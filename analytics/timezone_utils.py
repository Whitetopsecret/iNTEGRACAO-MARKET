from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

STATE_TO_TIMEZONE = {
    "AC": "America/Rio_Branco",
    "AL": "America/Maceio",
    "AM": "America/Manaus",
    "AP": "America/Belem",
    "BA": "America/Bahia",
    "CE": "America/Fortaleza",
    "DF": "America/Sao_Paulo",
    "ES": "America/Sao_Paulo",
    "GO": "America/Sao_Paulo",
    "MA": "America/Fortaleza",
    "MG": "America/Sao_Paulo",
    "MS": "America/Campo_Grande",
    "MT": "America/Cuiaba",
    "PA": "America/Belem",
    "PB": "America/Fortaleza",
    "PE": "America/Recife",
    "PI": "America/Fortaleza",
    "PR": "America/Sao_Paulo",
    "RJ": "America/Sao_Paulo",
    "RN": "America/Fortaleza",
    "RO": "America/Porto_Velho",
    "RR": "America/Boa_Vista",
    "RS": "America/Sao_Paulo",
    "SC": "America/Sao_Paulo",
    "SE": "America/Maceio",
    "SP": "America/Sao_Paulo",
    "TO": "America/Araguaina",
}


def resolve_timezone(state: Optional[str] = None, user_timezone: Optional[str] = None) -> str:
    if user_timezone:
        return user_timezone

    if state:
        normalized = state.strip().upper()
        if normalized in STATE_TO_TIMEZONE:
            return STATE_TO_TIMEZONE[normalized]

    return os.getenv("APP_TIMEZONE") or os.getenv("LOCAL_TIMEZONE") or "UTC"


def parse_utc(value: Optional[datetime | str]) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    return None


def convert_utc_to_local(value: Optional[datetime | str], state: Optional[str] = None, user_timezone: Optional[str] = None) -> Optional[datetime]:
    parsed = parse_utc(value)
    if parsed is None:
        return None

    tz_name = resolve_timezone(state=state, user_timezone=user_timezone)
    return parsed.astimezone(ZoneInfo(tz_name))


def format_utc_to_local(value: Optional[datetime | str], state: Optional[str] = None, user_timezone: Optional[str] = None, fmt: str = "%Y-%m-%d %H:%M:%S %Z") -> str:
    localized = convert_utc_to_local(value, state=state, user_timezone=user_timezone)
    if localized is None:
        return ""
    return localized.strftime(fmt)
