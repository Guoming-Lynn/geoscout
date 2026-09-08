from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app import __version__
from app.paths import default_data_dir, frozen, web_dir


def launcher_defaults(data_dir: Path) -> dict[str, str]:
    return {
        "GEOSCOUT_DATA_DIR": str(data_dir),
        "GEOSCOUT_HOST": "127.0.0.1",
        "GEOSCOUT_EMBED_WORKER": "true",
        "GEOSCOUT_SERVE_WEB": "true",
        "GEOSCOUT_OPEN_BROWSER": "true",
        "GEOSCOUT_NCBI_MODE": "live",
        "GEOSCOUT_LLM_MODE": "live",
        "GEOSCOUT_API_URL": "http://127.0.0.1:8000",
    }


def prepare_environment() -> None:
    for key, value in launcher_defaults(default_data_dir()).items():
        os.environ.setdefault(key, value)


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def _open_when_ready(url: str, health: str) -> None:
    for _ in range(50):
        try:
            urllib.request.urlopen(health, timeout=1)
            webbrowser.open(url)
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.2)


def main() -> int:
    multiprocessing.freeze_support()
    prepare_environment()
    from app.core.config import settings
    from app.main import app
    import uvicorn

    host = settings.host or "127.0.0.1"
    port = int(settings.port)
    ui = f"http://{host}:{port}/"
    health = f"http://{host}:{port}/api/health"
    if host not in {"127.0.0.1", "localhost"}:
        print("GEOScout only binds to 127.0.0.1 by default. Refusing to start.", flush=True)
        return 2
    if _port_open(host, port):
        print(f"Port {port} is already in use on {host}.", flush=True)
        print("Close the other GEOScout window (or the old API/Vite processes), then try again.", flush=True)
        return 1
    if settings.serve_web and web_dir() is None:
        print("UI files were not found (frontend/dist or bundled web/).", flush=True)
        print("From the repo, run:  cd frontend && npm run build", flush=True)
        return 1
    print(f"GEOScout {__version__}", flush=True)
    print(f"Open {ui}  (keep this window open; closing it stops GEOScout)", flush=True)
    print(f"Data dir: {settings.data_dir}", flush=True)
    if frozen():
        print("Packaged app. Keys stay in memory for this process only.", flush=True)
    if settings.open_browser:
        threading.Thread(target=_open_when_ready, args=(ui, health), daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info", reload=False)
    return 0


def _pause_if_needed(code: int) -> None:
    if code == 0 or not sys.stdin.isatty():
        return
    try:
        input("Press Enter to close...")
    except EOFError:
        pass


def run() -> int:
    code = main()
    _pause_if_needed(code)
    return code


if __name__ == "__main__":
    raise SystemExit(run())
