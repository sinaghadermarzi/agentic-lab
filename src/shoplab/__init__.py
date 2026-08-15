"""shoplab: the shared machinery behind agentic-lab, a hands-on Jupyter course on
agentic systems set in the Larkspur Outfitters micro-world (see docs/WORLD.md).

Submodules so far:

- ``world`` -- data loading for the micro-world plus ``search_policy``
- ``rules`` -- the normative refund-decision cascade (``decide``)
- ``llm`` -- the one door to the model: ``complete``/``llm``, the cost
  ``LEDGER``, and ``parse_json_loose``
- ``tools`` -- ``Tool``/``Ledger``, safe ``calc``, and the 9 standard tools
  (``standard_tools``, ``run_tool``, ``to_openai_tools``)
- ``loop`` -- the tool-calling agent loop (``run_agent`` -> ``AgentResult``)
- ``trace`` -- hand-rolled spans, trace trees, and OTLP export (``Tracer``)
- ``evals`` -- ticket scoring and the run/compare harness (``score_ticket``)

# Later chapters add more submodules (controls, context, ...).

No submodule is imported here: ``import shoplab`` stays cheap and
dependency-free, and each submodule is imported explicitly where needed.
"""
