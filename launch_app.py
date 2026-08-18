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

import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent


def _load_loading_status():
    """Load sibling loading_status.py by path (embeddable Python ignores app dir on sys.path)."""
    module_path = _APP_DIR / "loading_status.py"
    if not module_path.is_file():
        raise FileNotFoundError(f"Missing {module_path}")
    spec = importlib.util.spec_from_file_location("loading_status", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_loading_status = _load_loading_status()
_app_data_dir = _loading_status.app_data_dir
write_status = _loading_status.write_status

# Avoid Windows cp1252 crashes when upstream prints Unicode banners.
for _stream in (sys.stdout, sys.stderr):
    try:
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_NAME = "PyBibX Desktop"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5173
UPDATE_CHECK_INTERVAL_DAYS = 7

_PIP_COLLECTING = re.compile(r"^\s*Collecting\s+(\S+)", re.IGNORECASE)
_PIP_DOWNLOADING = re.compile(r"^\s*Downloading\s+(\S+)", re.IGNORECASE)
_PIP_USING_CACHED = re.compile(r"^\s*Using cached\s+(\S+)", re.IGNORECASE)
_PIP_INSTALLING = re.compile(
    r"^\s*Installing collected packages:\s*(.+)$", re.IGNORECASE
)
_PIP_PROGRESS = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)\s*%.*?/\s*\S+\s+(?P<file>\S+\.(?:whl|tar\.gz))",
    re.IGNORECASE,
)
_PIP_PROGRESS_ALT = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\|[^|]*\|\s*(?P<done>\S+)\s*/\s*(?P<total>\S+)(?:\s+(?P<file>\S+))?",
    re.IGNORECASE,
)


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


def _status(message: str, detail: str = "", *, phase: str = "start", percent: float | None = None) -> None:
    write_status(message, detail=detail, phase=phase, percent=percent)


def _parse_pip_line(line: str) -> tuple[str, str, float | None] | None:
    """Return (message, detail, percent) if the pip line is worth showing."""
    text = line.strip().strip("\r")
    if not text:
        return None

    # Carriage-return progress updates from pip's progress bar.
    if "\r" in line:
        text = line.split("\r")[-1].strip()

    m = _PIP_PROGRESS.search(text) or _PIP_PROGRESS_ALT.search(text)
    if m:
        try:
            pct = float(m.group("pct"))
        except (ValueError, IndexError):
            pct = None
        detail = m.groupdict().get("file") or ""
        if not detail and m.groupdict().get("done") and m.groupdict().get("total"):
            detail = f"{m.group('done')} / {m.group('total')}"
        return ("Downloading", detail, pct)

    m = _PIP_DOWNLOADING.match(text)
    if m:
        return ("Downloading package", m.group(1), None)

    m = _PIP_USING_CACHED.match(text)
    if m:
        return ("Using cached package", m.group(1), None)

    m = _PIP_COLLECTING.match(text)
    if m:
        return ("Collecting package", m.group(1), None)

    m = _PIP_INSTALLING.match(text)
    if m:
        packages = m.group(1).strip()
        short = packages if len(packages) <= 80 else packages[:77] + "..."
        return ("Installing packages", short, None)

    if text.lower().startswith("successfully installed"):
        return ("Packages installed", text[len("Successfully installed") :].strip(), 100.0)

    return None


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


def _update_lock_path() -> Path:
    return _app_data_dir() / "pypi_update.lock"


def _acquire_update_lock() -> bool:
    path = _update_lock_path()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return True
    except FileExistsError:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = 0.0
        if age > 600:
            try:
                path.unlink()
            except OSError:
                return False
            return _acquire_update_lock()
        return False
    except OSError:
        return False


def _release_update_lock() -> None:
    try:
        _update_lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def _pip_install(args: list[str], *, phase: str = "bootstrap", label: str = "Installing packages") -> int:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--prefer-binary", *args]
    _log("Running: " + " ".join(cmd))
    detail = " ".join(a for a in args if not a.startswith("-"))[:80]
    _status(label, detail, phase=phase)

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_PROGRESS_BAR"] = "on"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
    except OSError as exc:
        _log(f"Could not start pip: {exc}")
        return 1

    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.strip():
            print(line, flush=True)
        parsed = _parse_pip_line(raw)
        if parsed:
            message, detail, percent = parsed
            _status(message, detail, phase=phase, percent=percent)

    return int(proc.wait())


# Enough for `import pybibx` + Flask web UI (AI/torch are deferred).
# Keep in sync with scripts/critical_packages.txt (baked at build time).
_CRITICAL_PACKAGES = [
    "flask",
    "werkzeug",
    "plotly",
    "pandas",
    "numpy",
    "matplotlib",
    "scipy",
    "scikit-learn",
    "networkx",
    "Pillow",
    "chardet",
    "numba",
    "wordcloud",
    "gensim",
]

# PyPI name -> import name (when they differ).
_CRITICAL_IMPORT_NAMES: dict[str, str] = {
    "Pillow": "PIL",
    "scikit-learn": "sklearn",
}


def _missing_critical_packages() -> list[str]:
    missing: list[str] = []
    for pkg in _CRITICAL_PACKAGES:
        mod = _CRITICAL_IMPORT_NAMES.get(pkg, pkg.replace("-", "_"))
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    return missing


def _install_missing_critical_packages() -> bool:
    missing = _missing_critical_packages()
    if not missing:
        return True
    _log(f"Installing missing critical packages: {', '.join(missing)}")
    code = _pip_install(
        missing,
        phase="bootstrap",
        label="Installing missing libraries",
    )
    if code != 0:
        _log(f"Missing critical package install failed with exit code {code}")
        return False
    still_missing = _missing_critical_packages()
    if still_missing:
        _log(f"Still missing after install: {', '.join(still_missing)}")
        return False
    return True

_AI_PACKAGES = [
    "bertopic",
    "bert-extractive-summarizer",
    "sentence-transformers",
    "transformers",
    "sentencepiece",
    "umap-learn",
    "keybert",
    "openai",
    "google-generativeai",
    "llmx",
]


def _portable_marker(name: str) -> Path:
    return Path(sys.executable).resolve().parent / name


def _can_start_web_ui() -> bool:
    """True when the Flask web app can be imported (critical deps present)."""
    try:
        import pybibx  # noqa: F401
        from pybibx.base import app as _app  # noqa: F401

        return True
    except Exception as exc:
        _log(f"Web UI not ready yet: {exc}")
        return False


def _ai_stack_ready() -> bool:
    try:
        import bertopic  # noqa: F401
        import sentence_transformers  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401

        return True
    except Exception:
        return False


def _mark_file(name: str) -> None:
    try:
        _portable_marker(name).write_text(
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            encoding="ascii",
        )
    except OSError as exc:
        _log(f"Could not write {name}: {exc}")


def ensure_runtime_ready() -> bool:
    """
    Install only what is needed to open the pybibx web UI.
    Heavy AI wheels (PyTorch / transformers / BERTopic) install later in the background.
    """
    if _can_start_web_ui():
        _status("Checking installed packages", phase="start")
        if not _install_missing_critical_packages():
            _status("Package install incomplete", "Some core libraries are still missing", phase="error")
            return False
        _mark_file("runtime_ui_ready.txt")
        return True

    _log("Installing critical packages for the web UI (AI stack deferred)...")
    _status(
        "Installing core libraries",
        "Flask, pandas, plotly, and friends — AI packages load after the app opens…",
        phase="bootstrap",
    )

    code = _pip_install(
        ["pybibx", "--no-deps"],
        phase="bootstrap",
        label="Installing pybibx package",
    )
    if code != 0:
        _log(f"pip install pybibx --no-deps failed with exit code {code}")
        _status("Package install failed", f"Exit code {code}", phase="error")
        return False

    code = _pip_install(
        list(_CRITICAL_PACKAGES),
        phase="bootstrap",
        label="Installing critical libraries",
    )
    if code != 0:
        _log(f"Critical package install failed with exit code {code}")
        _status("Package install failed", f"Exit code {code}", phase="error")
        return False

    if not _can_start_web_ui():
        _log("Critical packages installed but web UI still will not import.")
        _status("Package install incomplete", "Web UI import still failing", phase="error")
        return False

    _mark_file("runtime_ui_ready.txt")
    _status("Core ready — starting app", phase="start", percent=100.0)
    return True


def install_ai_stack_background() -> None:
    """Finish Torch + NLP/AI dependencies after the GUI is already up."""
    if _ai_stack_ready():
        _log("AI stack already present.")
        _mark_file("runtime_ai_ready.txt")
        _mark_file("runtime_ready.txt")
        return

    _log("Background AI install starting…")
    _status(
        "Installing AI libraries in background",
        "You can use the app; topic modelling / LLM tools need these…",
        phase="bootstrap",
    )

    code = _pip_install(
        [
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            "https://download.pytorch.org/whl/cpu",
        ],
        phase="bootstrap",
        label="Downloading PyTorch (CPU)",
    )
    if code != 0:
        _log(f"CPU torch install exited with {code}; trying default PyPI torch.")

    code = _pip_install(
        list(_AI_PACKAGES),
        phase="bootstrap",
        label="Installing AI / NLP libraries",
    )
    if code != 0:
        _log(f"AI package install exited with {code}; trying full pybibx resolve.")
        _pip_install(["pybibx"], phase="bootstrap", label="Completing pybibx dependencies")

    if _ai_stack_ready() or _installed_pybibx_version():
        _mark_file("runtime_ai_ready.txt")
        _mark_file("runtime_ready.txt")
        _log("Background AI install finished.")
        try:
            import compileall
            from pathlib import Path as _Path

            site = _Path(sys.executable).resolve().parent / "Lib" / "site-packages"
            if site.is_dir():
                compileall.compile_dir(str(site), quiet=1, workers=0)
        except Exception as exc:
            _log(f"compileall skipped: {exc}")
    else:
        _log("Background AI install finished with missing imports; will retry next launch.")


def check_pybibx_updates(*, force: bool = False) -> dict:
    """Check PyPI for a newer pybibx and install it when online."""
    enable = os.environ.get("PYBIBX_DESKTOP_RUNTIME_UPDATES", "1").strip() not in {
        "0",
        "false",
        "False",
        "no",
        "NO",
    }
    current = _installed_pybibx_version()
    if not enable:
        _log("Runtime updates disabled by environment.")
        return {
            "ok": True,
            "status": "disabled",
            "message": "Automatic updates are disabled.",
            "current": current,
            "latest": None,
        }

    if not force and not _should_run_update_check():
        _log("Skipping PyPI update check (checked within the last week).")
        return {
            "ok": True,
            "status": "skipped",
            "message": "Already checked within the last week.",
            "current": current,
            "latest": None,
        }

    if not _acquire_update_lock():
        return {
            "ok": False,
            "status": "busy",
            "message": "An update check is already running.",
            "current": current,
            "latest": None,
        }

    try:
        _status("Checking for pybibx updates", phase="update")
        latest = _pypi_pybibx_version(timeout=8.0 if force else 3.0)
        if latest is None:
            _log("PyPI unreachable or pybibx metadata missing; keeping installed copy.")
            _record_update_check()
            msg = "Could not reach PyPI. Your installed copy will be used."
            _status(msg, current or "", phase="update")
            return {
                "ok": True,
                "status": "offline",
                "message": msg,
                "current": current,
                "latest": None,
            }

        if current and _parse_version(latest) <= _parse_version(current):
            _log(f"pybibx is up to date ({current}).")
            _record_update_check()
            msg = f"pybibx is up to date ({current})."
            _status(msg, "", phase="update")
            return {
                "ok": True,
                "status": "up_to_date",
                "message": msg,
                "current": current,
                "latest": latest,
            }

        _log(f"Updating pybibx: {current or 'none'} -> {latest}")
        code = _pip_install(
            [f"pybibx=={latest}"],
            phase="update",
            label=f"Updating pybibx to {latest}",
        )
        if code == 0:
            current = _installed_pybibx_version() or latest
            _log(f"pybibx updated to {current}")
            msg = f"Updated pybibx to {current}."
            _status(msg, "", phase="update")
            return {
                "ok": True,
                "status": "updated",
                "message": msg,
                "current": current,
                "latest": latest,
            }

        _log(f"pybibx update failed with exit code {code}; continuing with {current}")
        msg = f"Update failed; continuing with pybibx {current or 'already installed'}."
        _status(msg, f"Exit code {code}", phase="update")
        return {
            "ok": False,
            "status": "failed",
            "message": msg,
            "current": current,
            "latest": latest,
        }
    finally:
        _record_update_check()
        _release_update_lock()


def maybe_update_pybibx() -> None:
    check_pybibx_updates(force=False)


def run_update_check_cli() -> int:
    result = check_pybibx_updates(force=True)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1


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

    _status(
        "Starting PyBibX",
        "Loading the web interface…",
        phase="start",
    )
    import pybibx

    _status("Starting web server", phase="start")
    # Upstream binds 0.0.0.0; we still advertise localhost for the loading page.
    url = pybibx.web_app(port=port, open_browser=open_browser)
    _log(f"pybibx web app listening: {url} (preferred host {host})")
    _status("Ready — opening PyBibX", url, phase="ready", percent=100.0)
    return url


def main() -> int:
    _log(f"{APP_NAME} launch_app starting (python={sys.executable})")
    _status("Starting PyBibX Desktop", phase="start")
    if not ensure_runtime_ready():
        _log("Runtime bootstrap failed.")
        return 2

    # Loading page is already visible in the browser; safe to do a quick weekly check.
    maybe_update_pybibx()

    try:
        start_web_app()
    except Exception as exc:
        _log(f"Failed to start pybibx web app: {exc}")
        _status("Failed to start web app", str(exc), phase="error")
        return 1

    # Heavy AI wheels continue after the UI is up.
    try:
        threading.Thread(
            target=install_ai_stack_background,
            name="pybibx-ai-install",
            daemon=True,
        ).start()
    except Exception as exc:
        _log(f"Could not start background AI installer: {exc}")

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
    _ = threading
    if "--check-updates" in sys.argv:
        raise SystemExit(run_update_check_cli())
    raise SystemExit(main())
