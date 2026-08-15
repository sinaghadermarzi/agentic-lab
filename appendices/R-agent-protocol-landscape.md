# Reference — the agent-protocol landscape

A sourced map of the protocols an agent speaks. These are **layers of one stack, not rival choices**: each standardizes a different edge of an agent system — its tools, its peer agents, its user interface, its payment rails, its identity and discovery. Reading them as competitors is a category error; a real deployment speaks several at once. The AP2 docs put the whole stack in one line — "Build agents with ADK (or any framework), equip with MCP (or any tool), collaborate via A2A, and use AP2 to secure payments" ([ap2-protocol.org](https://ap2-protocol.org/)).

Every claim below links to a primary source registered in `docs/citations.json`. The course builds two of these by hand: **MCP** in [ch13](../13-mcp.ipynb) and **A2A** in [ch14](../14-a2a.ipynb).

| Protocol | Layer | One line | Source |
|---|---|---|---|
| MCP | agent <-> tools/data | JSON-RPC vocabulary exposing tools, resources, and prompts to a model | [spec](https://modelcontextprotocol.io/specification/2026-07-28) |
| A2A | agent <-> agent | peers discover each other by an Agent Card and exchange tasks | [spec](https://a2a-protocol.org/v1.0.0/specification/) |
| AG-UI | agent <-> user/UI | event stream connecting an agent to a user-facing app | [docs](https://docs.ag-ui.com/introduction) |
| AP2 | agent <-> payments | agents pay on a user's behalf with verifiable, signed authorization | [docs](https://ap2-protocol.org/) |
| AGNTCY | agent <-> agent (infra) | open "Internet of Agents" stack: discovery, identity, messaging, observability | [docs](https://agntcy.org/) |
| ANP | agent <-> agent (decentralized) | decentralized identity, discovery, and messaging for an "Agentic Web" | [docs](https://agent-network-protocol.com/) |
| Agent Client Protocol (Zed) | editor/IDE <-> agent | standard way for a code editor to drive a coding agent | [docs](https://agentclientprotocol.com/get-started/introduction) |

The rows overlap deliberately: MCP points **down** to tools, AG-UI points **up** to the user, A2A points **sideways** to peers, and AP2 rides on top for money. AGNTCY and ANP occupy the same agent-to-agent layer as A2A but lead with identity and discovery — the sideways layer has more than one bet in flight.

## MCP — Model Context Protocol (agent to tools)

The problem: a model needs a uniform way to reach external tools, data, and prompt templates without a bespoke integration per source. MCP answers it as JSON-RPC with an agreed vocabulary — a server exposes "Resources ... Prompts ... [and] Tools" to clients ([2026-07-28 spec](https://modelcontextprotocol.io/specification/2026-07-28)). Concrete detail: tool-execution failures are *not* protocol errors — a tool that ran and failed comes back inside the result with `isError: true` ("reported in tool results with `isError: true`", [tools spec](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)), so the model reads the failure as data and can recover. Backed by an open specification (modelcontextprotocol.io); the course builds the wire format by hand — the `initialize` handshake, `tools/list`, `tools/call` — in [ch13](../13-mcp.ipynb).

## A2A — Agent2Agent (agent to agent)

The problem: one organization's agent needs to call another's as a **peer** over the wire — with discovery, a task lifecycle, and streamed status — not as a local tool. Concrete detail: a peer publishes an Agent Card at the fixed well-known path `https://{server_domain}/.well-known/agent-card.json` ([spec](https://a2a-protocol.org/v1.0.0/specification/)), and a task can pause in the `input-required` state to "request additional input mid-processing" before resuming ([spec](https://a2a-protocol.org/v1.0.0/specification/)). History to know: IBM's **Agent Communication Protocol (ACP)** is "officially merging with the A2A under the Linux Foundation" (announced 2025-08-29, [LF AI & Data](https://lfaidata.foundation/communityblog/2025/08/29/acp-joins-forces-with-a2a-under-the-linux-foundations-lf-ai-data/)) — two efforts folded into one governed standard, which is why the field is consolidating on A2A. Official Python SDK: `a2a-sdk` ([a2a-python](https://github.com/a2aproject/a2a-python)). Built by hand in [ch14](../14-a2a.ipynb).

## AG-UI — Agent User Interaction Protocol (agent to user/UI)

The problem: wiring an agent's run into a front end — streaming messages, tool-call status, state, and interrupts — gets re-invented per app. AG-UI is "an open, lightweight, event-based protocol that standardizes how AI agents connect to user-facing applications" ([docs](https://docs.ag-ui.com/introduction)). Concrete detail: it is **event-based** — instead of one request/response call, a standardized stream of typed events flows from agent to app. Backed by the open-source AG-UI project (`ag-ui-protocol`). It is the "up" edge that MCP and A2A do not cover.

## AP2 — Agent Payments Protocol (agent payments)

The problem: when an agent transacts, the merchant and payment network need cryptographic proof the agent was authorized by the user for *that* purchase. AP2 targets "gen AI agents to make payments on behalf of users, safely, securely, and in a decentralized and privacy protecting manner" ([docs](https://ap2-protocol.org/)). Concrete detail: it is built on **Verifiable Digital Credentials (VDCs)** and signed **Mandates** (a Checkout Mandate and a Payment Mandate), and ships as an extension of the A2A protocol ([ap2-protocol.org](https://ap2-protocol.org/)). Led by Google, with payments-industry partners (the site notes a FIDO Alliance donation). This is the layer that turns "an agent did something" into "an agent paid for something, provably."

## AGNTCY — Internet of Agents (agent identity and discovery)

The problem: cross-vendor, cross-framework agent collaboration needs shared plumbing — discovery, identity, messaging, observability — rather than N-by-N point integrations. AGNTCY "delivers an open-source stack enabling AI agents to collaborate across vendors and frameworks through discovery, identity, messaging, and observability" ([docs](https://agntcy.org/)). Concrete detail: named components include an **Agent Directory** (a "federated registry for cross-framework, cross-protocol, cross-registry agent discovery"), **SLIM** (secure network-level agent messaging), **Identity**, and **Observability** ([agntcy.org](https://agntcy.org/)). Backed by the Linux Foundation — the site is "a Series of LF Projects, LLC." Same sideways layer as A2A, but its bet is the registry-and-identity substrate under it.

## ANP — Agent Network Protocol (decentralized agent network)

The problem: an open, **decentralized** alternative for agents to identify, discover, and message each other across domains without a central broker. ANP is "an open-source agent communication protocol designed for secure, decentralized communication between AI agents" ([docs](https://agent-network-protocol.com/)). Concrete detail: identity is decentralized — `did:wba` (a W3C Decentralized Identifier method) and WNS "provide verifiable agent identity, readable handles, and cross-domain trust roots," layered under description, discovery, and messaging protocols for an "Agentic Web" ([agent-network-protocol.com](https://agent-network-protocol.com/)). Backed by the open-source Agent Network Protocol project. It overlaps A2A/AGNTCY on the agent-to-agent layer but leads with decentralized identity rather than a hosted registry.

## Agent Client Protocol — Zed (editor/IDE to agent)

The problem: coding agents and editors are tightly coupled but not interoperable — every editor builds a custom integration for every agent, and every agent implements editor-specific APIs. Zed's Agent Client Protocol (ACP) "standardizes communication between code editors/IDEs and coding agents and is suitable for both local and remote scenarios" ([docs](https://agentclientprotocol.com/get-started/introduction)). Concrete detail: it is positioned as the LSP of agent-editor integration — "similar to how the Language Server Protocol (LSP) standardized language server" support, so any editor works with any agent ([agentclientprotocol.com](https://agentclientprotocol.com/get-started/introduction)). Backed by Zed Industries (with JetBrains among the implementers).

**Name-collision warning:** this "ACP" is *not* IBM's Agent Communication Protocol. IBM's ACP merged into A2A (see above, [LF AI & Data](https://lfaidata.foundation/communityblog/2025/08/29/acp-joins-forces-with-a2a-under-the-linux-foundations-lf-ai-data/)); Zed's ACP is an unrelated editor-to-agent protocol. Same three letters, different problem, different layer.

## Reading the map

If you built the course's ch13 MCP loop and ch14 A2A peer, you already have the two load-bearing layers. AG-UI is the same idea aimed at the human; AP2 is the same idea aimed at money; AGNTCY and ANP are the same idea aimed at identity and discovery at internet scale. None replaces MCP or A2A — they stack. Pick by the edge you are standardizing, not by picking a winner.
