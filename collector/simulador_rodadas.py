"""
Projeto Win Daniel — Simulador de Rodadas (collector/simulador_rodadas.py)

Gera rodadas de um jogo crash de forma 100% SINTÉTICA (nenhuma conta,
navegador ou plataforma real envolvida) e as persiste no Supabase pelo
mesmo pipeline do Coletor V1 (`database.connection.insert_round`).

Serve para validar de ponta a ponta a stack do projeto — gerador ->
Supabase -> queries de analytics/ -> Metabase — sem depender de login,
saldo real ou disponibilidade de um feed externo. Depois, se quiser,
basta trocar a fonte por um feed público/demo real usando o mesmo
formato de dados (veja collector/coletor_v1.py).

O modelo de distribuição do multiplicador abaixo é uma implementação
GENÉRICA e de conhecimento público (o formato "1 / (1 - U)" ajustado por
house edge, usado em várias implementações open-source de jogos crash
provably-fair). Ele NÃO reproduz nem tenta imitar o algoritmo real de
nenhuma plataforma específica — é só um gerador estatisticamente
plausível para preencher o pipeline com dados de teste.

Uso:
    python -m collector.simulador_rodadas --n 200 --intervalo 0.5
    python -m collector.simulador_rodadas --n 0 --intervalo 1   # contínuo
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import (  # noqa: E402
    insert_round,
    start_collector_run,
    finish_collector_run,
    get_supabase_client,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulador_rodadas")


def gerar_multiplicador(house_edge: float = 0.04) -> float:
    """
    Gera um multiplicador de crash sintético.

    Modelo público/genérico: crash_point = (1 - house_edge) / (1 - U),
    com U ~ Uniform(0, 1) e uma probabilidade `house_edge` de "crash
    instantâneo" em 1.00x. Resultado limitado a 1000x por segurança.
    """
    u = random.random()
    if u < house_edge:
        return 1.00
    valor = (1 - house_edge) / (1 - u)
    return round(min(valor, 1000.0), 2)


def gerar_rodada() -> dict:
    return {
        "round_id": str(uuid.uuid4()),
        "multiplier": gerar_multiplicador(),
        "round_timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_payload": None,
        "source": "simulado",
    }


def run(n_rodadas: int | None, intervalo_segundos: float) -> None:
    get_supabase_client()  # valida credenciais antes de iniciar
    run_id = start_collector_run()
    inseridas = 0
    status = "success"
    erro = None

    try:
        alvo = f"{n_rodadas} rodadas" if n_rodadas else "contínuo (Ctrl+C para parar)"
        logger.info("Iniciando simulação (run_id=%s) — %s", run_id, alvo)

        while n_rodadas is None or inseridas < n_rodadas:
            rodada = gerar_rodada()
            insert_round(**rodada)
            inseridas += 1
            logger.info("Rodada %d salva: multiplier=%.2fx", inseridas, rodada["multiplier"])
            time.sleep(intervalo_segundos)

    except KeyboardInterrupt:
        logger.info("Simulação interrompida pelo usuário.")
    except Exception as e:
        status = "failed"
        erro = str(e)
        logger.exception("Erro durante a simulação")
        raise
    finally:
        finish_collector_run(run_id, inseridas, status=status, error_message=erro)
        logger.info("Execução registrada em collector_runs (rodadas inseridas: %d)", inseridas)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simulador de rodadas — Coletor V1 (modo dados sintéticos)"
    )
    parser.add_argument(
        "--n", type=int, default=200,
        help="Quantidade de rodadas a gerar (padrão: 200). Use 0 para rodar continuamente.",
    )
    parser.add_argument(
        "--intervalo", type=float, default=0.5,
        help="Segundos entre rodadas (padrão: 0.5).",
    )
    args = parser.parse_args()

    run(n_rodadas=None if args.n == 0 else args.n, intervalo_segundos=args.intervalo)
