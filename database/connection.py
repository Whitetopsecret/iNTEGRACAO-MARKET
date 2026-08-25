"""
Projeto Win Daniel — Camada de Conexão com o Banco de Dados (database/connection.py)

Fornece duas formas de acesso ao Supabase/PostgreSQL:

1. `get_supabase_client()` -> cliente oficial do Supabase (REST) quando as
   credenciais forem fornecidas.
2. `get_engine()` / `get_session()` -> SQLAlchemy para queries analíticas.
3. Fallback direto via psycopg2 para o fluxo do collector/simulador quando
   apenas `DATABASE_URL` estiver disponível.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

logger = logging.getLogger("win_daniel.database")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")


def _normalize_round_timestamp(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(normalized)
    else:
        dt = datetime.now(timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).replace(microsecond=0)


class ConfigurationError(RuntimeError):
    """Levantado quando as credenciais do banco não estão configuradas."""


def _get_db_connection():
    if not DATABASE_URL:
        raise ConfigurationError("DATABASE_URL precisa estar definida no .env")
    return psycopg2.connect(DATABASE_URL)


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.game_rounds (
                id BIGSERIAL PRIMARY KEY,
                round_id TEXT NOT NULL UNIQUE,
                multiplier NUMERIC(12, 2),
                round_timestamp TIMESTAMPTZ,
                crash_point NUMERIC(12, 2),
                raw_payload TEXT,
                source TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.collector_runs (
                id BIGSERIAL PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                rounds_inserted INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMPTZ
            )
            """
        )
    conn.commit()


# =========================================================================
# 1. Cliente Supabase (REST) — usado pelo collector quando disponível
# =========================================================================
@lru_cache(maxsize=1)
def get_supabase_client():
    """Retorna o cliente Supabase quando as chaves existem; senão usa o fallback direto."""
    if SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client

        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Cliente Supabase inicializado com sucesso.")
        return client

    logger.info("Usando fallback direto para PostgreSQL via DATABASE_URL")
    return None


def insert_round(round_id: str, multiplier: float, round_timestamp: str | datetime,
                 raw_payload: dict | None = None, source: str = "api") -> dict:
    """Insere uma rodada em game_rounds usando Supabase ou fallback direto para PostgreSQL."""
    normalized_timestamp = _normalize_round_timestamp(round_timestamp)
    client = get_supabase_client()
    if client is not None:
        payload = {
            "round_id": round_id,
            "multiplier": multiplier,
            "round_timestamp": normalized_timestamp.isoformat(),
            "raw_payload": raw_payload,
            "source": source,
        }
        response = client.table("game_rounds").upsert(payload, on_conflict="round_id").execute()
        return response.data

    conn = _get_db_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.game_rounds (
                    round_id, multiplier, crash_point, round_timestamp, raw_payload, source
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (round_id) DO NOTHING
                """,
                (
                    round_id,
                    float(multiplier),
                    float(multiplier),
                    normalized_timestamp,
                    None if raw_payload is None else json.dumps(raw_payload),
                    source,
                ),
            )
        conn.commit()
        return [{"round_id": round_id, "multiplier": multiplier, "source": source}]
    finally:
        conn.close()


def start_collector_run() -> str:
    """Registra o início da execução do collector/simulador."""
    client = get_supabase_client()
    if client is not None:
        response = client.table("collector_runs").insert({"status": "running"}).execute()
        return response.data[0]["id"]

    conn = _get_db_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.collector_runs (status) VALUES (%s) RETURNING id",
                ("running",),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
        return str(run_id)
    finally:
        conn.close()


def finish_collector_run(run_id: str, rounds_inserted: int, status: str = "success",
                          error_message: str | None = None) -> None:
    """Atualiza o registro de execução ao finalizar."""
    client = get_supabase_client()
    if client is not None:
        client.table("collector_runs").update({
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "rounds_inserted": rounds_inserted,
            "status": status,
            "error_message": error_message,
        }).eq("id", run_id).execute()
        return

    conn = _get_db_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.collector_runs
                SET finished_at = %s,
                    rounds_inserted = %s,
                    status = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    datetime.now(timezone.utc),
                    rounds_inserted,
                    status,
                    error_message,
                    int(run_id),
                ),
            )
        conn.commit()
    finally:
        conn.close()


# =========================================================================
# 2. SQLAlchemy Engine — usado por analytics/ para queries pesadas + pandas
# =========================================================================
@lru_cache(maxsize=1)
def get_engine():
    """Retorna uma Engine SQLAlchemy singleton para queries analíticas."""
    from sqlalchemy import create_engine

    if not DATABASE_URL:
        raise ConfigurationError("DATABASE_URL precisa estar definida no .env")

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
    logger.info("Engine SQLAlchemy inicializada com sucesso.")
    return engine


def get_session():
    """Retorna uma nova Session do SQLAlchemy vinculada à engine principal."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=get_engine())
    return Session()


# =========================================================================
# Teste rápido manual: `python -m database.connection`
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        get_supabase_client()
        print("✔ Conexão inicializada")
    except ConfigurationError as e:
        print(f"✘ Configuração ausente: {e}")

    try:
        engine = get_engine()
        with engine.connect() as conn:
            print("✔ Conexão direta PostgreSQL OK")
    except ConfigurationError as e:
        print(f"✘ DATABASE_URL não configurada: {e}")
    except Exception as e:
        print(f"✘ Falha ao conectar ao PostgreSQL: {e}")
