"""Optional observability helpers for the agentic-lab notebooks (taught in notebook 03).

Usage, from any notebook:

    import obs
    obs.enable_phoenix()    # find-or-start Phoenix and route LiteLLM traces to it

Design notes (the robustness contract):
- Sessions are dated: everything logs under the Phoenix project
  `agentic-lab-YYYY-MM-DD`, so work from different days never collides in the UI.
- Servers are reused when they are genuinely ours (health-checked), skipped when a
  stranger holds the port (the next port is tried), and started otherwise. Started
  servers are plain background processes: they survive kernel restarts, and
  rerunning a cell just finds them again.
"""

import datetime
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

TODAY = datetime.date.today().isoformat()
EXPERIMENT = f"agentic-lab-{TODAY}"
REPO = Path(__file__).resolve().parent


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _http_get(url: str, timeout: float = 3.0) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read(65536) if response.status == 200 else None
    except Exception:
        return None


def _find_or_start(name, start_on_port, is_ours, first_port, tries=4, wait_s=90):
    """Reuse a server that passes `is_ours`; skip ports held by strangers; else start one."""
    for port in range(first_port, first_port + tries):
        if _port_open(port):
            if is_ours(port):
                print(f"obs: {name} already running — http://127.0.0.1:{port}")
                return port
            continue                                    # someone else's server; try next port
        start_on_port(port)
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if _port_open(port) and is_ours(port):
                print(f"obs: {name} — http://127.0.0.1:{port}")
                return port
            time.sleep(0.5)
        print(f"obs: {name} did not come up on port {port}; trying {port + 1}")
    print(f"obs: could not find or start {name} on ports "
          f"{first_port}-{first_port + tries - 1}")
    return None


def _spawn(cmd, env=None):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env=env, cwd=REPO)


def enable_phoenix(port: int = 6006):
    """Find or start Phoenix, then route LiteLLM traces to it under the dated project."""

    import importlib.util
    if importlib.util.find_spec("phoenix") is None:     # isolated framework venvs omit it
        print("obs: phoenix not installed in this environment — tracing skipped "
              "(this notebook runs in an isolated venv; see the install box)")
        return None

    def is_ours(p):                                     # any healthy Phoenix will do:
        body = _http_get(f"http://127.0.0.1:{p}")       # instances share ~/.phoenix data
        return body is not None and b"phoenix" in body.lower()

    def start(p):
        _spawn([sys.executable, "-m", "phoenix.server.main", "serve"],
               env={**os.environ, "PHOENIX_PORT": str(p)})

    chosen = _find_or_start("Phoenix", start, is_ours, port)
    if chosen is not None:
        import warnings

        with warnings.catch_warnings():     # tqdm's "IProgress not found" hint
            warnings.filterwarnings("ignore", message="IProgress not found")
            from phoenix.otel import register

        # verbose=False: register's banner is noise here (and uses emoji).
        register(project_name=EXPERIMENT, auto_instrument=True, verbose=False,
                 endpoint=f"http://127.0.0.1:{chosen}/v1/traces")
        print(f"obs: Phoenix tracing on — project {EXPERIMENT!r}")
    return chosen
