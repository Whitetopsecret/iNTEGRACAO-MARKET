#!/usr/bin/env python3
"""Collector simples para buscar um dado público e salvar no Supabase."""

import argparse
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Optional
from urllib.request import urlopen

import psycopg2
from dotenv import load_dotenv

from analytics.timezone_utils import format_utc_to_local, resolve_timezone


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
TABLE_NAME = os.getenv("BTC_TABLE_NAME", "btc_price_history")
SYMBOL = os.getenv("BTC_SYMBOL", "BTCUSDT")
API_URL = os.getenv("BTC_API_URL", "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
STATE = os.getenv("STATE")
USER_TIMEZONE = os.getenv("USER_TIMEZONE")


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não configurada no .env")
    return psycopg2.connect(DATABASE_URL)


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS public.{TABLE_NAME} (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                price NUMERIC(12, 2) NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    conn.commit()


def fetch_public_price() -> float:
    with urlopen(API_URL, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return float(payload["price"])


def insert_price(conn, symbol: str, price: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO public.{TABLE_NAME} (symbol, price, fetched_at)
            VALUES (%s, %s, %s)
            """,
            (symbol, price, datetime.now(timezone.utc)),
        )
    conn.commit()


def check_alert(history: Deque[float], current: float) -> Optional[str]:
    if len(history) < 3:
        return None

    prev1 = history[-1]
    prev2 = history[-2]
    prev3 = history[-3]
    delta1 = current - prev1
    delta2 = prev1 - prev2
    delta3 = prev2 - prev3

    if delta1 > 0 and delta2 > 0 and delta3 > 0:
        return "ALERTA: sequência crescente em 3 passos"
    if delta1 < 0 and delta2 < 0 and delta3 < 0:
        return "ALERTA: sequência decrescente em 3 passos"
    return None


def collect_once() -> float:
    conn = get_connection()
    try:
        ensure_table(conn)
        price = fetch_public_price()
        insert_price(conn, SYMBOL, price)
        return price
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Coletor de preço público no Supabase")
    parser.add_argument("--once", action="store_true", help="executa uma única coleta")
    parser.add_argument("--interval", type=float, default=15.0, help="intervalo em segundos entre coletas")
    args = parser.parse_args()

    history: Deque[float] = deque(maxlen=3)

    while True:
        try:
            price = collect_once()
            history.append(price)
            alert = check_alert(history, price)
            local_tz = resolve_timezone(state=STATE, user_timezone=USER_TIMEZONE)
            if alert:
                print(f"{alert} | {SYMBOL} = {price:.2f} USD")
            else:
                print(
                    f"[{format_utc_to_local(datetime.now(timezone.utc), state=STATE, user_timezone=USER_TIMEZONE)}] {SYMBOL} = {price:.2f} USD ({local_tz})"
                )
        except Exception as exc:
            print(f"Erro na coleta: {exc}")

        if args.once:
            break

        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
