#!/usr/bin/env python3
"""Lógica de gatilho temporal com espelho de 24h para o collector."""

from __future__ import annotations

import argparse
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import psycopg2
from dotenv import load_dotenv

from analytics.timezone_utils import resolve_timezone

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
STATE = os.getenv("STATE")
USER_TIMEZONE = os.getenv("USER_TIMEZONE")
DEFAULT_TIMEZONE = resolve_timezone(state=STATE, user_timezone=USER_TIMEZONE)
EVENT_TABLE = os.getenv("TRIGGER_EVENTS_TABLE", "temporal_trigger_events")


class TemporalMirrorEngine:
    def __init__(self, timezone_name: Optional[str] = None) -> None:
        self.timezone_name = timezone_name or DEFAULT_TIMEZONE
        self.local_tz = ZoneInfo(self.timezone_name)
        self._pre_alert_sent: set[str] = set()
        self._final_alert_sent: set[str] = set()

    def get_connection(self):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL não configurada no .env")
        return psycopg2.connect(DATABASE_URL)

    def ensure_event_table(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS public.{EVENT_TABLE} (
                    id BIGSERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    round_id TEXT,
                    observed_at TIMESTAMPTZ,
                    target_at TIMESTAMPTZ,
                    scenario TEXT,
                    calm BOOLEAN,
                    media_intervalo NUMERIC(12, 3),
                    desvio_intervalo NUMERIC(12, 3),
                    stable_count INTEGER,
                    compensation_seconds NUMERIC(12, 3),
                    delta_seconds NUMERIC(12, 3),
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()

    def _record_event(self, conn, payload: dict[str, Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO public.{EVENT_TABLE} (
                    event_type,
                    round_id,
                    observed_at,
                    target_at,
                    scenario,
                    calm,
                    media_intervalo,
                    desvio_intervalo,
                    stable_count,
                    compensation_seconds,
                    delta_seconds,
                    notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["event_type"],
                    payload.get("round_id"),
                    payload.get("observed_at"),
                    payload.get("target_at"),
                    payload.get("scenario"),
                    payload.get("calm"),
                    payload.get("media_intervalo"),
                    payload.get("desvio_intervalo"),
                    payload.get("stable_count"),
                    payload.get("compensation_seconds"),
                    payload.get("delta_seconds"),
                    payload.get("notes"),
                ),
            )
        conn.commit()

    def _fetch_rounds(self, conn) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, round_id, created_at, multiplier
                FROM public.game_rounds
                WHERE created_at IS NOT NULL AND multiplier IS NOT NULL
                ORDER BY created_at ASC
                """
            )
            rows = cur.fetchall()

        return [
            {
                "id": row[0],
                "round_id": row[1],
                "created_at": row[2],
                "multiplier": float(row[3]),
            }
            for row in rows
        ]

    def _recent_interval_stability(self, intervals: list[float]) -> tuple[bool, float, float, int]:
        if not intervals:
            return False, 0.0, 0.0, 0

        media = statistics.fmean(intervals)
        desvio = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0
        stable_count = 0
        for interval in intervals:
            if interval is None:
                continue
            if interval > max(90.0, media * 2.0):
                continue
            if abs(interval - media) > max(3.0, media * 0.25):
                continue
            if desvio > max(5.0, media * 0.20):
                continue
            stable_count += 1

        return stable_count >= 6, media, desvio, stable_count

    def evaluate(self, conn, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
        self.ensure_event_table(conn)
        rounds = self._fetch_rounds(conn)
        if not rounds:
            return None

        now_utc = now or datetime.now(timezone.utc)
        now_local = now_utc.astimezone(self.local_tz)

        rows = sorted(rounds, key=lambda item: item["created_at"])
        latest_row = rows[-1]
        latest_local = latest_row["created_at"].astimezone(self.local_tz)

        today_rows = [row for row in rows if row["created_at"].astimezone(self.local_tz).date() == now_local.date()]
        if today_rows:
            today_high = max(today_rows, key=lambda item: item["multiplier"])
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT 1 FROM public.{EVENT_TABLE} WHERE event_type = %s AND round_id = %s",
                    ("high_candle", today_high["round_id"]),
                )
                exists = cur.fetchone() is not None
            if not exists:
                self._record_event(
                    conn,
                    {
                        "event_type": "high_candle",
                        "round_id": today_high["round_id"],
                        "observed_at": today_high["created_at"],
                        "target_at": None,
                        "scenario": None,
                        "calm": None,
                        "media_intervalo": None,
                        "desvio_intervalo": None,
                        "stable_count": None,
                        "compensation_seconds": None,
                        "delta_seconds": None,
                        "notes": "vela alta (rosa) registrada",
                    },
                )

        prev_day = latest_local.date() - timedelta(days=1)
        prev_day_rows = [row for row in rows if row["created_at"].astimezone(self.local_tz).date() == prev_day]
        if not prev_day_rows:
            return None

        prev_high = max(prev_day_rows, key=lambda item: item["multiplier"])
        prev_high_time = prev_high["created_at"].astimezone(self.local_tz).time()
        target_local = datetime.combine(now_local.date(), prev_high_time, tzinfo=self.local_tz)
        if target_local <= now_local:
            target_local = target_local + timedelta(days=1)

        intervals = []
        previous_dt: Optional[datetime] = None
        for row in rows:
            current_dt = row["created_at"]
            if previous_dt is not None:
                intervals.append((current_dt - previous_dt).total_seconds())
            previous_dt = current_dt

        recent_intervals = intervals[-8:]
        calm, media, desvio, stable_count = self._recent_interval_stability(recent_intervals)
        compensation_seconds = round(max(0.0, (0.5 * media) + (0.8 * desvio)), 2)
        tolerance_seconds = max(compensation_seconds + 600.0, 1800.0)
        delta_seconds = (target_local - now_local).total_seconds()

        if abs(delta_seconds) <= compensation_seconds:
            scenario = "[A] Espelho Direto Compensado"
        elif abs(delta_seconds) <= tolerance_seconds:
            scenario = "[B] Janela de Tolerância Ampliada"
        else:
            scenario = "[C] Zona de Invalidação (Quebra de Padrão)"

        key = target_local.strftime("%Y-%m-%d %H:%M:%S")
        if now_local >= (target_local - timedelta(hours=1)) and key not in self._pre_alert_sent:
            self._pre_alert_sent.add(key)
            payload = {
                "event_type": "pre_alert",
                "round_id": latest_row["round_id"],
                "observed_at": now_utc,
                "target_at": target_local.astimezone(timezone.utc),
                "scenario": scenario,
                "calm": calm,
                "media_intervalo": round(media, 3),
                "desvio_intervalo": round(desvio, 3),
                "stable_count": stable_count,
                "compensation_seconds": compensation_seconds,
                "delta_seconds": round(delta_seconds, 3),
                "notes": "alerta prévio do espelho temporal",
            }
            self._record_event(conn, payload)
            return {
                "phase": "pre_alert",
                "target_local": target_local,
                "scenario": scenario,
                "message": f"ALERTA PRÉVIO: o espelho temporal em {target_local.strftime('%Y-%m-%d %H:%M:%S')} está a 1h de distância.",
                "calm": calm,
                "media_intervalo": round(media, 3),
                "desvio_intervalo": round(desvio, 3),
                "stable_count": stable_count,
                "compensation_seconds": compensation_seconds,
                "delta_seconds": round(delta_seconds, 3),
            }

        if now_local >= (target_local - timedelta(minutes=2)) and key not in self._final_alert_sent:
            self._final_alert_sent.add(key)
            final_ok = calm and scenario in {"[A] Espelho Direto Compensado", "[B] Janela de Tolerância Ampliada"}
            if final_ok:
                message = "SINAL FINAL: confirmação de entrada — calmaria e espelho sustentados."
            else:
                message = "SINAL FINAL: invalidação — calmaria ou espelho não sustentados."
            payload = {
                "event_type": "final_recheck",
                "round_id": latest_row["round_id"],
                "observed_at": now_utc,
                "target_at": target_local.astimezone(timezone.utc),
                "scenario": scenario,
                "calm": calm,
                "media_intervalo": round(media, 3),
                "desvio_intervalo": round(desvio, 3),
                "stable_count": stable_count,
                "compensation_seconds": compensation_seconds,
                "delta_seconds": round(delta_seconds, 3),
                "notes": message,
            }
            self._record_event(conn, payload)
            return {
                "phase": "final_recheck",
                "target_local": target_local,
                "scenario": scenario,
                "message": message,
                "calm": calm,
                "media_intervalo": round(media, 3),
                "desvio_intervalo": round(desvio, 3),
                "stable_count": stable_count,
                "compensation_seconds": compensation_seconds,
                "delta_seconds": round(delta_seconds, 3),
            }

        return None


def run_loop(interval_seconds: float = 15.0, once: bool = False) -> int:
    engine = TemporalMirrorEngine(timezone_name=DEFAULT_TIMEZONE)
    conn = engine.get_connection()
    try:
        while True:
            event = engine.evaluate(conn)
            if event:
                print(f"[{datetime.now(ZoneInfo(engine.timezone_name)).strftime('%Y-%m-%d %H:%M:%S %Z')}] {event['message']}")
                print(f"  -> cenário: {event['scenario']} | calm={event['calm']} | media={event['media_intervalo']} | desvio={event['desvio_intervalo']} | estáveis={event['stable_count']} | delta={event['delta_seconds']}s")
            if once:
                break
            time.sleep(interval_seconds)
    finally:
        conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Gatilho de espelho temporal para o collector")
    parser.add_argument("--once", action="store_true", help="executa uma única verificação")
    parser.add_argument("--interval", type=float, default=15.0, help="intervalo entre verificações em segundos")
    args = parser.parse_args()
    return run_loop(interval_seconds=args.interval, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
