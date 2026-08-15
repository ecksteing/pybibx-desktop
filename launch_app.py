# launch_app.py
#
# Starts the official pybibx Flask web app from the bundled portable Python.
#
# Update policy (mirrors Bibliometrix Desktop):
#   - Prefer wheels / binary installs (CPU PyTorch index for torch*)
#   - Newer pybibx installs into the portable environment when online
#   - At most weekly PyPI checks
#   - If offline / update fails, the already-installed copy still launches

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "PyBibX Desktop"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5173
UPDATE_CHECK_INTERVAL_DAYS = 7


def _app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp_path() -> Path:
    return _app_data_dir() / "pypi_update_check.txt"


def _log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    try:
        log_file = _app_data_dir() / "runtime.log"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _installed_pybibx_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("pybibx")
    except Exception:
        return None


def _pypi_pybibx_version(timeout: float = 8.0) -> str | None:
    url = "https://pypi.org/pypi/pybibx/json"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME}/launch_app"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return str(payload["info"]["version"])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, ValueError, OSError):
        return None


def _parse_version(text: str) -> tuple:
    parts: list[int] = []
    for chunk in text.replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            break
    return tuple(parts) if parts else (0,)


def _should_run_update_check() -> bool:
    path = _stamp_path()
    if not path.is_file():
        return True
    try:
        stamp = path.read_text(encoding="utf-8").strip()
    except OSError:
        return True
    stamp_clean = stamp.rstrip("Zz")
    try:
        last = datetime.strptime(stamp_clean, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    age_days = (datetime.now(timezone.utc) - last).total_seconds() / 86400.0
    return age_days >= UPDATE_CHECK_INTERVAL_DAYS


def _record_update_check() -> None:
    try:
        _stamp_path().write_text(
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            encoding="utf-8",
        )
    except OSError as exc:
        _log(f"Could not write PyPI check stamp: {exc}")


def _pip_install(args: list[str]) -> int:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *args]
    _log("Running: " + " ".join(cmd))
    import subprocess

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(cmd, creationflags=creationflags)
    return int(result.returncode)


def ensure_runtime_ready() -> bool:
    """Install pybibx (+ CPU torch) if missing. Returns True when importable."""
    if _installed_pybibx_version():
        return True

    _log("pybibx not installed; bootstrapping runtime packages...")
    # CPU wheels first so students avoid multi-GB CUDA builds.
    code = _pip_install(
        [
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            "https://download.pytorch.org/whl/cpu",
        ]
    )
    if code != 0:
        _log(f"CPU torch install exited with {code}; continuing with default PyPI torch.")

    code = _pip_install(["pybibx"])
    if code != 0:
        _log(f"pip install pybibx failed with exit code {code}")
        return False

    return _installed_pybibx_version() is not None


def maybe_update_pybibx() -> None:
    enable = os.environ.get("PYBIBX_DESKTOP_RUNTIME_UPDATES", "1").strip() not in {
        "0",
        "false",
        "False",
        "no",
        "NO",
    }
    if not enable:
        _log("Runtime updates disabled by environment.")
        return
    if not _should_run_update_check():
        _log("Skipping PyPI update check (checked within the last week).")
        return

    current = _installed_pybibx_version()
    latest = _pypi_pybibx_version()
    if latest is None:
        _log("PyPI unreachable or pybibx metadata missing; keeping installed copy.")
        _record_update_check()
        return

    if current and _parse_version(latest) <= _parse_version(current):
        _log(f"pybibx is up to date ({current}).")
        _record_update_check()
        return

    _log(f"Updating pybibx: {current or 'none'} -> {latest}")
    code = _pip_install([f"pybibx=={latest}"])
    if code == 0:
        _log(f"pybibx updated to {_installed_pybibx_version() or latest}")
    else:
        _log(f"pybibx update failed with exit code {code}; continuing with {current}")
    _record_update_check()


def start_web_app() -> str:
    host = os.environ.get("PYBIBX_DESKTOP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    port = int(os.environ.get("PYBIBX_DESKTOP_PORT", str(DEFAULT_PORT)))
    open_browser = os.environ.get("PYBIBX_DESKTOP_LAUNCH_BROWSER", "0").strip() not in {
        "0",
        "false",
        "False",
        "no",
        "NO",
    }

    import pybibx

    # Upstream binds 0.0.0.0; we still advertise localhost for the loading page.
    url = pybibx.web_app(port=port, open_browser=open_browser)
    _log(f"pybibx web app listening: {url} (preferred host {host})")
    return url


def main() -> int:
    _log(f"{APP_NAME} launch_app starting (python={sys.executable})")
    if not ensure_runtime_ready():
        _log("Runtime bootstrap failed.")
        return 2

    maybe_update_pybibx()

    try:
        start_web_app()
    except Exception as exc:
        _log(f"Failed to start pybibx web app: {exc}")
        return 1

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        try:
            import pybibx

            pybibx.web_stop()
        except Exception:
            pass
        _log("Stopped by KeyboardInterrupt.")
        return 0


if __name__ == "__main__":
    # Keep a reference so static analysers know threading may be used by pybibx.
    _ = threading
    raise SystemExit(main())
