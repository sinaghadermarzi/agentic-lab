#!/usr/bin/env python3
"""Pre-build gate for the course: static checks, and an optional live probe.

Usage:
  python scripts/preflight.py            # same as --static
  python scripts/preflight.py --static   # pytest, check_data, validators
  python scripts/preflight.py --live     # one tiny LM call + one HTTPS GET

--static runs, from the repo root and with this same interpreter:
  pytest -q, scripts/check_data.py, scripts/validate_notebooks.py,
  scripts/api_audit.py
and prints a PASS/FAIL table (exit 1 if anything fails). A pytest run that
collects zero tests counts as PASS -- the suite may not exist yet.

--live confirms the environment can actually reach the outside world before an
expensive build: one litellm.completion (MODEL env var or the course default,
temperature=0, max_tokens=8) printing the reply and its cost, and one httpx
GET of https://modelcontextprotocol.io/ (certifi verification, env proxies
respected) printing the status code. Exit 1 if either fails.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PYTEST_EXIT_NO_TESTS = 5
TAIL_LINES = 15


def run_static() -> None:
    steps = [
        ("pytest -q", [sys.executable, "-m", "pytest", "-q"], None),
        ("scripts/check_data.py",
         [sys.executable, "scripts/check_data.py"], ROOT / "scripts/check_data.py"),
        ("scripts/validate_notebooks.py",
         [sys.executable, "scripts/validate_notebooks.py"],
         ROOT / "scripts/validate_notebooks.py"),
        ("scripts/api_audit.py",
         [sys.executable, "scripts/api_audit.py"], ROOT / "scripts/api_audit.py"),
    ]

    rows: list[tuple[str, str, str]] = []   # (step, PASS/FAIL, note)
    tails: list[tuple[str, str]] = []       # (step, output tail) for failures
    for label, cmd, required_file in steps:
        if required_file is not None and not required_file.exists():
            rows.append((label, "FAIL", "file missing"))
            continue
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if proc.returncode == 0:
            rows.append((label, "PASS", ""))
        elif label == "pytest -q" and proc.returncode == PYTEST_EXIT_NO_TESTS:
            rows.append((label, "PASS", "no tests collected"))
        else:
            rows.append((label, "FAIL", f"exit {proc.returncode}"))
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-TAIL_LINES:]
            tails.append((label, "\n".join(tail)))

    width = max(len(label) for label, _, _ in rows)
    print(f"{'step'.ljust(width)}  result")
    print(f"{'-' * width}  ------")
    for label, result, note in rows:
        suffix = f"  ({note})" if note else ""
        print(f"{label.ljust(width)}  {result}{suffix}")

    for label, tail in tails:
        print(f"\n--- {label} output (tail) ---")
        print(tail)

    if any(result == "FAIL" for _, result, _ in rows):
        sys.exit(1)
    print("\npreflight --static: all checks passed")


def run_live() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    ok = True

    try:
        import litellm
        model = os.environ.get("MODEL", "openrouter/deepseek/deepseek-v3.2")
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": "Reply with one word: ready"}],
            temperature=0, max_tokens=8)
        reply = resp.choices[0].message.content
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = None
        cost_str = f"${cost:.6f}" if cost is not None else "n/a"
        print(f"LM call    PASS  model={model} reply={reply!r} cost={cost_str}")
    except Exception as e:
        ok = False
        print(f"LM call    FAIL  {type(e).__name__}: {e}")

    try:
        import httpx
        resp = httpx.get("https://modelcontextprotocol.io/",
                         follow_redirects=True, timeout=20)
        status = resp.status_code
        verdict = "PASS" if status < 400 else "FAIL"
        if status >= 400:
            ok = False
        print(f"HTTPS GET  {verdict}  https://modelcontextprotocol.io/ -> {status}")
    except Exception as e:
        ok = False
        print(f"HTTPS GET  FAIL  {type(e).__name__}: {e}")

    if not ok:
        sys.exit(1)
    print("\npreflight --live: all checks passed")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-build gate: --static runs the test/validation suite, "
                    "--live makes one tiny LM call and one HTTPS GET. "
                    "Default is --static.")
    parser.add_argument("--static", action="store_true",
                        help="run pytest, check_data, validate_notebooks, "
                             "api_audit (default)")
    parser.add_argument("--live", action="store_true",
                        help="run the live connectivity probes")
    args = parser.parse_args()

    if not args.static and not args.live:
        args.static = True
    if args.static:
        run_static()
    if args.live:
        run_live()


if __name__ == "__main__":
    main()
