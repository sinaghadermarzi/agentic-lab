# Measured course costs

Method: every notebook executed top-to-bottom against the live default model
(`openrouter/deepseek/deepseek-v3.2`, temperature 0) in one serial sweep on
2026-08-15, starting from a **cold** litellm disk cache, so the numbers are
what a new learner's first full pass actually costs. Per-notebook figures are the
OpenRouter credit delta measured around that notebook's run. Two notebooks hit a
transient provider disconnect during the sweep and were re-run to green (their
re-run figures shown). Rows marked `$0.00*` made calls that were either served
from the cache warmed earlier in the same sweep or issued through clients whose
spend the per-notebook delta could not attribute; the course total below is the
sum of all metered deltas and is the authoritative number.

Cached reruns are ~free: the disk cache (`.litellm_cache/`) replays identical
calls without touching the network.

## Chapters

| Notebook | Wall time | Measured cost |
|---|---|---|
| `00-orientation-and-the-ops-desk.ipynb` | 23s | $0.00* |
| `01-the-model-boundary.ipynb` | 24s | $0.00* |
| `02-the-tool-loop.ipynb` | 57s | $0.0013 |
| `03-tracing.ipynb` | 47s | $0.0035 |
| `04-evaluation.ipynb` | 441s | $0.0194 |
| `05-workflows.ipynb` | 213s | $0.0180 |
| `06-verification.ipynb` | 37s | $0.0011 |
| `07-multi-agent.ipynb` | 101s | $0.0043 |
| `08-production-controls.ipynb` | 41s | $0.00* |
| `09-security.ipynb` | 345s | $0.0150 |
| `10-context-engineering.ipynb` | 48s | $0.0042 |
| `11-deep-agents.ipynb` | 314s | $0.0205 |
| `12-interrupt-resume-compact.ipynb` | 79s | $0.0017 |
| `13-mcp.ipynb` | 34s | $0.00* |
| `14-a2a.ipynb` | 16s | $0.00* |
| `15-framework-thinking.ipynb` | 42s | $0.00* |
| `16-langgraph.ipynb` | 82s | $0.0010 |
| `17-smolagents.ipynb` | 69s | $0.0074 |
| `18-crewai.ipynb` | 32s | $0.00* |
| `19-capstone.ipynb` | 180s | $0.0199 |

## Appendices

| Notebook | Wall time | Measured cost |
|---|---|---|
| `A-agno.ipynb` | 21s | $0.00* |
| `A-aws-strands.ipynb` | 26s | $0.00* |
| `A-google-adk.ipynb` | 37s | $0.0027 |
| `A-llamaindex-workflows.ipynb` | 8s | $0.00* |
| `A-microsoft-agent-framework.ipynb` | 34s | $0.0019 |
| `A-openai-agents-sdk.ipynb` | 24s | $0.00* |
| `A-pydantic-ai.ipynb` | 26s | $0.00* |

**Whole course, cold, one pass: ~$0.12.** Warm reruns: ~$0.
