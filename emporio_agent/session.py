"""JSON-file persistence so a conversation (history + verification state) survives restarts."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import SESSIONS_DIR


def _path(session_id: str, directory: Path | None = None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    return (directory or SESSIONS_DIR) / f"{safe}.json"


def load(session_id: str, directory: Path | None = None) -> dict:
    p = _path(session_id, directory)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"history": [], "state": {}}


def save(session_id: str, data: dict, directory: Path | None = None) -> None:
    p = _path(session_id, directory)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
