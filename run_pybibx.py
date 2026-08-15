# run_pybibx.py
#
"""Launch the pybibx web app from the bundled portable Python runtime."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import traceback
import webbrowser
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

GITHUB_VERSION_URL = (
    "https://raw.githubusercontent.com/ecksteing/pybibx-desktop/main/version.txt"
)
RELEASES_URL = "https://github.com/ecksteing/pybibx-desktop/releases"
APP_NAME = "PyBibX Desktop"
APP_HOST = "127.0.0.1"
APP_PORT = 5173
LOADING_PORT = 5172
LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
LOG_BACKUP_COUNT = 2


def get_base_dir() -> Path:
    """Directory containing the launcher, whether running as .py or .exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_log_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Logs"
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    log_dir = root / APP_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def log_path() -> Path:
    return get_log_dir() / "launcher.log"


def rotate_logs_if_needed() -> None:
    path = log_path()
    try:
        if not path.is_file() or path.stat().st_size < LOG_MAX_BYTES:
            return
        oldest = path.with_name(f"launcher.log.{LOG_BACKUP_COUNT}")
        if oldest.exists():
            oldest.unlink()
        for i in range(LOG_BACKUP_COUNT - 1, 0, -1):
            src = path.with_name(f"launcher.log.{i}")
            dst = path.with_name(f"launcher.log.{i + 1}")
            if src.exists():
                src.replace(dst)
        path.replace(path.with_name("launcher.log.1"))
    except OSError:
        pass


def log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    try:
        rotate_logs_if_needed()
        with log_path().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def show_message(text: str, title: str = APP_NAME, error: bool = False) -> None:
    log(("ERROR: " if error else "INFO: ") + text.replace("\n", " | "))
    if sys.platform == "win32":
        try:
            import ctypes

            flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, text, title, flags)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def ask_yes_no(text: str, title: str = APP_NAME) -> bool:
    log(f"PROMPT: {text.replace(chr(10), ' | ')}")
    if sys.platform == "win32":
        try:
            import ctypes

            result = ctypes.windll.user32.MessageBoxW(0, text, title, 0x04 | 0x40)
            return result == 6
        except Exception:
            pass
    print(text, file=sys.stderr)
    return False


def get_local_version(base_dir: Path) -> str:
    version_file = base_dir / "version.txt"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def check_for_wrapper_updates(current_version: str) -> None:
    try:
        request = Request(
            GITHUB_VERSION_URL,
            headers={"User-Agent": f"{APP_NAME}/{current_version}"},
        )
        with urlopen(request, timeout=3) as response:
            latest = response.read().decode("utf-8", errors="replace").strip()
        if latest and latest != current_version:
            open_download = ask_yes_no(
                f"A new version ({latest}) is available.\n"
                f"You are running {current_version}.\n\n"
                f"Open the download page now?",
                title=f"{APP_NAME} update available",
            )
            if open_download:
                log(f"Opening releases page: {RELEASES_URL}")
                webbrowser.open(RELEASES_URL)
    except (URLError, HTTPError, TimeoutError, ValueError, OSError):
        log("Update check skipped (offline or unavailable).")


def app_url(port: int = APP_PORT) -> str:
    return f"http://{APP_HOST}:{port}"


def fetch_app_html(port: int = APP_PORT, timeout: float = 2.0) -> str | None:
    """Return response body text if the web app looks alive, else None."""
    try:
        request = Request(
            app_url(port),
            headers={"User-Agent": f"{APP_NAME}/health"},
        )
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if not (200 <= status < 500):
                return None
            raw = response.read(120_000)
        text = raw.decode("utf-8", errors="replace")
        # pybibx serves a large inline HTML shell at /
        lowered = text.lower()
        if len(text) < 500:
            return None
        if "pybibx" in lowered or "<html" in lowered:
            return text
        return None
    except Exception:
        return None


def app_http_reachable(port: int = APP_PORT) -> bool:
    return fetch_app_html(port) is not None


def open_app_in_browser(port: int = APP_PORT) -> None:
    webbrowser.open(app_url(port))


def open_loading_page(
    base_dir: Path,
    app_port: int = APP_PORT,
    mode: str = "start",
) -> ThreadingHTTPServer | None:
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))
    try:
        from loading_status import read_status, write_status
    except ImportError:
        read_status = None  # type: ignore[assignment]
        write_status = None  # type: ignore[assignment]

    loading_file = base_dir / "loading.html"
    if loading_file.is_file():
        html = loading_file.read_text(encoding="utf-8")
    else:
        html = (
            "<!DOCTYPE html><html><body>"
            "<p>Starting PyBibX…</p>"
            "<script>setTimeout(function(){location.replace('"
            f"{app_url(app_port)}"
            "');},3000);</script>"
            "</body></html>"
        )

    if write_status is not None:
        if mode == "bootstrap":
            write_status(
                "Preparing to download AI libraries",
                detail="One-time setup; this can take several minutes…",
                phase="bootstrap",
            )
        elif mode == "reopen":
            write_status("Reopening PyBibX", phase="ready", percent=100.0)
        else:
            write_status(
                "Loading Python libraries",
                detail="Subsequent launches can take a minute while AI packages warm up…",
                phase="start",
            )

    class LoadingHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/status", "/status.json"):
                if read_status is None:
                    payload = {
                        "phase": mode,
                        "message": "Starting…",
                        "detail": "",
                        "percent": None,
                    }
                else:
                    payload = read_status()
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return

            if path in ("/readyz", "/health"):
                healthy = fetch_app_html(app_port, timeout=1.2) is not None
                phase = "unknown"
                if read_status is not None:
                    try:
                        phase = str(read_status().get("phase") or "unknown")
                    except Exception:
                        phase = "unknown"
                if mode == "reopen":
                    ready = healthy
                else:
                    # Wait until launch_app marks the UI ready (after import + bind).
                    ready = healthy and phase == "ready"
                payload = {"ready": bool(ready), "healthy": bool(healthy), "phase": phase}
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return

            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    try:
        server = ThreadingHTTPServer((APP_HOST, LOADING_PORT), LoadingHandler)
    except OSError as exc:
        log(f"Loading port {LOADING_PORT} busy ({exc}); trying to free it.")
        kill_pids(pids_listening_on_port(LOADING_PORT))
        try:
            import time

            time.sleep(0.6)
            server = ThreadingHTTPServer((APP_HOST, LOADING_PORT), LoadingHandler)
        except OSError as exc2:
            log(f"Could not start loading page server on {LOADING_PORT}: {exc2}")
            return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = quote(app_url(app_port), safe=":/")
    loading_url = f"http://{APP_HOST}:{LOADING_PORT}/?target={target}&mode={quote(mode)}"
    log(f"Opening loading page: {loading_url}")
    webbrowser.open(loading_url)
    return server


def port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((APP_HOST, port)) == 0


def _creationflags_no_window() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def pids_listening_on_port(port: int) -> set[int]:
    if sys.platform != "win32":
        return set()
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            errors="replace",
            creationflags=_creationflags_no_window(),
        )
    except (OSError, subprocess.CalledProcessError):
        return set()

    suffix = f":{port}"
    pids: set[int] = set()
    for line in output.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        if not local_addr.endswith(suffix):
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return pids


def kill_pids(pids: set[int]) -> None:
    for pid in sorted(pids):
        if pid <= 0:
            continue
        log(f"Stopping process PID {pid} holding the PyBibX port.")
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    creationflags=_creationflags_no_window(),
                )
            else:
                os.kill(pid, 15)
        except OSError as exc:
            log(f"Could not stop PID {pid}: {exc}")


def prepare_app_port(port: int = APP_PORT) -> str:
    """
    Returns:
      - "running" if a healthy PyBibX UI is already serving
      - "free" if the port is available (or was freed)
    """
    if app_http_reachable(port):
        log(f"PyBibX already running and healthy at {app_url(port)}.")
        return "running"

    if port_is_listening(port):
        log(f"Port {port} is in use but PyBibX UI is not healthy; freeing it.")
        kill_pids(pids_listening_on_port(port))
        try:
            import time

            time.sleep(1.0)
        except Exception:
            pass
    return "free"


def find_python(base_dir: Path) -> Path | None:
    if sys.platform == "win32":
        candidates = [
            base_dir / "Python-Portable" / "python.exe",
            base_dir / "Python-Portable" / "pythonw.exe",
        ]
    else:
        candidates = [
            base_dir / "Python-Portable" / "bin" / "python3",
            base_dir / "Python-Portable" / "bin" / "python",
        ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def pybibx_installed(python_path: Path) -> bool:
    """Fast check: metadata only (avoids importing torch/pybibx)."""
    try:
        result = subprocess.run(
            [
                str(python_path),
                "-c",
                "from importlib.metadata import version; print(version('pybibx'))",
            ],
            capture_output=True,
            text=True,
            creationflags=_creationflags_no_window(),
            timeout=30,
        )
        return result.returncode == 0 and bool((result.stdout or "").strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def start_application(base_dir: Path, *, mode: str = "start") -> int:
    python_path = find_python(base_dir)
    launch_script = base_dir / "launch_app.py"

    if python_path is None:
        show_message(
            "Bundled Python was not found.\n\n"
            f"Expected under:\n{base_dir / 'Python-Portable'}\n\n"
            f"Details were written to:\n{log_path()}",
            error=True,
        )
        return 1

    if not launch_script.is_file():
        show_message(
            f"Missing launch script:\n{launch_script}\n\n"
            f"Details were written to:\n{log_path()}",
            error=True,
        )
        return 1

    env = os.environ.copy()
    env["PYBIBX_DESKTOP_HOST"] = APP_HOST
    env["PYBIBX_DESKTOP_PORT"] = str(APP_PORT)
    env["PYBIBX_DESKTOP_LAUNCH_BROWSER"] = "0"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    # Faster / quieter cold start for scientific stacks.
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    env.setdefault("TORCH_NUM_THREADS", "1")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    env.setdefault("TRANSFORMERS_VERBOSITY", "error")

    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    log(f"Starting: {python_path} {launch_script} (mode={mode})")
    try:
        rotate_logs_if_needed()
        with log_path().open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n----- Python session {datetime.now().isoformat(timespec='seconds')} -----\n"
            )
            result = subprocess.run(
                [str(python_path), str(launch_script)],
                cwd=str(base_dir),
                env=env,
                startupinfo=startupinfo,
                creationflags=creationflags,
                stdout=fh,
                stderr=subprocess.STDOUT,
                text=True,
            )
    except OSError as exc:
        show_message(
            f"Could not start Python:\n{exc}\n\nDetails were written to:\n{log_path()}",
            error=True,
        )
        return 1

    if result.returncode != 0:
        try:
            log_text = log_path().read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        session_marker = "----- Python session "
        latest = log_text.rsplit(session_marker, 1)[-1] if session_marker in log_text else log_text
        started = "pybibx web app listening" in latest or "Web App" in latest
        if started:
            log(
                f"Python exited with code {result.returncode} after the web app started; "
                "treating as a normal shutdown."
            )
            return 0

        show_message(
            "PyBibX failed to start.\n\n"
            f"Exit code: {result.returncode}\n"
            f"See the log for details:\n{log_path()}\n\n"
            "If this is the first run, check your internet connection "
            "(AI libraries download once during setup).",
            error=True,
        )
        return result.returncode

    log("Python session finished successfully.")
    return 0


def main() -> int:
    base_dir = get_base_dir()
    current_version = get_local_version(base_dir)
    log(f"Launcher start version={current_version} base_dir={base_dir}")
    check_for_wrapper_updates(current_version)

    port_state = prepare_app_port(APP_PORT)
    python_path = find_python(base_dir)

    # Open the loading UI immediately (before any slow work).
    if port_state == "running":
        loading_server = open_loading_page(base_dir, APP_PORT, mode="reopen")
        # Keep serving the loading page long enough for the redirect.
        try:
            import time

            time.sleep(4.0)
        except Exception:
            pass
        if loading_server is not None:
            try:
                loading_server.shutdown()
            except Exception:
                pass
        return 0

    needs_bootstrap = True
    if python_path is not None:
        needs_bootstrap = not pybibx_installed(python_path)
    mode = "bootstrap" if needs_bootstrap else "start"
    if needs_bootstrap:
        log("pybibx missing; first-run / post-install bootstrap will run inside launch_app.py")

    loading_server = open_loading_page(base_dir, APP_PORT, mode=mode)
    try:
        return start_application(base_dir, mode=mode)
    finally:
        if loading_server is not None:
            try:
                loading_server.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        details = traceback.format_exc()
        try:
            log(details)
        except Exception:
            pass
        show_message(
            "An unexpected launcher error occurred.\n\n"
            f"See the log for details:\n{log_path()}",
            error=True,
        )
        sys.exit(1)
