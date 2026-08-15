# Reference — The framework comparison

A single table for the ten agent libraries this course meets, plus the dependency conflicts we
hit resolving them. The deep dives are chapters [16](../16-langgraph.ipynb) (LangGraph),
[17](../17-smolagents.ipynb) (smolagents), and [18](../18-crewai.ipynb) (CrewAI); the rest live in
the appendices. Chapter [15](../15-framework-thinking.ipynb) is the map this page is a legend for:
every framework repackages machinery you built by hand in Parts 1-4.

## How to read this

- **Archetype** is the shape the library sorts into once you strip the branding. Chapter 15 names
  five — `graph`, `typed`, `team`, `model-driven`, `code-as-action`; this page adds `workflow`
  (fixed, event-driven control flow you own, not a loop the model steers), the other side of
  Anthropic's [workflow-vs-agent line](https://www.anthropic.com/engineering/building-effective-agents).
  **Every archetype cell links to the primary source that supports it** (all URLs registered in
  `docs/citations.json`). Other columns are engineering facts from our own runs, not marketing.
- **Conflict notes** are the unique data here: what actually happened when we resolved each library
  against the course's base stack (`litellm>=1.96,<2`, `mcp[cli]>=1.28,<2`, `pydantic 2.13`,
  Python 3.12.3). Seven co-install on the main venv; three needed a fresh venv and a registered
  kernel. Measured 2026-08-15. The [resolver evidence](#resolver-evidence-our-own-data) section
  expands each note with exact pins and observed versions.
- **Install weight** is the transitive base-dependency closure (no extras) of the top-level
  package, counted from the installed metadata graph on 2026-08-15 — a like-for-like proxy, not a
  disk figure.
- **The seam moves in every row.** Each library routes model calls through its own client, so the
  cost `LEDGER` and disk cache you built in ch01/ch03 stop seeing them unless you re-instrument. The
  fixed appendix ticket **TKT-2205** (opened boots, member/non-vip, in-window) is the constant that
  makes the appendices comparable: every framework lands on the same gold from `shoplab.rules.decide`
  — **`partial_refund` / `pol-restocking` / `170.99`** ($189.99 x 0.90), approval-gated wherever the
  framework has a primitive for it.

## The table

| Framework | Archetype | State model | Persistence / checkpointing | HITL | MCP | Model access (agnostic?) | Weight (deps) | Conflict notes |
|---|---|---|---|---|---|---|---|---|
| **LangGraph** (ch16) | [graph](https://docs.langchain.com/oss/python/langgraph/overview) | `TypedDict` state + reducers (`add_messages`) | first-class [checkpointer + store](https://docs.langchain.com/oss/python/langgraph/persistence) | [`interrupt`](https://docs.langchain.com/oss/python/langgraph/interrupts) / `interrupt_before` | via `langchain-mcp-adapters` (separate pkg) | LangChain integrations; ch16 used `ChatOpenAI`, **had to strip `openrouter/`** (not LiteLLM-native) | medium ~36 (extra also pulls langchain + langchain-openai + deepagents) | co-installs (Py 3.12) |
| **smolagents** (ch17) | [code-as-action](https://huggingface.co/docs/smolagents/index) ([CodeAct](https://arxiv.org/abs/2402.01030)) | `agent.memory.steps` trajectory; code vars in the executor namespace | in-memory only | no per-tool gate; keep risky tools out of `CodeAgent` scope / sandbox | `mcp` extra (1.x) | `LiteLLMModel` — course `MODEL` string, `openrouter/` prefix intact | medium ~29 | co-installs |
| **CrewAI** (ch18) | [team](https://docs.crewai.com/) | `Task` outputs + `context=[...]` handoff | crew memory (opt-in); in-memory default | task-level `human_input` (coarse; not exercised in ch18) | base dep `mcp~=1.28.1` | `LLM("openrouter/...")` over LiteLLM | very heavy ~138 | **own venv:** `mcp~=1.28.1`, `pydantic<2.13`, `openai<3` |
| **OpenAI Agents SDK** ([appendix](A-openai-agents-sdk.ipynb)) | [model-driven](https://openai.github.io/openai-agents-python/) ([ReAct](https://arxiv.org/abs/2210.03629)) | `result.new_items` / `to_state()`; sessions | serializable run state; session memory | `needs_approval=True` + `state.approve()` | built-in `agents.mcp` (`mcp<3`) | default OpenAI; `LitellmModel` for provider-agnostic (we used it) | medium ~41 | **own venv:** needs `openai>=3` vs main litellm's `openai<3` |
| **PydanticAI** ([appendix](A-pydantic-ai.ipynb)) | [typed](https://pydantic.dev/docs/ai/overview/) | message history + typed `output_type` result | serialize history + `DeferredToolRequests` to resume | `requires_approval=True` + `DeferredToolRequests` | `mcp` extra via `fastmcp-slim` (3.x) | "every model a string swap away" (cited); we used `OpenAIChatModel` + `OpenRouterProvider` | light ~22 (`-slim`) | co-installs (`pydantic-ai-slim[openai]`) |
| **Google ADK** ([appendix](A-google-adk.ipynb)) | [model-driven](https://adk.dev/) + team (multi-agent) | `Session` + `State` via a session service | session service (`InMemoryRunner`; pluggable backends) | `require_confirmation=True` + `adk_request_confirmation` | `mcp` extra (`>=1.24,<2`) | native Gemini; `LiteLlm(model=MODEL)` for others (we used it) | heavy ~60 | co-installs; pins `openai<3` (aligned) |
| **Microsoft Agent Framework** ([appendix](A-microsoft-agent-framework.ipynb)) | [model-driven](https://learn.microsoft.com/en-us/agent-framework/overview/) + graph workflows | `AgentThread` / `AgentSession` | session carries the paused run; middleware hooks | `approval_mode="always_require"` + `to_function_approval_response` | `mcp` extra (`>=1.24,<2`) | model client is a **separate package**; we wrote a LiteLLM `BaseChatClient` | light ~8 (`-core` only) | co-installs (`agent-framework-core`) |
| **AWS Strands** ([appendix](A-aws-strands.ipynb)) | [model-driven](https://strandsagents.com/) (cited: "model-driven") | `Agent.messages` across turns; `SessionManager` | session manager (opt-in) | `BeforeToolCallEvent` + `cancel_tool` (light); heavier interrupt system available | base dep `mcp<2` | `LiteLLMModel(model_id=MODEL)` | medium ~47 | **own venv:** `strands[litellm]` caps `litellm<=1.95.0` (main pins `>=1.96`); also `mcp<2` |
| **LlamaIndex Workflows** ([appendix](A-llamaindex-workflows.ipynb)) | [workflow](https://developers.llamaindex.ai/python/llamaagents/workflows/) | `Context.store` + `Event` objects between `@step`s | `Context` (serializable); event-driven | `InputRequiredEvent` / `HumanResponseEvent` | via separate `llama-index` MCP tool spec (not the engine) | any LlamaIndex `LLM`; we used `LiteLLM` | light ~9 (standalone engine) | co-installs (`llama-index-workflows` + `-llms-litellm`) |
| **Agno** ([appendix](A-agno.ipynb)) | [model-driven](https://docs.agno.com/) + team + workflow (cited: "agents, teams, and workflows") | session message list (`run.messages` / `get_chat_history`) + `session_state` | session `db` / `memory_manager` (opt-in; in-memory in the appendix) | `@tool(requires_confirmation=True)` + `run.is_paused` / `continue_run` | `mcp` extra (`<2` + `fastmcp<4`) | native `OpenRouter` model class (multi-provider built-ins) | medium ~28 | co-installs (`agno` extra) |

Archetype cells carry two or three shapes for the libraries whose own docs advertise more than one
(ADK, Agno, Microsoft) — the linked term is the one this course exercises; the trailing terms are
what the same cited page also claims.

## Resolver evidence (our own data)

Running `pip install -e ".[<extra>]"` against the base stack, 2026-08-15, Python 3.12.3. Main venv
observed: `litellm 1.96.2`, `openai 2.54.0`, `mcp 1.29.0`, `pydantic 2.13.4`, with `fastmcp-slim 3.4.7`
coexisting — every framework below co-installs there **except** the three called out.

- **CrewAI — own venv.** `crewai 1.15.16` declares `mcp~=1.28.1` (resolves to `1.28.1`, below the
  main venv's `1.29.0`), `pydantic<2.13,>=2.11.9` (resolves to `2.12.5`, below the main venv's
  `2.13.4`), and `openai<3,>=2.30.0`. Two hard downgrades from the shared stack, plus by far the
  heaviest closure (~138). This is a real conflict, not tidiness (ch18 states the same).
- **OpenAI Agents SDK — own venv.** `openai-agents 0.21.0` requires `openai>=3.0.0,<4` (resolves to
  `3.1.0`). The main stack's `litellm 1.96.2` requires `openai>=2.20.0,<3.0.0`, so the two cannot
  share a venv; the resolver drops `litellm` to `1.83.0` (which lifts the `<3` cap) and pulls
  `mcp 2.0.0` — the **only** venv in the course where mcp goes to 2.x.
- **AWS Strands — own venv.** `strands-agents[litellm] 1.52.0` caps `litellm<=1.95.0`, directly
  below the course pin `litellm>=1.96`; the venv lands on `litellm 1.95.0`. It also pins
  `mcp<2.0.0,>=1.23.0` (the course-stated reason) and `openai<3` — both aligned with the main
  stack, so the binding conflict is the litellm cap.
- **The co-installers.** LangGraph, smolagents, PydanticAI (`-slim`), Google ADK,
  Microsoft `agent-framework-core`, LlamaIndex Workflows, and Agno all resolve cleanly onto the
  main venv. ADK is the heaviest of these (~60); `agent-framework-core` (~8) and
  `llama-index-workflows` (~9) are the lightest — both ship the runtime and leave the model client
  to a separate package or extra.

### The `mcp < 2` through-line

The course pins `mcp>=1.28,<2` and teaches `FastMCP` 1.x on purpose (ch13). mcp 2.0 renamed the
server class (`FastMCP` -> `MCPServer`), and the whole surrounding ecosystem still sits on the 1.x
line: `crewai` (`mcp~=1.28.1`), `strands-agents` (`mcp<2`), `google-adk` and `agent-framework-core`
(`mcp>=1.24,<2`), `agno` (`mcp<2`), and arize-phoenix's `fastmcp-slim 3.x` all resolve to `mcp 1.29.0`
in the main venv. Only the isolated openai-agents venv reached `mcp 2.0.0`, and it does not touch the
course's MCP server. See the [MCP Python SDK README](https://github.com/modelcontextprotocol/python-sdk)
("keep a `<2` upper bound ... until you've migrated") and the maintained
[v1.x branch](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) that the pin resolves to.
Separately, `arize-phoenix` 20.x forces **Python >= 3.12** on the whole course.

## Which to reach for

Start from a requirement and read off the archetype — the same move as ch15's checklist, now with a
concrete library on the end. None of these beats the plain `run_agent` loop until its defaults earn
the abstraction; Anthropic's [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
is right that the first answer is usually the simplest thing that works.

- **A durable, pausable run you can draw and audit** — an approval before money moves, state that
  survives a crash: **LangGraph** (ch16). Its checkpointer and `interrupt` are your ch08
  `Checkpoint` and `require_approval`, first-class.
- **The model should write code as its action** — multi-step arithmetic, chaining, looping in one
  block: **smolagents** (ch17). The one genuinely new execution model; keep the money-moving tools
  behind a validated gate and a sandbox.
- **Several scoped specialist roles on one job** — a triager and a policy checker holding different
  toolsets: **CrewAI** (ch18). Reach for it only when a second role buys isolation or a toolset, not
  a tidier diagram.
- **Typed, validated IO with the least ceremony** — declare the output shape, never write a parser:
  **PydanticAI** (appendix). Light (`-slim`), typed end to end.
- **A provider-agnostic model-driven loop with few abstractions** — `run_agent` with a logo, model
  swapped by a LiteLLM string: **OpenAI Agents SDK** or **AWS Strands** (appendices). Note both need
  their own venv.
- **A Gemini-native, session-backed enterprise runtime** with multi-agent orchestration:
  **Google ADK** (appendix). Heaviest co-installer, but a real `Session` service and a first-class
  confirmation pause.
- **AutoGen lineage plus Semantic Kernel enterprise features and graph workflows**, model client
  kept separate: **Microsoft Agent Framework** (appendix).
- **A fixed, known process pinned down as events** — no runtime planning, the model confined to one
  adjudication step: **LlamaIndex Workflows** (appendix). The `workflow` archetype; wrong when you
  want the model to find the process.
- **Batteries-included agents + teams + workflows with a production runtime (AgentOS)**: **Agno**
  (appendix). Its `@tool(requires_confirmation=True)` pause is your ch08 `require_approval`, and the
  session message list it threads is your ch02 loop state — assembled for you.

## Cross-references

- **Chapters:** [15 — Framework thinking](../15-framework-thinking.ipynb) (the five archetypes and
  the checklist), [16 — LangGraph](../16-langgraph.ipynb), [17 — smolagents](../17-smolagents.ipynb),
  [18 — CrewAI](../18-crewai.ipynb). MCP is [ch13](../13-mcp.ipynb); the machinery each framework
  repackages is Parts 1-4.
- **Appendices** (all on the fixed TKT-2205 scenario): [Agno](A-agno.ipynb),
  [PydanticAI](A-pydantic-ai.ipynb),
  [Google ADK](A-google-adk.ipynb), [Microsoft Agent Framework](A-microsoft-agent-framework.ipynb),
  [LlamaIndex Workflows](A-llamaindex-workflows.ipynb), [OpenAI Agents SDK](A-openai-agents-sdk.ipynb),
  [AWS Strands](A-aws-strands.ipynb).

## Sources

Every framework-identity claim above links to its `docs/citations.json` entry. URLs used, all
registered: LangGraph [overview](https://docs.langchain.com/oss/python/langgraph/overview) /
[persistence](https://docs.langchain.com/oss/python/langgraph/persistence) /
[interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts);
[smolagents](https://huggingface.co/docs/smolagents/index) and [CodeAct](https://arxiv.org/abs/2402.01030);
[CrewAI](https://docs.crewai.com/); [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
and [ReAct](https://arxiv.org/abs/2210.03629); [PydanticAI](https://pydantic.dev/docs/ai/overview/);
[Google ADK](https://adk.dev/); [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/);
[AWS Strands](https://strandsagents.com/); [LlamaIndex Workflows](https://developers.llamaindex.ai/python/llamaagents/workflows/);
[Agno](https://docs.agno.com/); [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
and its [v1.x branch](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x); and Anthropic's
[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents). Version,
dependency-count, and pin figures are from the installed metadata of the course venvs on 2026-08-15.
```
