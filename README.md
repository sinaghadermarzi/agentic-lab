# agentic-lab

A hands-on Jupyter course on agentic systems that builds the machinery by hand before it names a
single framework. You write the tool loop, the tracing layer, the eval harness, the budget and
approval gates, the checkpointer, and the context-management tools yourself, in plain Python, each
piece small enough to read in one sitting. Only then do the frameworks — LangGraph, smolagents,
CrewAI, MCP, A2A, and a shelf of others — arrive as what they actually are: opinionated packagings
of parts you already own. Every chapter makes live model calls, measures what they cost, and grades
its output against fixed gold labels in one small persistent micro-world. Nothing here is a paper
exercise, and nothing here is magic by the time you meet it.

The through-line is a **build-then-import contract**: a chapter writes a piece of machinery in the
notebook, later chapters import it from the `shoplab` package, and a validator checks the two copies
are byte-identical so the thing you read is exactly the thing that runs. By the end of Part 1 there is
a real package whose every important function you first wrote by hand.

## The mental model

The point of building the un-branded version first is that every framework feature then reads as
"which of my parts did they package, and how?" The seam is the same in every row.

| You build, by hand | Lives in | The framework name for it |
|---|---|---|
| `run_agent` tool loop (ReAct) | `shoplab.loop` (ch02) | OpenAI Agents SDK `Runner`, smolagents `CodeAgent`, the model-driven loop |
| Router / supervisor over sub-agents | `shoplab.loop` (ch07) | CrewAI crew, LangGraph conditional edges, handoffs |
| `Span` tracer | `shoplab.trace` (ch03) | Phoenix / OpenInference spans |
| `Budget` ceiling on calls and dollars | `shoplab.controls` (ch08) | LangGraph `recursion_limit`; most frameworks leave it to you |
| `require_approval` gate on risky tools | `shoplab.controls` (ch08) | LangGraph `interrupt`, OpenAI SDK `needs_approval`, Agno `requires_confirmation` |
| `Checkpoint.save` / resume | `shoplab.controls` (ch08) | LangGraph checkpointer + store; PydanticAI `DeferredToolRequests` |
| `run_subagent` policy firewall | `shoplab.loop` (ch07, ch11) | LangGraph subgraph, CrewAI crew, `deepagents` |
| `context.compact` | `shoplab.context` (ch10) | LangGraph `add_messages` reducer, framework memory managers |
| Tool bridge over the wire | `mcp_servers/` (ch13) | MCP `FastMCP` server + client |

## The micro-world

Every chapter runs against **Larkspur Outfitters**, a small fictional online outdoor-gear shop seen
from its back office, learned once in chapter 00. The recurring job is to **triage return/refund
tickets**: decide what the customer gets, cite the policy that says so, and compute the amount to the
cent. Names, SKUs, and people are all invented so a model cannot lean on memorized priors, the data
is 40 gold-labeled tickets split train/dev/test, and the labels are computed by a rules engine rather
than hand-assigned — see [`docs/WORLD.md`](docs/WORLD.md) for the full schema and the refund cascade.
The agent works a fixed toolset — `get_order`, `get_customer`, `search_policy`, `check_inventory`,
`calc`, and the two risky, gated writes `issue_refund` and `create_replacement` — the same set every
chapter extends rather than replaces, which is what keeps twenty chapters comparable.

## Setup

Requires Python **>= 3.12** (arize-phoenix 20.x crashes on import under 3.11).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[obs]"
cp .env.example .env    # then add your OPENROUTER_API_KEY
jupyter lab
```

**One `.env` for the whole course.** The single required key is `OPENROUTER_API_KEY` — the default
models route through OpenRouter. `MODEL` and `STRONG_MODEL` are optional; unset, they fall back to
`openrouter/deepseek/deepseek-v3.2` and `openrouter/deepseek/deepseek-v4-flash`. Any LiteLLM provider
string works (`openai/gpt-4o-mini`, `openrouter/google/gemini-2.5-flash-lite`, ...), so you can point
a single variable anywhere. The `.env` contract is byte-for-byte identical to the sibling course
[dspy-lab](https://github.com/sinaghadermarzi/dspy-lab), so one `.env` file serves both repos.

## Curriculum

Costs are the dollar figure read off the model responses on a first, cold run; every cached rerun is
free. Full breakdown in [`docs/costs.md`](docs/costs.md).

**Part 1 — The machinery.** Build the core: a live call, the structured-output boundary, the tool
loop, tracing, and evaluation.

| # | Title | What you learn | Cost |
|---|---|---|---|
| 00 | Orientation: the course, the shop, your first live call | First live `litellm.completion`, the disk cache, loading the micro-world | < $0.01 |
| 01 | The model boundary: prompts as interfaces, JSON as a contract | Prompts as APIs; `parse_json_loose` as the model/code seam | $0.001 |
| 02 | The tool loop: ReAct by hand, twice | `run_agent`, the tool registry, the `Ledger`, ReAct built from scratch | $0.01 |
| 03 | Tracing: build the spans, then meet Phoenix | A `Span` tracer by hand, then the same data in Phoenix | $0.002 |
| 04 | Evaluation: gold labels, decision accuracy, catching regressions | `score_ticket`, decision accuracy, and a regression harness | $0.02 |

**Part 2 — Patterns of control.** When to take the loop away from the model, and how to compose more
than one agent.

| # | Title | What you learn | Cost |
|---|---|---|---|
| 05 | Workflows: when fixed control flow beats an agent | Fixed control flow vs. an agent; parallel fan-out | $0.02 |
| 06 | Verification: draft, critique, revise | The draft/critique/revise loop and a verifier gate | $0.001 |
| 07 | Multi-agent: supervisor, tools-that-are-agents, handoffs | Router, sub-agents-as-tools, and handoffs | $0.01 |

**Part 3 — Production.** Budgets, gates, checkpoints, injection defense, context management, and a
deep agent that composes them all.

| # | Title | What you learn | Cost |
|---|---|---|---|
| 08 | Production controls: budgets, checkpoints, approval gates | `Budget`, `Checkpoint`, and the `require_approval` gate | $0.01 |
| 09 | Security: prompt injection through tool results | Injection through tool output; defenses that hold | $0.02 |
| 10 | Context engineering: why flat loops die | `context.compact` and the `ContextLedger` | $0.01 |
| 11 | A deep agent, end to end | Composing loop + firewall + gate + budget into one agent | $0.03 |
| 12 | Interrupt, resume, compact: the ops story | A durable, pausable, resumable run | $0.01 |

**Part 4 — Interoperability.** Point the desk outward, still by hand.

| # | Title | What you learn | Cost |
|---|---|---|---|
| 13 | MCP: the wire format, then the SDK | The `initialize` handshake, `tools/list`, `tools/call`, then `FastMCP` | $0.02 |
| 14 | A2A: agents as peers | Agent Cards, the task lifecycle, a supplier agent over HTTP | $0.01 |

**Part 5 — The frameworks.** Hold your machinery up against the libraries the field reaches for.

| # | Title | What you learn | Cost |
|---|---|---|---|
| 15 | Framework thinking: what they buy, and the archetypes | The five archetypes; a requirement-to-framework checklist | $0.01 |
| 16 | LangGraph: the graph archetype | Graph state, checkpointer, and `interrupt` vs. your own | $0.03 |
| 17 | smolagents: code as action | CodeAct — the one execution model you did not build by hand | $0.02 |
| 18 | CrewAI: the team archetype (and a lesson in dependency pins) | A crew of scoped roles; why it needs its own venv | $0.01 |

**Part 6 — Capstone.**

| # | Title | What you learn | Cost |
|---|---|---|---|
| 19 | Capstone: the whole desk, end to end | The morning queue, wired through MCP + A2A + every control | $0.02 |

**Whole course: under $0.30 on a first live run** — a full cold sweep of all 27 notebooks
measured **~$0.12** of metered spend ([docs/costs.md](docs/costs.md)); cached reruns are free.

### Appendices

Seven framework appendices each run the *same* fixed ticket (**TKT-2205**, gold `partial_refund /
pol-restocking / $170.99`) so you can compare frameworks on one problem, plus two reference pages.

| File | What it covers |
|---|---|
| [`A-pydantic-ai.ipynb`](appendices/A-pydantic-ai.ipynb) | PydanticAI — the typed agent loop |
| [`A-openai-agents-sdk.ipynb`](appendices/A-openai-agents-sdk.ipynb) | OpenAI Agents SDK — model-driven loop, gated (isolated venv) |
| [`A-google-adk.ipynb`](appendices/A-google-adk.ipynb) | Google ADK — agent, runner, and session |
| [`A-microsoft-agent-framework.ipynb`](appendices/A-microsoft-agent-framework.ipynb) | Microsoft Agent Framework — the same triage, gated |
| [`A-aws-strands.ipynb`](appendices/A-aws-strands.ipynb) | AWS Strands — model-driven and gated (isolated venv) |
| [`A-llamaindex-workflows.ipynb`](appendices/A-llamaindex-workflows.ipynb) | LlamaIndex Workflows — fixed control flow as events |
| [`A-agno.ipynb`](appendices/A-agno.ipynb) | Agno — the batteries-included agent |
| [`R-framework-comparison.md`](appendices/R-framework-comparison.md) | Ten libraries in one table, with resolver evidence |
| [`R-agent-protocol-landscape.md`](appendices/R-agent-protocol-landscape.md) | MCP, A2A, AG-UI, AP2, and the rest as one stack |

## Extras: install before these chapters

The base install (`pip install -e ".[obs]"`) covers chapters 00–10 and 12. Some chapters open with a
standardized install box. Follow the sequence; no judgement calls.

| Before | Run | Notes |
|---|---|---|
| ch11, ch16 | `pip install -e ".[langgraph]"` | main venv |
| ch13, ch19 | `pip install -e ".[mcp]"` | main venv |
| ch14, ch19 | `pip install -e ".[a2a]"` | main venv |
| ch17 | `pip install -e ".[smolagents]"` | main venv |

Three notebooks — **ch18 (CrewAI)**, **A-aws-strands**, **A-openai-agents-sdk** — have
resolver-proven dependency conflicts with the main stack and must run in their own venv with a
registered kernel. Set each up once (substitute `crewai` / `strands` / `openai-agents`):

```bash
python -m venv .venv-crewai && . .venv-crewai/bin/activate
pip install -e ".[crewai]"
python -m ipykernel install --user --name agentic-lab-crewai
```

Then pick the kernel `agentic-lab-crewai` (or `-strands` / `-openai-agents`) for that notebook. The
conflicts are real, not tidiness: CrewAI downgrades `mcp`, `pydantic`, and `openai`; Strands caps
`litellm<=1.95` below the course pin; OpenAI Agents needs `openai>=3` where the main stack pins
`openai<3`. The exact pins and observed versions are in
[`appendices/R-framework-comparison.md`](appendices/R-framework-comparison.md).

## Observability

Observability is **Phoenix-only and optional**. Every numbered chapter carries one frozen cell,
`obs.enable_phoenix()`, which finds-or-starts a local Phoenix server (port 6006, health-checked, a
background process that survives kernel restarts) and logs every model call under the dated project
`agentic-lab-YYYY-MM-DD`. It is taught once, in chapter 03; before that you build the tracer by hand.
The traces are there when you want to look and free to ignore when you don't — no chapter depends on
Phoenix running.

## Repo map

```
agentic-lab/
├── 00-orientation-and-the-ops-desk.ipynb ... 19-capstone.ipynb   # the 20 numbered chapters
├── appendices/           # 7 framework appendices (A-*.ipynb) + 2 reference pages (R-*.md)
├── src/shoplab/          # the package you build across the course (loop, tools, controls, ...)
├── data/                 # the hand-authored micro-world: products, orders, tickets, policies (JSON)
├── mcp_servers/          # the shop's tools exposed over MCP (ch13)
├── a2a_servers/          # the supplier peer agent over A2A (ch14)
├── scripts/              # validate_notebooks, check_data, execute_notebooks, strip_outputs
├── tests/                # pytest suite guarding shoplab + the data invariants
├── docs/                 # CONVENTIONS.md, WORLD.md, costs.md, citations.json
├── obs.py                # the Phoenix find-or-start helper
└── pyproject.toml        # base deps + every framework extra
```

## How this was built / quality

Every chapter was executed live at `temperature=0` and its costs measured on a real run, not
estimated. The hand-built machinery is drift-checked byte-for-byte: each canonical function is marked
with paired sentinels in both its home notebook and `src/shoplab/`, and the validator fails on any
divergence. **185 tests** guard the package and the data invariants (every gold ticket recomputed
from the rules engine). Every claim about a framework, protocol, or tool cites a primary source
fetched at authoring time and registered in [`docs/citations.json`](docs/citations.json) — no URL is
written from memory. The framework comparisons are engineering facts from our own resolver runs, not
marketing copy: each library was installed against the base stack on one dated pass, and what
actually happened — which co-installed, which forced its own venv, and why — is recorded with the
observed versions.

## Sources

Every external claim is backed by a registered primary source in
[`docs/citations.json`](docs/citations.json). The two reference pages collect the framework and
protocol landscapes with their citations: [`appendices/R-framework-comparison.md`](appendices/R-framework-comparison.md)
and [`appendices/R-agent-protocol-landscape.md`](appendices/R-agent-protocol-landscape.md).
