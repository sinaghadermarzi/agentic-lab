#!/usr/bin/env python3
"""Execute course notebooks serially and log one JSON report line per notebook.

Usage:
  python scripts/execute_notebooks.py NOTEBOOK [NOTEBOOK ...]
  python scripts/execute_notebooks.py --all [--stop-on-failure] [--keep-outputs]

--all runs the numbered chapters in order, then the appendices. Execution is
serial only (the notebooks share one OpenRouter budget and one Phoenix server).

Each notebook runs in a fresh python3 kernel with the repo root as its working
directory (timeout 300 s per cell). Wall time is measured directly; cost is
measured as the delta of OpenRouter credits (GET /api/v1/key, field
data.usage) around the run and is null when the endpoint or the key is
unavailable. A cell error is recorded with a short traceback and the build
moves on to the next notebook unless --stop-on-failure.

By default the .ipynb on disk is left untouched -- this is a build check, not
an output writer; pass --keep-outputs to write the executed notebook back.
One JSON line per notebook is appended to artifacts/exec-report.jsonl:
{notebook, status, seconds, cost_usd, error, sha256_nb, sha256_pkg,
executed_at}.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx
import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
REPORT = ARTIFACTS / "exec-report.jsonl"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
CELL_TIMEOUT_S = 300
ERROR_MAX_LINES = 12
ERROR_MAX_CHARS = 1500


def openrouter_usage() -> float | None:
    """Total credits used on the key (data.usage), or None if unavailable."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        resp = httpx.get(OPENROUTER_KEY_URL,
                         headers={"Authorization": f"Bearer {key}"}, timeout=15)
        resp.raise_for_status()
        usage = resp.json()["data"]["usage"]
        return float(usage) if usage is not None else None
    except Exception:
        return None


def sha256_pkg() -> str:
    """Hash of the sorted src/shoplab/*.py contents (name + bytes per file)."""
    h = hashlib.sha256()
    for py in sorted((ROOT / "src" / "shoplab").glob("*.py")):
        h.update(py.name.encode("utf-8"))
        h.update(b"\x00")
        h.update(py.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()


def short_error(exc: Exception) -> str:
    lines = f"{type(exc).__name__}: {exc}".strip().splitlines()
    text = "\n".join(lines[-ERROR_MAX_LINES:])
    if len(text) > ERROR_MAX_CHARS:
        text = "..." + text[-ERROR_MAX_CHARS:]
    return text


def discover_all() -> list[Path]:
    chapters = sorted(ROOT.glob("[0-9][0-9]-*.ipynb"))
    appendices = sorted((ROOT / "appendices").glob("A-*.ipynb"))
    return chapters + appendices


def run_one(path: Path, keep_outputs: bool) -> dict:
    rel = str(path.resolve().relative_to(ROOT)) if path.resolve().is_relative_to(ROOT) else str(path)
    raw = path.read_bytes()
    nb = nbformat.reads(raw.decode("utf-8"), as_version=4)

    usage_before = openrouter_usage()
    start = time.time()
    status, error = "ok", None
    try:
        client = NotebookClient(nb, timeout=CELL_TIMEOUT_S,
                                kernel_name="python3",
                                resources={"metadata": {"path": str(ROOT)}})
        client.execute()
    except Exception as e:
        status, error = "error", short_error(e)
    seconds = round(time.time() - start, 2)
    usage_after = openrouter_usage()
    cost = (round(usage_after - usage_before, 6)
            if usage_before is not None and usage_after is not None else None)

    if keep_outputs:
        nbformat.write(nb, path)

    return {
        "notebook": rel,
        "status": status,
        "seconds": seconds,
        "cost_usd": cost,
        "error": error,
        "sha256_nb": hashlib.sha256(raw).hexdigest(),
        "sha256_pkg": sha256_pkg(),
        "executed_at": time.time(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute course notebooks serially and append a JSON "
                    "report line per notebook to artifacts/exec-report.jsonl.")
    parser.add_argument("notebooks", nargs="*", metavar="NOTEBOOK",
                        help="notebook paths to execute (in the given order)")
    parser.add_argument("--all", action="store_true",
                        help="execute all numbered chapters (sorted), then "
                             "the appendices")
    parser.add_argument("--stop-on-failure", action="store_true",
                        help="stop at the first notebook whose execution errors")
    parser.add_argument("--keep-outputs", action="store_true",
                        help="write the executed notebook (with outputs) back "
                             "to disk; default leaves files untouched")
    args = parser.parse_args()

    if args.all and args.notebooks:
        parser.error("pass either --all or explicit notebook paths, not both")
    if not args.all and not args.notebooks:
        parser.print_usage(sys.stderr)
        print("error: nothing to execute -- pass notebook paths or --all",
              file=sys.stderr)
        sys.exit(2)

    if args.all:
        paths = discover_all()
        if not paths:
            print("no notebooks found (repo-root NN-*.ipynb or "
                  "appendices/A-*.ipynb); nothing to execute")
            return
    else:
        paths = [Path(p) for p in args.notebooks]
        missing = [p for p in paths if not p.exists()]
        if missing:
            for p in missing:
                print(f"error: notebook not found: {p}", file=sys.stderr)
            sys.exit(2)

    ARTIFACTS.mkdir(exist_ok=True)
    any_error = False
    for path in paths:
        print(f"executing {path} ...", flush=True)
        record = run_one(path, keep_outputs=args.keep_outputs)
        with open(REPORT, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        cost = record["cost_usd"]
        cost_str = f"${cost:.4f}" if cost is not None else "cost n/a"
        print(f"  {record['status']} in {record['seconds']}s ({cost_str})")
        if record["status"] == "error":
            any_error = True
            first_line = record["error"].splitlines()[0] if record["error"] else ""
            print(f"  error: {first_line}")
            if args.stop_on_failure:
                print("stopping (--stop-on-failure)")
                break

    print(f"report: {REPORT.relative_to(ROOT)}")
    sys.exit(1 if any_error else 0)


if __name__ == "__main__":
    main()
