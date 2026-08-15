# Course conventions

Normative for every notebook and module in this repo. `scripts/validate_notebooks.py` enforces
the machine-checkable parts. The conventions mirror the sibling course
[`dspy-lab`](https://github.com/sinaghadermarzi/dspy-lab) so that **one `.env` serves both
repos** — same variable names, same defaults, same setup rhythm.

## Model configuration

- The one required secret: `OPENROUTER_API_KEY`.
- `MODEL` / `STRONG_MODEL` are LiteLLM provider strings; unset means exactly these defaults:
  `openrouter/deepseek/deepseek-v3.2` and `openrouter/deepseek/deepseek-v4-flash`.
- The whole course runs at `temperature=0` (the config cell sets `TEMPERATURE = 0`; every call
  passes it). Only a deliberately-contrastive demo may use another temperature, stated inline.
- Python **>= 3.12** (arize-phoenix 20.x crashes on import under 3.11).

## The frozen config cell

Byte-identical in **every** notebook (chapters and appendices), always the first code cell.
The validator compares against this text exactly:

```python
# === config (identical in every notebook) ===
import os, getpass
import litellm
from dotenv import load_dotenv              # pip install -e ".[obs]" if this fails

load_dotenv(".env")   # reads OPENROUTER_API_KEY / MODEL / STRONG_MODEL (see .env.example)

if not os.environ.get("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = getpass.getpass("OpenRouter API key: ")

MODEL = os.environ.get("MODEL", "openrouter/deepseek/deepseek-v3.2")
STRONG_MODEL = os.environ.get("STRONG_MODEL", "openrouter/deepseek/deepseek-v4-flash")

# Per-notebook override: uncomment to ignore .env here (any LiteLLM provider works).
# MODEL = "openrouter/google/gemini-2.5-flash-lite"
# MODEL = "openai/gpt-4o-mini"              # direct OpenAI, uses OPENAI_API_KEY instead

TEMPERATURE = 0                             # the whole course runs at temperature 0
litellm.drop_params = True                  # ignore params a provider does not support
litellm.cache = litellm.Cache(type="disk", disk_cache_dir=".litellm_cache")  # reruns are ~free
```

## The frozen Phoenix cell

In every numbered chapter (not appendices), immediately after the config cell, preceded by a
short markdown cell headed `### Phoenix observability (optional)`:

```python
# optional: Phoenix tracing (see notebook 03)
import obs

obs.enable_phoenix()
```

Observability is **Phoenix-only** in this course. `obs.py` finds-or-starts a local Phoenix
server (port 6006, health-checked, background process that survives kernel restarts) and logs
under the dated project `agentic-lab-YYYY-MM-DD`.

## Chapter skeleton

Required, in order (validator-enforced):

1. H1 title cell: `# NN — Title: elaboration` (em dash), then `**What you'll learn**` with 3–5
   bullets (concrete capabilities, backticked API names), then an italic line:
   `*Time: ~X min. Cost: ~$Y. Cached reruns are free.*`
2. The frozen config cell, then the Phoenix markdown + cell.
3. Body: `## Section` headers with opinionated titles → 1–3 short prose paragraphs → a small
   code cell (median 5–10 lines, max ~15 for hand-written cells) → a blockquote callout
   `> **What you should see:** ...` phrased as **invariants, not exact strings** (temp 0 does
   not make providers deterministic). Variants allowed: `> **What to look for:**`,
   `> **Expected result:**`.
4. `## Recap` — always a two-column table `| Concept | One-liner |`.
5. `## Exercises` — exactly 3 numbered items, phrased as investigations; cost-flag any pricey
   one. End the cell with `**Next up:**` one-sentence teaser (all chapters except the last).

Budgets: 18–31 cells per chapter (12–20 for appendices), markdown:code roughly 2:1. **No
emoji. No `assert` in notebooks** (expectations live in the callouts; machine checks live in
`tests/` and `scripts/`). No `!` shell or `%` line magics. Outputs stripped before commit.
Kernelspec: `Python 3 (ipykernel)` / `python3`.

## The build-then-import contract (sentinel drift-checks)

A chapter *builds* a piece of machinery in-notebook; later chapters *import* it from
`shoplab`. The canonical function bodies are marked with paired sentinels in BOTH places:

```python
# >>> shoplab.loop.run_agent
def run_agent(...):
    ...
# <<< shoplab.loop.run_agent
```

The validator extracts each region from its home notebook and from `src/shoplab/*.py` and
requires **byte identity**. Regions: `world.search_policy` (ch00), `llm.parse_json_loose`
(ch01), `loop.run_agent` (ch02), `trace.Span` (ch03), `rules.decide` + `evals.score_ticket`
(ch04), `controls.Budget` + `controls.Checkpoint.save` (ch08), `context.compact` (ch10).

## Install boxes

The base install (`pip install -e ".[obs]"`) covers chapters 00–10 and 12. A chapter needing
an extra opens with a standardized markdown "Install box" right after the title cell:

> **Before running this notebook:** `pip install -e ".[langgraph]"` (once). Everything else
> stays the same.

Extras: ch11/16 `.[langgraph]`, ch13/19 `.[mcp]`, ch14/19 `.[a2a]`, ch17 `.[smolagents]`.
Appendices: `.[pydantic-ai]`, `.[adk]`, `.[msaf]`, `.[llamaindex]`, `.[agno]` in the main
venv. Three frameworks have resolver-proven conflicts with the main stack and get a **fresh
venv + registered kernel** (exact 3-command box in the notebook): `.[crewai]` (pins
`mcp~=1.28`, `pydantic<2.13`, `openai<3`), `.[strands]` (pins `mcp<2`), `.[openai-agents]`
(needs `openai>=3`; litellm pins `openai<3`).

## Citations

Every claim about a framework, protocol, or tool cites a primary source (spec, official docs,
release notes, paper). **Never write a docs URL from memory** — every URL is fetched at
authoring time (via `curl` through the build proxy; the snippet confirming the claim is
recorded) and registered in `docs/citations.json`:

```json
{"url": "https://...", "kind": "docs|spec|paper|release",
 "claim": "one sentence the source supports", "fetched_at": "2026-08-15",
 "excerpt": "short verbatim phrase found on the page"}
```

`scripts/validate_notebooks.py` builds its URL/arXiv allowlists from this file and fails any
notebook citing an unregistered source. Paper sections use a three-column table:
`| Paper concept | Plain English | Where it lives in code |` under a full citation line.

## MCP version note

The course pins `mcp>=1.28,<2` and teaches `FastMCP` (stdio). This is deliberate: mcp 2.0
(released just before authoring) renamed the server API, and the surrounding ecosystem —
arize-phoenix's `fastmcp-slim`, `agent-framework-core`, `crewai`, `strands-agents` — all pin
`mcp<2` (resolver-verified). Chapter 13 states this with citations.
