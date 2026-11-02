# pi_lab — chapter 19's TypeScript side

The Node half of [`19-pi.ipynb`](../19-pi.ipynb): pi 1.4.0 (`@earendil-works/pi-ai`,
`pi-agent-core`, `pi-coding-agent`), pinned exactly, driving the Larkspur desk through the Python
desk bridge (`shoplab.bridge.DeskBridge`).

```bash
npm ci --prefix pi_lab           # once; needs Node.js >= 22.19. Nothing global, nothing in ~/.pi
npm run typecheck --prefix pi_lab  # optional: tsc over every file here
```

| File | Layer | What it shows |
|---|---|---|
| `desk.ts` | shared | the desk model as data, its provider config, and the desk tools fetched from the bridge's tool door |
| `models.ts` | 1, pi-ai | a `Models` collection with one provider (the bridge) |
| `01-stream.ts` | 1, pi-ai | one `models.stream()` call with one tool, event by event |
| `02-agent-loop.ts` | 2, pi-agent-core | the ticket through `agentLoop` |
| `03-hooks.ts` | 2, pi-agent-core | `beforeToolCall` gate, `afterToolCall` quarantine, `finishTurn` budget |
| `04-session.ts` | 3, the harness SDK | a file-backed `AgentSession`, closed, reopened, resumed |
| `extensions/larkspur.ts` | 4, extensions | the desk as a pi extension: provider, tools, gate, quarantine, budget |

Every script prints one JSON object per line on stdout; `shoplab.pi` reads them. The scripts are
plain TypeScript for Node's built-in type stripping (no build step): type-only imports use
`import type`, and nothing uses enums or namespaces (`erasableSyntaxOnly` in `tsconfig.json`).

Each script expects `DESK_URL` (the bridge) and, for the harness layers, `PI_CODING_AGENT_DIR`
(an isolated config dir). The notebook sets both through `shoplab.pi`, and runs the CLI with
`shoplab.pi.ISOLATION_FLAGS` so pi sees the desk and nothing else. The code blocks the chapter shows
are the `// >>> pi_lab.<name>` regions of these files; `scripts/validate_notebooks.py` fails if
they drift.
