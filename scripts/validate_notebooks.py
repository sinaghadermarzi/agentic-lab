#!/usr/bin/env python3
"""Static validation of the course notebooks (no execution, no network).

Run from anywhere:  python scripts/validate_notebooks.py

Enforces the machine-checkable parts of docs/CONVENTIONS.md:

- nbformat validity; Python syntax of every code cell; no "!" shell or "%" line
  magics; no emoji codepoints; no assert statements; stripped outputs and
  execution counts; the standard kernelspec.
- Byte-identity of the frozen config cell (first code cell of EVERY notebook)
  and the frozen Phoenix cell (second code cell of every numbered chapter,
  preceded by its markdown heading). Both canonical texts are PARSED from the
  python code fences in docs/CONVENTIONS.md -- single source of truth.
- The chapter skeleton (H1, "What you'll learn", time line, callouts, Recap
  table, exactly 3 exercises, "Next up:", section order, cell budget) and the
  lighter appendix skeleton (config cell, H1, cell budget, machinery-map table).
- Sentinel drift between notebooks and src/shoplab (build-then-import contract):
  paired "# >>> shoplab.X" / "# <<< shoplab.X" regions present in BOTH places
  must be byte-identical (trailing whitespace stripped per line). A region that
  exists on only one side is reported as INFO, not a failure.
- Citations: every http(s) URL outside the allowlist and every arXiv id cited
  in markdown must be registered in docs/citations.json.

Notebooks are discovered (repo-root NN-*.ipynb and appendices/A-*.ipynb) and
validated even when not yet listed in EXPECTED_CHAPTERS / EXPECTED_APPENDICES;
a listed notebook missing on disk is a failure. Zero notebooks passes: phase 1
ships the validator before the notebooks exist.
"""

import ast
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import nbformat

ROOT = Path(__file__).resolve().parent.parent
CONVENTIONS_MD = ROOT / "docs" / "CONVENTIONS.md"
CITATIONS_JSON = ROOT / "docs" / "citations.json"

# Filled in later phases as notebooks land. Discovered notebooks are validated
# even when unlisted; a listed file that is missing on disk is a failure.
EXPECTED_CHAPTERS: list[str] = [
    "00-orientation-and-the-ops-desk.ipynb",
    "01-the-model-boundary.ipynb",
    "02-the-tool-loop.ipynb",
    "03-tracing.ipynb",
    "04-evaluation.ipynb",
    "05-workflows.ipynb",
    "06-verification.ipynb",
    "07-multi-agent.ipynb",
    "08-production-controls.ipynb",
    "09-security.ipynb",
]
EXPECTED_APPENDICES: list[str] = []

# Chapter number ("NN") -> URLs / arXiv ids that MUST appear in that chapter.
# Filled in later phases alongside the chapters themselves.
REQUIRED_CITATIONS: dict[str, set[str]] = {}

# URLs whose domain is allowlisted need no docs/citations.json entry.
ALLOWED_DOMAINS = {"openrouter.ai", "docs.litellm.ai", "example.com"}
ALLOWED_GITHUB_PATH_PREFIX = "/sinaghadermarzi"

EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF))

H1_CHAPTER_RE = re.compile(r"^# \d\d — .+")
URL_RE = re.compile(r"https?://[^\s)\]>\"'`]+")
ARXIV_MD_RE = re.compile(r"arXiv:(\d{4}\.\d{4,5})")
ARXIV_URL_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})")
SENTINEL_OPEN_RE = re.compile(r"^\s*# >>> (shoplab\.[A-Za-z_][\w.]*)\s*$")
SENTINEL_CLOSE_RE = re.compile(r"^\s*# <<< (shoplab\.[A-Za-z_][\w.]*)\s*$")
NUMBERED_ITEM_RE = re.compile(r"^\s{0,3}\d+[.)]\s")

PHOENIX_MD_HEADING = "### Phoenix observability (optional)"
CALLOUT_MARKERS = ("> **What you should see", "> **What to look for",
                   "> **Expected result")
KERNEL_DISPLAY_NAME = "Python 3 (ipykernel)"

LAST_CHAPTER = "19"            # the only chapter without a "Next up:" teaser
CHAPTER_CELL_BUDGET = (18, 31)
APPENDIX_CELL_BUDGET = (12, 20)

failures: list[str] = []
infos: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def info(msg: str) -> None:
    infos.append(msg)


# --- frozen cells: parsed from docs/CONVENTIONS.md (single source of truth) ---

def frozen_cell_from_conventions(heading: str) -> str | None:
    """Return the text of the first ```python fence under `heading`, or None."""
    try:
        lines = CONVENTIONS_MD.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        fail(f"docs/CONVENTIONS.md: cannot read: {e}")
        return None
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        fail(f"docs/CONVENTIONS.md: heading {heading!r} not found")
        return None
    fence_start = None
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):          # ran into the next section
            break
        if lines[i].strip() == "```python":
            fence_start = i + 1
            break
    if fence_start is None:
        fail(f"docs/CONVENTIONS.md: no ```python fence under {heading!r}")
        return None
    body = []
    for line in lines[fence_start:]:
        if line.strip() == "```":
            return "\n".join(body)
        body.append(line)
    fail(f"docs/CONVENTIONS.md: unterminated ```python fence under {heading!r}")
    return None


# --- small helpers ---------------------------------------------------------

def md_cells(nb) -> list[str]:
    return [c.source for c in nb.cells if c.cell_type == "markdown"]


def code_cell_sources(nb) -> list[str]:
    return [c.source for c in nb.cells if c.cell_type == "code"]


def section_text(md: str, heading: str) -> str | None:
    """Markdown from `heading` up to the next H2 (or the end)."""
    start = md.find(heading)
    if start == -1:
        return None
    rest = md[start + len(heading):]
    nxt = re.search(r"^## ", rest, flags=re.M)
    return rest[:nxt.start()] if nxt else rest


def table_column_counts(text: str) -> list[int]:
    """Column counts of the markdown-table rows (|-delimited lines) in text."""
    counts = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and len(s) >= 3:
            counts.append(len(s.strip("|").split("|")))
    return counts


def url_is_allowlisted(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ALLOWED_DOMAINS:
        return True
    return host == "github.com" and parsed.path.startswith(ALLOWED_GITHUB_PATH_PREFIX)


def collect_sentinel_regions(text: str, where: str, dest: dict) -> None:
    """Collect '# >>> shoplab.X' ... '# <<< shoplab.X' regions from text."""
    current, buf = None, []
    for line in text.splitlines():
        m = SENTINEL_OPEN_RE.match(line)
        if m:
            if current is not None:
                fail(f"{where}: sentinel {current!r} still open when "
                     f"{m.group(1)!r} opens")
            current, buf = m.group(1), []
            continue
        m = SENTINEL_CLOSE_RE.match(line)
        if m:
            if current is None or m.group(1) != current:
                fail(f"{where}: sentinel close {m.group(1)!r} does not match "
                     f"open {current!r}")
                current = None
                continue
            body = "\n".join(l.rstrip() for l in buf)
            dest.setdefault(current, []).append((where, body))
            current = None
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        fail(f"{where}: sentinel {current!r} opened but never closed")


# --- citations -------------------------------------------------------------

def load_registered_citations() -> tuple[set[str], set[str]]:
    """(registered URLs, registered arXiv ids) from docs/citations.json."""
    if not CITATIONS_JSON.exists():
        info("docs/citations.json not present -- citation allowlist is empty")
        return set(), set()
    try:
        entries = json.loads(CITATIONS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fail(f"docs/citations.json: cannot parse: {e}")
        return set(), set()
    urls = {e["url"] for e in entries if isinstance(e, dict) and e.get("url")}
    arxiv = {e["arxiv"] for e in entries if isinstance(e, dict) and e.get("arxiv")}
    for u in urls:                              # arXiv ids embedded in entry URLs
        arxiv.update(ARXIV_URL_RE.findall(u))
    return urls, arxiv


def collect_cited(md: str) -> tuple[set[str], set[str]]:
    """(URLs, arXiv ids) cited in a notebook's concatenated markdown."""
    urls = {u.rstrip(".,;:!?*") for u in URL_RE.findall(md)}
    arxiv = set(ARXIV_MD_RE.findall(md))
    for u in urls:
        arxiv.update(ARXIV_URL_RE.findall(u))
    return urls, arxiv


# --- per-notebook checks ---------------------------------------------------

def check_notebook(path: Path, is_appendix: bool, config_cell: str | None,
                   phoenix_cell: str | None, sentinel_notebook_regions: dict,
                   registered_urls: set[str], registered_arxiv: set[str]) -> None:
    name = path.name if not is_appendix else f"appendices/{path.name}"
    try:
        nb = nbformat.read(path, as_version=4)
    except Exception as e:
        fail(f"{name}: cannot read notebook: {e}")
        return
    try:
        nbformat.validate(nb)
    except Exception as e:
        fail(f"{name}: nbformat validation error: {e}")

    kernelspec = nb.metadata.get("kernelspec", {})
    if kernelspec.get("display_name") != KERNEL_DISPLAY_NAME:
        fail(f"{name}: kernelspec display_name is "
             f"{kernelspec.get('display_name')!r}, expected {KERNEL_DISPLAY_NAME!r}")

    # -- cell-level checks --
    code_index_in_cells = [i for i, c in enumerate(nb.cells)
                           if c.cell_type == "code"]
    for ci, cell in enumerate(nb.cells):
        for ch in cell.source:
            cp = ord(ch)
            if any(lo <= cp <= hi for lo, hi in EMOJI_RANGES):
                fail(f"{name}: cell {ci} contains banned emoji codepoint "
                     f"U+{cp:04X} ({ch!r})")
                break

    for i, src in enumerate(code_cell_sources(nb)):
        for line in src.splitlines():
            if line.lstrip().startswith(("!", "%")):
                fail(f"{name}: code cell {i} uses a shell/line magic: "
                     f"{line.strip()[:60]}")
        try:
            # PyCF_ALLOW_TOP_LEVEL_AWAIT: ipykernel accepts top-level await.
            tree = compile(src, f"<{name}:code-cell-{i}>", "exec",
                           ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        except SyntaxError as e:
            fail(f"{name}: syntax error in code cell {i}: {e}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                fail(f"{name}: code cell {i} contains an assert statement "
                     f"(line {node.lineno}) -- expectations belong in callouts")
                break
        collect_sentinel_regions(src, f"{name}:code-cell-{i}",
                                 sentinel_notebook_regions)

    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        if cell.get("outputs"):
            fail(f"{name}: code cell has non-empty outputs "
                 f"(run scripts/strip_outputs.py before committing)")
            break
    for cell in nb.cells:
        if cell.cell_type == "code" and cell.get("execution_count") is not None:
            fail(f"{name}: code cell has a non-null execution_count "
                 f"(run scripts/strip_outputs.py before committing)")
            break

    # -- frozen cells --
    code_srcs = code_cell_sources(nb)
    if config_cell is not None:
        if not code_srcs:
            fail(f"{name}: no code cells -- the frozen config cell must be "
                 f"the first code cell")
        elif code_srcs[0] != config_cell:
            fail(f"{name}: first code cell is not byte-identical to the frozen "
                 f"config cell in docs/CONVENTIONS.md")
    if not is_appendix and phoenix_cell is not None:
        if len(code_srcs) < 2:
            fail(f"{name}: fewer than 2 code cells -- the frozen Phoenix cell "
                 f"must be the second code cell")
        else:
            if code_srcs[1] != phoenix_cell:
                fail(f"{name}: second code cell is not byte-identical to the "
                     f"frozen Phoenix cell in docs/CONVENTIONS.md")
            second_idx = code_index_in_cells[1]
            prev = nb.cells[second_idx - 1] if second_idx > 0 else None
            if (prev is None or prev.cell_type != "markdown"
                    or PHOENIX_MD_HEADING not in prev.source):
                fail(f"{name}: the Phoenix cell is not preceded by a markdown "
                     f"cell containing {PHOENIX_MD_HEADING!r}")

    # -- skeleton --
    mds = md_cells(nb)
    md = "\n".join(mds)
    md_lines = md.splitlines()
    n_cells = len(nb.cells)

    if is_appendix:
        lo, hi = APPENDIX_CELL_BUDGET
        if not lo <= n_cells <= hi:
            fail(f"{name}: {n_cells} cells, appendix budget is {lo}-{hi}")
        if not mds or not mds[0].startswith("# "):
            fail(f"{name}: first markdown cell is not an H1 title")
        machinery_ok = False
        for j, src in enumerate(mds):
            if "machinery map" in src.lower():
                nearby = src + ("\n" + mds[j + 1] if j + 1 < len(mds) else "")
                counts = table_column_counts(nearby)
                if len(counts) >= 3:
                    machinery_ok = True
                break
        if not machinery_ok:
            fail(f"{name}: no 'machinery map' markdown table found")
        return

    # numbered chapter
    lo, hi = CHAPTER_CELL_BUDGET
    if not lo <= n_cells <= hi:
        fail(f"{name}: {n_cells} cells, chapter budget is {lo}-{hi}")

    if not mds or not H1_CHAPTER_RE.match(mds[0]):
        fail(f"{name}: first markdown cell does not match H1 pattern "
             f"'# NN — Title'")
    learn_zone = mds[0] + ("\n" + mds[1] if len(mds) > 1 else "") if mds else ""
    if "**What you'll learn**" not in learn_zone:
        fail(f"{name}: missing \"**What you'll learn**\" in the first or "
             f"second markdown cell")
    if not any(line.startswith("*Time:") for line in md_lines):
        fail(f"{name}: missing the italic '*Time: ...' line")
    if not any(marker in md for marker in CALLOUT_MARKERS):
        fail(f"{name}: no callout found (need at least one of "
             f"'What you should see' / 'What to look for' / 'Expected result')")

    recap = section_text(md, "## Recap")
    if recap is None:
        fail(f"{name}: missing section '## Recap'")
    else:
        counts = table_column_counts(recap)
        if len(counts) < 3 or any(c != 2 for c in counts):
            fail(f"{name}: '## Recap' must contain a two-column markdown table")

    exercises = section_text(md, "## Exercises")
    if exercises is None:
        fail(f"{name}: missing section '## Exercises'")
    else:
        items = [l for l in exercises.splitlines() if NUMBERED_ITEM_RE.match(l)]
        if len(items) != 3:
            fail(f"{name}: '## Exercises' has {len(items)} numbered items, "
                 f"expected exactly 3")

    if name[:2] != LAST_CHAPTER and "**Next up:**" not in md:
        fail(f"{name}: missing '**Next up:**' teaser")

    title_pos = 0 if mds and H1_CHAPTER_RE.match(mds[0]) else -1
    recap_pos = md.find("## Recap")
    ex_pos = md.find("## Exercises")
    if recap_pos != -1 and ex_pos != -1:
        if not (title_pos < recap_pos < ex_pos):
            fail(f"{name}: sections out of order (need title < '## Recap' "
                 f"< '## Exercises')")

    # -- citations --
    cited_urls, cited_arxiv = collect_cited(md)
    for url in sorted(cited_urls):
        if url_is_allowlisted(url):
            continue
        ids_in_url = set(ARXIV_URL_RE.findall(url))
        if url in registered_urls or ids_in_url & registered_arxiv:
            continue
        fail(f"{name}: URL not registered in docs/citations.json: {url}")
    for aid in sorted(cited_arxiv):
        if aid not in registered_arxiv:
            fail(f"{name}: arXiv id not registered in docs/citations.json: {aid}")
    required = REQUIRED_CITATIONS.get(name[:2], set())
    missing = {r for r in required if r not in cited_urls and r not in cited_arxiv}
    if missing:
        fail(f"{name}: missing required citations: {sorted(missing)}")


# --- main ------------------------------------------------------------------

def main() -> None:
    config_cell = frozen_cell_from_conventions("## The frozen config cell")
    phoenix_cell = frozen_cell_from_conventions("## The frozen Phoenix cell")
    registered_urls, registered_arxiv = load_registered_citations()

    chapters = sorted(ROOT.glob("[0-9][0-9]-*.ipynb"))
    appendices = sorted((ROOT / "appendices").glob("A-*.ipynb"))

    for listed in EXPECTED_CHAPTERS:
        if not (ROOT / listed).exists():
            fail(f"listed chapter missing from repo root: {listed}")
    for listed in EXPECTED_APPENDICES:
        if not (ROOT / "appendices" / listed).exists():
            fail(f"listed appendix missing from appendices/: {listed}")
    for path in chapters:
        if EXPECTED_CHAPTERS and path.name not in EXPECTED_CHAPTERS:
            info(f"{path.name}: not yet listed in EXPECTED_CHAPTERS")
    for path in appendices:
        if EXPECTED_APPENDICES and path.name not in EXPECTED_APPENDICES:
            info(f"appendices/{path.name}: not yet listed in EXPECTED_APPENDICES")

    notebook_regions: dict[str, list[tuple[str, str]]] = {}
    for path in chapters:
        check_notebook(path, False, config_cell, phoenix_cell, notebook_regions,
                       registered_urls, registered_arxiv)
    for path in appendices:
        check_notebook(path, True, config_cell, phoenix_cell, notebook_regions,
                       registered_urls, registered_arxiv)

    # -- sentinel drift: notebooks vs src/shoplab --
    package_regions: dict[str, list[tuple[str, str]]] = {}
    for py in sorted((ROOT / "src" / "shoplab").glob("*.py")):
        collect_sentinel_regions(py.read_text(encoding="utf-8"),
                                 f"src/shoplab/{py.name}", package_regions)

    for region in sorted(set(notebook_regions) | set(package_regions)):
        nb_occurrences = notebook_regions.get(region, [])
        pkg_occurrences = package_regions.get(region, [])
        if not pkg_occurrences:
            info(f"sentinel region {region!r} only in notebooks "
                 f"({', '.join(w for w, _ in nb_occurrences)}) -- no package "
                 f"counterpart yet")
            continue
        if not nb_occurrences:
            info(f"sentinel region {region!r} only in package "
                 f"({', '.join(w for w, _ in pkg_occurrences)}) -- no notebook "
                 f"counterpart yet")
            continue
        bodies = {body for _, body in nb_occurrences + pkg_occurrences}
        if len(bodies) > 1:
            wheres = [w for w, _ in nb_occurrences + pkg_occurrences]
            fail(f"sentinel region {region!r} drifted between "
                 f"{', '.join(wheres)} -- bodies must be byte-identical")

    # -- report --
    for line in infos:
        print("INFO:", line)
    n = len(chapters) + len(appendices)
    if failures:
        print(f"\n{len(failures)} FAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print(f"All checks passed for {n} notebooks "
          f"({len(chapters)} chapters, {len(appendices)} appendices).")


if __name__ == "__main__":
    main()
