# loading_status.py
#
# Shared loading-screen status file for the launcher (HTTP /status) and
# launch_app.py (pip / startup progress). Kept tiny and dependency-free.

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "PyBibX Desktop"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def status_path() -> Path:
    return app_data_dir() / "loading_status.json"


def write_status(
    message: str,
    detail: str = "",
    *,
    phase: str = "start",
    percent: float | None = None,
) -> None:
    payload = {
        "phase": phase,
        "message": message,
        "detail": detail,
        "percent": percent,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = status_path()
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def read_status() -> dict:
    path = status_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {
            "phase": "start",
            "message": "Starting...",
            "detail": "",
            "percent": None,
            "updated_at": None,
        }
