#!/usr/bin/env python3
"""Audit every framework API name the course touches against what is installed.

Run from anywhere:  python scripts/api_audit.py

Regex-extracts dotted names rooted at the course's libraries (litellm, mcp,
a2a, langgraph, langchain, smolagents, deepagents, phoenix, openinference,
obs, shoplab) from all notebook code cells and from src/shoplab/*.py, then
resolves each name via importlib + getattr. A name that cannot be resolved is
a failure (the notebook teaches an API that does not exist in the pinned
stack); a name whose root package or a third-party dependency is not installed
is reported as "SKIP (extra not installed)" -- the base install does not carry
every extra.

A handful of signature spot-checks then guard the call shapes the course
relies on (litellm.completion, phoenix.otel.register, FastMCP.tool,
shoplab.rules.decide, shoplab.world.search_policy, obs.enable_phoenix).
"""

import importlib
import inspect
import re
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))           # obs.py lives at the repo root
sys.path.insert(0, str(ROOT / "src"))   # shoplab is not pip-installed yet

ROOTS = ("litellm", "mcp", "a2a", "langgraph", "langchain", "smolagents",
         "deepagents", "phoenix", "openinference", "obs", "shoplab")
ROOT_ALT = "|".join(ROOTS)
DOTTED_RE = re.compile(rf"\b(?:{ROOT_ALT})(?:\.[A-Za-z_]\w*)+")
FROM_IMPORT_RE = re.compile(
    rf"^\s*from\s+((?:{ROOT_ALT})(?:\.[A-Za-z_]\w*)*)\s+import\s+(.+)$")
BARE_IMPORT_RE = re.compile(
    rf"^\s*import\s+((?:{ROOT_ALT})(?:\.[A-Za-z_]\w*)*)\s*(?:as\s+\w+)?\s*$")
IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


# --- name extraction -------------------------------------------------------

def collect_names(text: str, origin: str, names: dict[str, set[str]]) -> None:
    for line in text.splitlines():
        if line.lstrip().startswith("#"):       # skip comments (sentinels etc.)
            continue
        m = FROM_IMPORT_RE.match(line)
        if m:
            base, imported = m.group(1), m.group(2)
            names.setdefault(base, set()).add(origin)
            imported = imported.split("#")[0].replace("(", "").replace(")", "")
            for item in imported.split(","):
                item = item.strip().split(" as ")[0].strip()
                if item and item != "*" and IDENT_RE.match(item):
                    names.setdefault(f"{base}.{item}", set()).add(origin)
            continue
        m = BARE_IMPORT_RE.match(line)
        if m:
            names.setdefault(m.group(1), set()).add(origin)
        for m in DOTTED_RE.finditer(line):
            names.setdefault(m.group(0), set()).add(origin)


def gather_sources() -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    notebooks = sorted(ROOT.glob("[0-9][0-9]-*.ipynb"))
    notebooks += sorted((ROOT / "appendices").glob("A-*.ipynb"))
    for path in notebooks:
        label = str(path.relative_to(ROOT))
        try:
            nb = nbformat.read(path, as_version=4)
        except Exception as e:
            fail(f"{label}: cannot read notebook: {e}")
            continue
        for cell in nb.cells:
            if cell.cell_type == "code":
                collect_names(cell.source, label, names)
    for py in sorted((ROOT / "src" / "shoplab").glob("*.py")):
        collect_names(py.read_text(encoding="utf-8"),
                      f"src/shoplab/{py.name}", names)
    return names


# --- resolution ------------------------------------------------------------

def resolve(name: str) -> tuple[str, str]:
    """Resolve a dotted name -> (status, detail); status in OK | SKIP | FAIL."""
    parts = name.split(".")
    try:
        obj = importlib.import_module(parts[0])
    except ModuleNotFoundError:
        return "SKIP", "extra not installed"
    except Exception as e:
        return "FAIL", f"importing {parts[0]!r} raised {type(e).__name__}: {e}"
    prefix = parts[0]
    for part in parts[1:]:
        prefix = f"{prefix}.{part}"
        try:
            obj = getattr(obj, part)
            continue
        except AttributeError:
            pass
        try:                                    # maybe it is a submodule
            obj = importlib.import_module(prefix)
        except ModuleNotFoundError as e:
            # e.name inside our own dotted path -> the name is bogus;
            # e.name naming some other package -> a missing extra dependency.
            if e.name and (e.name == prefix or prefix.startswith(e.name + ".")):
                return "FAIL", f"{prefix!r} is neither an attribute nor a module"
            return "SKIP", f"extra not installed (missing {e.name})"
        except Exception as e:
            return "FAIL", f"importing {prefix!r} raised {type(e).__name__}: {e}"
    return "OK", type(obj).__name__


# --- signature spot-checks -------------------------------------------------

def spot_litellm_completion() -> None:
    import litellm
    if not callable(getattr(litellm, "completion", None)):
        raise RuntimeError("litellm.completion is missing or not callable")


def spot_phoenix_register() -> None:
    from phoenix.otel import register
    sig = inspect.signature(register)
    params = set(sig.parameters)
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD
                     for p in sig.parameters.values())
    for want in ("project_name", "auto_instrument", "endpoint"):
        if want not in params and not has_var_kw:
            raise RuntimeError(
                f"phoenix.otel.register does not accept {want!r}; "
                f"parameters are {sorted(params)}")


def spot_fastmcp() -> None:
    from mcp.server.fastmcp import FastMCP
    if not hasattr(FastMCP, "tool"):
        raise RuntimeError("mcp.server.fastmcp.FastMCP has no 'tool' attribute")


def spot_shoplab_decide() -> None:
    from shoplab.rules import decide
    got = list(inspect.signature(decide).parameters)
    if got != ["ticket", "order", "customer"]:
        raise RuntimeError(
            f"shoplab.rules.decide takes {got}, expected "
            f"['ticket', 'order', 'customer']")


def spot_shoplab_search_policy() -> None:
    from shoplab.world import search_policy
    got = list(inspect.signature(search_policy).parameters)
    if got != ["query", "k"]:
        raise RuntimeError(
            f"shoplab.world.search_policy takes {got}, expected ['query', 'k']")


def spot_obs_enable_phoenix() -> None:
    import obs
    if not callable(getattr(obs, "enable_phoenix", None)):
        raise RuntimeError("obs.enable_phoenix is missing or not callable")


SPOT_CHECKS = [
    ("litellm.completion is callable", spot_litellm_completion, False),
    ("phoenix.otel.register accepts project_name/auto_instrument/endpoint",
     spot_phoenix_register, True),
    ("mcp.server.fastmcp.FastMCP exists and has a tool attribute",
     spot_fastmcp, True),
    ("shoplab.rules.decide takes (ticket, order, customer)",
     spot_shoplab_decide, False),
    ("shoplab.world.search_policy takes (query, k)",
     spot_shoplab_search_policy, False),
    ("obs.enable_phoenix is callable", spot_obs_enable_phoenix, False),
]


def main() -> None:
    names = gather_sources()
    counts = {"OK": 0, "SKIP": 0, "FAIL": 0}
    for name in sorted(names):
        status, detail = resolve(name)
        counts[status] += 1
        origins = ", ".join(sorted(names[name]))
        if status == "OK":
            print(f"OK   {name}  [{origins}]")
        elif status == "SKIP":
            print(f"SKIP {name} ({detail})  [{origins}]")
        else:
            print(f"FAIL {name}: {detail}  [{origins}]")
            fail(f"{name}: {detail} (used in {origins})")

    print()
    for label, check, is_extra in SPOT_CHECKS:
        try:
            check()
            print(f"OK   spot-check: {label}")
        except ModuleNotFoundError as e:
            if is_extra:
                print(f"SKIP spot-check: {label} (extra not installed: {e.name})")
            else:
                print(f"FAIL spot-check: {label} ({e})")
                fail(f"spot-check {label!r}: {e}")
        except Exception as e:
            print(f"FAIL spot-check: {label} ({e})")
            fail(f"spot-check {label!r}: {e}")

    print(f"\n{sum(counts.values())} names audited: {counts['OK']} ok, "
          f"{counts['SKIP']} skipped, {counts['FAIL']} failed.")
    if failures:
        print(f"\n{len(failures)} FAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("API audit passed.")


if __name__ == "__main__":
    main()
