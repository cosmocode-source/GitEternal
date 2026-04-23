from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILE = "harvest.lock"
STALE_AFTER = timedelta(hours=2)


def _lock_path(vault_path: Path) -> Path:
    return vault_path / LOCK_FILE


def _read_lock(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _is_stale(lock_data: dict | None) -> bool:
    if not lock_data:
        return True
    started_raw = lock_data.get("started")
    if not isinstance(started_raw, str):
        return True
    try:
        started = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return datetime.now(tz=UTC) - started > STALE_AFTER


def acquire_lock(vault_path: Path) -> bool:
    path = _lock_path(vault_path)
    lock_data = _read_lock(path)

    if path.exists() and not _is_stale(lock_data):
        return False

    if path.exists() and _is_stale(lock_data):
        logger.warning("Stale lock detected at %s; overwriting", path)

    payload = {"pid": os.getpid(), "started": datetime.now(tz=UTC).isoformat()}
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return True


def release_lock(vault_path: Path) -> None:
    try:
        _lock_path(vault_path).unlink()
    except FileNotFoundError:
        pass


def is_locked(vault_path: Path) -> bool:
    path = _lock_path(vault_path)
    if not path.exists():
        return False
    return not _is_stale(_read_lock(path))
