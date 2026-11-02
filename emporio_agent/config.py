"""Paths and the notion of "now" for the store (America/Campo_Grande).

AGENT_NOW lets a run be pinned to a date so time-dependent rules (return windows,
store hours, overdue deliveries) behave reproducibly. The dataset snapshot ends in
March 2026, so the examples in this repo are generated with AGENT_NOW=2026-03-25T10:30:00.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SESSIONS_DIR = ROOT / "sessions"
STORE_TZ = ZoneInfo("America/Campo_Grande")


def now() -> datetime:
    raw = os.getenv("AGENT_NOW")
    if raw:
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=STORE_TZ)
    return datetime.now(STORE_TZ)


def today() -> date:
    return now().date()
