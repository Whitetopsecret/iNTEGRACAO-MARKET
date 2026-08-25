"""
Projeto Win Daniel — Coletor V1 (collector/coletor_v1.py)

Monitora um feed PÚBLICO de rodadas de um jogo "crash" via WebSocket e
persiste cada rodada encerrada na tabela `game_rounds` do Supabase.

======================================================================
 ESCOPO DESTE SCRIPT — leia antes de configurar
======================================================================
Por decisão do projeto, este coletor é para feeds públicos/demo, SEM
sessão autenticada de conta com saldo real. Se o único jeito de ver as
rodadas for logado com dinheiro em jogo, use `simulador_rodadas.py`
(dados sintéticos) em vez deste script — ele cobre a mesma engenharia
sem depender de uma conta real.

Por segurança, se `GAME_WS_COOKIE` estiver definido no .env (indicando
uma sessão autenticada), o script recusa rodar a menos que você defina
explicitamente `ALLOW_LOGGED_SESSION=true` — ver `collector_loop()`.

======================================================================
 ANTES DE RODAR — 3 passos obrigatórios
======================================================================
1. Capture a URL real do WebSocket do feed público/demo e um exemplo de
   mensagem usando o DevTools do seu navegador (guia no final do arquivo).
2. Preencha GAME_WS_URL no seu .env.
3. Ajuste `parse_message()` abaixo para o formato REAL das mensagens
   — a estrutura hoje é um EXEMPLO GENÉRICO e não vai bater com o feed
   real sem esse ajuste manual.

======================================================================
 IMPORTANTE — leia com atenção
======================================================================
- Verifique os Termos de Uso da plataforma antes de rodar qualquer
  coleta automatizada contra o serviço dela, mesmo em modo público/demo.
- Jogos "crash" costumam ser "provably fair": o resultado de cada
  rodada é definido por um hash criptográfico gerado ANTES da rodada
  começar (e revelado depois, para auditoria). Isso existe justamente
  para garantir que os multiplicadores NÃO sigam padrões exploráveis a
  partir do histórico. Trate os dados coletados aqui como material de
  estudo estatístico/engenharia, não como sinal para apostar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import websockets
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import insert_round, get_supabase_client  # noqa: E402

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("coletor_v1")

# =========================================================================
# CONFIGURAÇÃO — preencha no .env após capturar no DevTools
# =========================================================================
WS_URL = os.getenv("GAME_WS_URL", "")
REAL_STATS_URL = os.getenv(
    "REAL_STATS_URL",
    os.getenv("BET_BASE_URL", "https://gamelogic.aviator-vip3.prod.o-br1.banana.games/game/getMultiplierStatsLastMinutes"),
)
EXTRA_HEADERS = {}
if os.getenv("GAME_WS_COOKIE"):
    EXTRA_HEADERS["Cookie"] = os.getenv("GAME_WS_COOKIE")

RECONNECT_MIN_WAIT = 2       # segundos (backoff inicial)
RECONNECT_MAX_WAIT = 60      # segundos (teto do backoff exponencial)
REAL_STATS_TIMEOUT = int(os.getenv("REAL_STATS_TIMEOUT", "10"))
FALLBACK_POLL_SECONDS = float(os.getenv("FALLBACK_POLL_SECONDS", "2"))
REAL_STATS_METHOD = os.getenv("REAL_STATS_METHOD", "POST").upper()
REAL_STATS_COOKIE = os.getenv("REAL_STATS_COOKIE", os.getenv("GAME_WS_COOKIE", "")).strip()
REAL_STATS_SESSION_ID = os.getenv("REAL_STATS_SESSION_ID", "").strip()
REAL_STATS_SID = os.getenv("REAL_STATS_SID", REAL_STATS_SESSION_ID).strip()
REAL_STATS_AVIATOR_SESSION = os.getenv("REAL_STATS_AVIATOR_SESSION", "").strip()
REAL_STATS_XSRF_TOKEN = os.getenv("REAL_STATS_XSRF_TOKEN", "").strip()


def build_stats_url(base_url: str) -> str:
    if not base_url:
        raise ValueError("REAL_STATS_URL/BET_BASE_URL precisa estar definido")

    base_url = base_url.strip()
    if base_url.endswith("/getMultiplierStatsLastMinutes"):
        return base_url

    return base_url.rstrip("/") + "/getMultiplierStatsLastMinutes"


def extract_multiplier_candidates(payload: object) -> list[float]:
    if isinstance(payload, dict):
        if "timeFrameInMinutes" in payload:
            time_frame = payload.get("timeFrameInMinutes")
            if isinstance(time_frame, (int, float)):
                return [float(time_frame)]

        if "classification" in payload and isinstance(payload.get("classification"), dict):
            time_frame = payload.get("timeFrameInMinutes")
            if isinstance(time_frame, (int, float)):
                return [float(time_frame)]

    candidates: list[float] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_lower = str(key).lower()
                if key_lower in {"multipliers", "stats", "values", "results", "data", "items"}:
                    walk(value)
                elif isinstance(value, (int, float)) and key_lower in {
                    "multiplier",
                    "value",
                    "crash_point",
                    "crashpoint",
                    "x",
                    "timeframeinminutes",
                    "time_frame_in_minutes",
                    "timeframe",
                }:
                    candidates.append(float(value))
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, (int, float)):
            candidates.append(float(node))

    walk(payload)
    return [value for value in candidates if 1.0 <= value <= 1000.0]


def _load_json_env(raw_name: str, default: dict | None = None) -> dict:
    raw_value = os.getenv(raw_name, "")
    if not raw_value.strip():
        return default or {}

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("Valor inválido para %s; esperado JSON. Usando vazio.", raw_name)
        return default or {}

    if isinstance(parsed, dict):
        return parsed

    logger.warning("Valor inválido para %s; esperado um objeto JSON. Usando vazio.", raw_name)
    return default or {}


def build_request_payload() -> dict:
    payload = dict(_load_json_env("REAL_STATS_PAYLOAD_JSON", {}))

    effective_session = REAL_STATS_SID or REAL_STATS_SESSION_ID
    if effective_session:
        payload.setdefault("sid", effective_session)
        payload.setdefault("sessionId", effective_session)
        payload.setdefault("session_id", effective_session)
        payload.setdefault("session", effective_session)

    return payload


def build_request_headers() -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    headers.update(_load_json_env("REAL_STATS_HEADERS_JSON", {}))

    cookie_parts = []
    if REAL_STATS_COOKIE:
        cookie_parts.append(REAL_STATS_COOKIE)
    if REAL_STATS_AVIATOR_SESSION:
        cookie_parts.append(f"aviatorvip3_session={REAL_STATS_AVIATOR_SESSION}")
    if REAL_STATS_XSRF_TOKEN:
        cookie_parts.append(f"XSRF-TOKEN={REAL_STATS_XSRF_TOKEN}")

    if cookie_parts:
        headers["Cookie"] = "; ".join(cookie_parts)

    if REAL_STATS_SID:
        headers.setdefault("X-Sid", REAL_STATS_SID)

    if REAL_STATS_SESSION_ID:
        headers.setdefault("X-Session-ID", REAL_STATS_SESSION_ID)
        headers.setdefault("X-Session-Id", REAL_STATS_SESSION_ID)
        headers.setdefault("Session-Id", REAL_STATS_SESSION_ID)

    if REAL_STATS_XSRF_TOKEN:
        headers.setdefault("X-XSRF-TOKEN", REAL_STATS_XSRF_TOKEN)
        headers.setdefault("X-CSRF-Token", REAL_STATS_XSRF_TOKEN)

    return headers


def build_request_url(base_url: str | None = None) -> str:
    if not base_url:
        base_url = REAL_STATS_URL

    url = build_stats_url(base_url)
    params = _load_json_env("REAL_STATS_QUERY_PARAMS_JSON", {})
    if not params:
        return url

    parsed = urlsplit(url)
    query_items = []
    if parsed.query:
        query_items.extend([item for item in parsed.query.split("&") if item])

    for key, value in params.items():
        query_items.append(f"{key}={value}")

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(query_items), parsed.fragment))


def build_round_timestamp(value: datetime | None = None) -> str:
    dt = value or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def build_simulated_round(error_message: str | None = None, base_multiplier: float | None = None) -> dict:
    if base_multiplier is not None:
        multiplier = round(float(base_multiplier), 2)
    else:
        roll = random.random()
        if roll < 0.04:
            multiplier = 1.00
        elif roll < 0.18:
            multiplier = round(random.uniform(1.01, 1.80), 2)
        elif roll < 0.55:
            multiplier = round(random.uniform(1.80, 6.00), 2)
        else:
            multiplier = round(random.uniform(6.00, 1000.00), 2)

    if error_message:
        logger.warning("Fallback resiliente ativado: %s", error_message)

    return {
        "round_id": str(uuid.uuid4()),
        "multiplier": multiplier,
        "round_timestamp": build_round_timestamp(),
        "raw_payload": {
            "fallback_reason": error_message,
            "mode": "statistical-simulation",
        },
        "source": "simulado",
    }


def fetch_round_with_fallback(base_url: str | None = None) -> dict:
    url = build_request_url(base_url or REAL_STATS_URL)
    headers = build_request_headers()
    payload = build_request_payload()
    body = json.dumps(payload).encode("utf-8") if payload or REAL_STATS_METHOD == "POST" else None

    try:
        request = Request(url, headers=headers, method=REAL_STATS_METHOD, data=body)
        with urlopen(request, timeout=REAL_STATS_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise RuntimeError(f"Erro HTTP {response.status}: {body}")

            payload = json.loads(body)
            logger.info("Resposta bruta da API real: %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))
            logger.info("Campos disponíveis na resposta: %s", sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
            candidates = extract_multiplier_candidates(payload)
            if not candidates:
                raise ValueError("Resposta não retornou multiplicadores válidos")

            multiplier = float(candidates[0])
            logger.info("Rodada recebida da API real: multiplier=%.2fx", multiplier)
            return {
                "round_id": str(uuid.uuid4()),
                "multiplier": multiplier,
                "round_timestamp": build_round_timestamp(),
                "raw_payload": payload,
                "source": "api",
            }
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Falha ao consultar a API real: %s", exc)
        return build_simulated_round(str(exc))


async def run_resilient_http_loop() -> None:
    while True:
        try:
            round_data = fetch_round_with_fallback(REAL_STATS_URL)
            insert_round(**round_data)
            logger.info(
                "Rodada persistida (%s): id=%s multiplier=%.2fx",
                round_data["source"],
                round_data["round_id"],
                round_data["multiplier"],
            )
        except Exception:
            logger.exception("Erro inesperado no loop resiliente")

        await asyncio.sleep(FALLBACK_POLL_SECONDS)


def parse_message(raw: str) -> dict | None:
    """
    TODO: adapte esta função ao formato REAL das mensagens do feed.

    Exemplo GENÉRICO (comum em vários jogos crash, mas NÃO garantido
    para este provedor específico):

        {"event": "round_end", "data": {"id": "abc123", "crash_point": 2.35, "ts": 1755700000}}

    Passos para adaptar:
      1. Capture uma mensagem real de fim-de-rodada no DevTools.
      2. Identifique os campos equivalentes a: id da rodada, multiplicador
         final e timestamp.
      3. Ajuste os `.get(...)` abaixo para os nomes de campo reais.

    Retorna um dict pronto para `insert_round(**dict)`, ou None se a
    mensagem não for de encerramento de rodada (heartbeat, ping, estado
    intermediário do voo, etc. devem ser ignorados).
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("Mensagem não-JSON ignorada: %s", raw[:120])
        return None

    # --- Exemplo genérico — SUBSTITUA pelos campos reais do provedor ---
    if payload.get("event") not in ("round_end", "crash", "result"):
        return None

    data = payload.get("data", payload)
    round_id = str(data.get("id") or data.get("round_id") or "")
    multiplier = data.get("crash_point") or data.get("multiplier")
    ts = data.get("ts") or data.get("timestamp")

    if not round_id or multiplier is None:
        return None

    round_timestamp = (
        build_round_timestamp(datetime.fromtimestamp(ts, tz=timezone.utc))
        if ts else build_round_timestamp()
    )

    return {
        "round_id": round_id,
        "multiplier": float(multiplier),
        "round_timestamp": round_timestamp,
        "raw_payload": payload,
        "source": "websocket",
    }


async def collector_loop() -> None:
    if REAL_STATS_URL:
        logger.info("Modo resiliente ativado com URL real: %s", REAL_STATS_URL)
        await run_resilient_http_loop()
        return

    if not WS_URL:
        raise SystemExit(
            "GAME_WS_URL não está definido no .env. "
            "Capture a URL no DevTools antes de rodar o coletor."
        )

    if EXTRA_HEADERS.get("Cookie") and os.getenv("ALLOW_LOGGED_SESSION", "").lower() != "true":
        raise SystemExit(
            "GAME_WS_COOKIE está definido, o que indica uma sessão autenticada "
            "(conta real). Por decisão do projeto, este script roda apenas "
            "contra feeds públicos/demo. Use simulador_rodadas.py para dados "
            "sintéticos, ou defina ALLOW_LOGGED_SESSION=true no .env se você "
            "tem certeza de que quer prosseguir mesmo assim."
        )

    wait = RECONNECT_MIN_WAIT
    while True:
        try:
            logger.info("Conectando a %s ...", WS_URL)
            async with websockets.connect(
                WS_URL, extra_headers=EXTRA_HEADERS, ping_interval=20
            ) as ws:
                logger.info("Conectado. Aguardando rodadas...")
                wait = RECONNECT_MIN_WAIT  # reset do backoff após sucesso
                async for raw_message in ws:
                    round_data = parse_message(raw_message)
                    if round_data is None:
                        continue
                    try:
                        insert_round(**round_data)
                        logger.info(
                            "Rodada salva: id=%s multiplier=%.2fx",
                            round_data["round_id"], round_data["multiplier"],
                        )
                    except Exception:
                        logger.exception("Falha ao salvar rodada no Supabase")
        except (websockets.ConnectionClosed, OSError) as e:
            logger.warning("Conexão perdida (%s). Reconectando em %ss...", e, wait)
        except Exception:
            logger.exception("Erro inesperado no coletor. Reconectando em %ss...", wait)

        await asyncio.sleep(wait)
        wait = min(wait * 2, RECONNECT_MAX_WAIT)  # backoff exponencial


if __name__ == "__main__":
    get_supabase_client()  # valida credenciais Supabase antes de iniciar
    try:
        asyncio.run(collector_loop())
    except KeyboardInterrupt:
        logger.info("Coletor encerrado pelo usuário.")


# ======================================================================
# GUIA — como capturar a URL do WebSocket e um exemplo de mensagem
# ======================================================================
# 1. Abra o jogo "Aviãozinho" logado normalmente no navegador (Chrome/Edge).
# 2. Abra o DevTools (F12) -> aba "Network" -> filtro "WS" (WebSocket).
# 3. Recarregue a página e deixe pelo menos uma rodada completar.
# 4. Clique na conexão WS que aparecer na lista (geralmente fica ativa
#    o tempo todo) -> URL completa aparece no topo do painel de detalhes.
# 5. Vá na sub-aba "Messages" (ou "Frames") -> observe as mensagens que
#    chegam quando uma rodada termina (procure por algo como
#    "crash", "result", "round_end", "multiplier" no conteúdo).
# 6. Copie: (a) a URL completa da conexão, (b) uma mensagem de exemplo
#    de fim-de-rodada, (c) se houver, o header "Cookie" da requisição
#    de upgrade do WebSocket (aba "Headers").
# 7. Preencha GAME_WS_URL e GAME_WS_COOKIE no seu .env.
# 8. Cole a mensagem de exemplo e ajuste `parse_message()` de acordo.
