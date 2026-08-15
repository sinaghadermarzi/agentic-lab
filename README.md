# agentic-lab

A hands-on Jupyter course on agentic systems. You build the machinery by hand
first — the LLM layer, the tool loop, tracing, evaluation, controls — and only
then meet the frameworks (LangGraph, smolagents, MCP, A2A, and more) as
opinionated packagings of ideas you have already implemented yourself. The whole
course runs live models throughout, and every chapter works the same micro-world:
Larkspur Outfitters, a small online outdoor-gear shop seen from its ops desk.

**Status:** under construction — chapters land phase by phase on the open PR.
The full README, with the curriculum table, arrives in the final phase.

## Setup

Requires Python >= 3.12.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[obs]"
cp .env.example .env    # then add your OPENROUTER_API_KEY
jupyter lab
```

One key is required: `OPENROUTER_API_KEY` — the default models route through
OpenRouter, and any LiteLLM provider string works in `MODEL` / `STRONG_MODEL`.
The `.env` contract is identical to the sibling course
[dspy-lab](https://github.com/sinaghadermarzi/dspy-lab), so one `.env` file can
serve both repos.
