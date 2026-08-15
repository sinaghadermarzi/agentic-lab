"""shoplab: the shared machinery behind agentic-lab, a hands-on Jupyter course on
agentic systems set in the Larkspur Outfitters micro-world (see docs/WORLD.md).

Submodules so far:

- ``world`` -- data loading for the micro-world plus ``search_policy``
- ``rules`` -- the normative refund-decision cascade (``decide``)

# Later chapters add more submodules (llm, loop, trace, evals, tools, ...).

No submodule is imported here: ``import shoplab`` stays cheap and
dependency-free, and each submodule is imported explicitly where needed.
"""
