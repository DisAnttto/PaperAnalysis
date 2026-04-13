"""Start uvicorn for local development.

If port 8000 is already taken (common after an orphaned ``--reload`` parent),
this picks the next candidate so the server always starts.

Usage (from repo root ``medlit-ranking-tool/``)::

    py -3 scripts/dev_server.py

Or set ``MEDLIT_PORT=8001`` to prefer a specific port first.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pick_port() -> int | None:
    env = os.environ.get("MEDLIT_PORT", "").strip()
    candidates: list[int] = [8000, 8001, 8010, 8765]
    if env.isdigit():
        p = int(env)
        candidates = [p] + [x for x in candidates if x != p]
    for port in candidates:
        if _port_free(port):
            return port
    return None


def main() -> None:
    os.chdir(ROOT)
    port = _pick_port()
    if port is None:
        print(
            "No free port among 8000, 8001, 8010, 8765. "
            "Free one (e.g. stop other uvicorn) or set MEDLIT_PORT.",
            file=sys.stderr,
        )
        sys.exit(1)
    if port != 8000:
        print(
            f"Port 8000 is in use — starting on http://127.0.0.1:{port}/ "
            f"(stop the other process to use 8000).",
            flush=True,
        )
    else:
        print(f"http://127.0.0.1:{port}/", flush=True)
    # --reload is intentionally omitted: on Windows + Python 3.14 the
    # multiprocessing reloader stalls all HTTP requests.  Restart the script
    # manually after code changes, or use a different OS/version for hot reload.
    raise SystemExit(
        subprocess.run(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(ROOT),
        ).returncode
    )


if __name__ == "__main__":
    main()
