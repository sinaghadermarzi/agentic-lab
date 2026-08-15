"""Northwind Supply: an A2A peer-agent server for chapter 14.

Larkspur Outfitters (our micro-world; see ``docs/WORLD.md``) is a retailer, not a
manufacturer. When stock runs low the ops desk has to ask a *supplier* -- a
separate organization -- how fast it can restock a SKU and at what wholesale
price. That supplier is a different company running its own agent, so we cannot
call it as a local Python tool the way ``shoplab.tools`` are called. We reach it
over the wire with the **Agent2Agent (A2A) protocol**: the supplier publishes an
Agent Card at a well-known URL, and Larkspur speaks JSON-RPC to it.

This module is that supplier. "Northwind Supply" is a fictional wholesaler whose
one skill is quoting restock lead times and wholesale availability for a Larkspur
SKU. It is deliberately small but protocol-complete:

- It serves its **Agent Card** at ``/.well-known/agent-card.json`` (the exact
  well-known path the A2A v1.0.0 spec mandates -- see ``docs/citations.json``).
- It implements the A2A **task lifecycle** (submitted -> working -> completed).
- It supports a **multi-turn ``input-required`` flow**: a SKU can be stocked in
  more than one regional warehouse, so if the caller does not say *which* region
  the agent parks the task in ``INPUT_REQUIRED`` and asks; the caller's follow-up
  message resumes the same task and drives it to ``COMPLETED``.

Every number it quotes is **deterministic** -- derived arithmetically from the
SKU (no randomness, no model call) -- so the chapter's assertions are stable and
reruns are free. The catalog of valid SKUs comes from ``shoplab.world`` so the
supplier and the retailer always agree on what exists.

The a2a-sdk (1.1.x) shipped here is the protobuf-typed v1.x line: ``AgentCard``,
``AgentSkill``, ``Message`` etc. are protobuf messages and ``TaskState`` is a
protobuf enum whose members are spelled ``TASK_STATE_INPUT_REQUIRED`` and so on.

Run it directly for a manual smoke test::

    python -m a2a_servers.supplier_agent            # picks a free port, prints URL

Inside a notebook, never call ``serve()`` in a cell (it blocks forever). Use the
``serve_in_background`` context manager instead -- it runs uvicorn in a daemon
thread and tears the server down when the ``with`` block exits::

    with serve_in_background() as base_url:
        ...  # talk to base_url; server is guaranteed stopped after this block
"""

from __future__ import annotations

import contextlib
import re
import socket
import threading
import time

import uvicorn
from starlette.applications import Starlette

from a2a.helpers import get_message_text, new_task, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    TaskState,
)
from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH, TransportProtocol

import shoplab.world as world

# --- domain: what Northwind Supply knows -------------------------------------

#: The three regional warehouses Northwind ships from. If a caller does not name
#: one, the request is ambiguous and the agent must ask (the input-required arm).
REGIONS = ("west", "central", "east")

#: Each region adds a fixed number of business days to the base lead time.
_REGION_LEAD_OFFSET = {"west": 0, "central": 1, "east": 3}

_SKU_RE = re.compile(r"\bLK-\d{4}\b", re.IGNORECASE)


def _valid_skus() -> set[str]:
    """The SKUs Northwind will quote -- exactly Larkspur's catalog."""
    return {p["sku"] for p in world.load_products()}


def _product(sku: str) -> dict | None:
    for p in world.load_products():
        if p["sku"] == sku:
            return p
    return None


def _sku_number(sku: str) -> int:
    """``LK-1007`` -> ``1007`` -- the seed for all deterministic quoting."""
    return int(sku.split("-", 1)[1])


def quote(sku: str, region: str) -> dict:
    """A fully deterministic restock quote for ``sku`` from ``region``.

    No randomness and no model call: every field is arithmetic over the SKU
    number and the product's own catalog price, so the same inputs always yield
    the same quote. ``available_units == 0`` means the item is backordered, which
    stretches the lead time.
    """
    sku = sku.upper()
    region = region.lower()
    product = _product(sku)
    if product is None:
        raise ValueError(f"{sku} is not a Larkspur SKU")
    if region not in _REGION_LEAD_OFFSET:
        raise ValueError(f"{region!r} is not one of {REGIONS}")

    n = _sku_number(sku)
    base_lead = 3 + (n % 12)                      # 3..14 business days
    available = (n * 37) % 200                    # 0..199 units; 0 == backordered
    backordered = available == 0
    lead_days = base_lead + _REGION_LEAD_OFFSET[region] + (14 if backordered else 0)
    wholesale = round(product["price_usd"] * 0.60, 2)

    return {
        "sku": sku,
        "name": product["name"],
        "region": region,
        "wholesale_price_usd": wholesale,
        "available_units": available,
        "backordered": backordered,
        "lead_time_business_days": lead_days,
    }


def format_quote(q: dict) -> str:
    """Render a quote dict as the human-readable answer Larkspur receives."""
    tail = (
        "currently backordered, so the lead time already includes the restock wait"
        if q["backordered"]
        else f"{q['available_units']} units available to ship now"
    )
    return (
        f"Northwind Supply restock quote for {q['sku']} ({q['name']}) from our "
        f"{q['region']} warehouse: wholesale ${q['wholesale_price_usd']:.2f}/unit, "
        f"{tail}, restock lead time {q['lead_time_business_days']} business days."
    )


def _parse_request(text: str) -> tuple[str | None, str | None]:
    """Pull a valid SKU and (optionally) a region out of free-text.

    Returns ``(sku_or_None, region_or_None)``. ``sku`` is upper-cased and checked
    against the live catalog; an unknown SKU comes back as ``None``.
    """
    sku = None
    m = _SKU_RE.search(text or "")
    if m:
        candidate = m.group(0).upper()
        if candidate in _valid_skus():
            sku = candidate
    region = None
    lowered = (text or "").lower()
    for r in REGIONS:
        if re.search(rf"\b{r}\b", lowered):
            region = r
            break
    return sku, region


# --- the A2A agent ------------------------------------------------------------


class SupplierAgentExecutor(AgentExecutor):
    """Core logic wired into the A2A task lifecycle.

    The executor sees one request at a time. ``context.get_user_input()`` is the
    latest inbound message; ``context.current_task`` is the task so far (present
    only when the caller is *resuming* an input-required task). We reconstruct
    the full picture -- SKU and region -- from the whole conversation, because the
    SKU usually arrives in the first message and the region in the follow-up.
    """

    def _gather_text(self, context: RequestContext) -> str:
        """All caller-supplied text: this message plus any prior history."""
        parts = [context.get_user_input()]
        task = context.current_task
        if task is not None:
            for msg in task.history:
                parts.append(get_message_text(msg))
        return "\n".join(p for p in parts if p)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if context.current_task is None:
            # First turn: the Task object itself must reach the queue before any
            # status-update event, or the framework rejects the response. Seed its
            # history with this inbound message -- once we enqueue the Task
            # ourselves the framework stops auto-saving it, and we need it later so
            # a resumed (input-required) turn can recover the SKU from the first
            # message.
            await event_queue.enqueue_event(
                new_task(context.task_id, context.context_id,
                         TaskState.TASK_STATE_SUBMITTED,     # -> TASK_STATE_SUBMITTED
                         history=[context.message])
            )
        await updater.start_work()          # -> TASK_STATE_WORKING

        sku, region = _parse_request(self._gather_text(context))

        if sku is None:
            # Nothing we can price. Finish the task; the caller can start a new one.
            await updater.complete(
                updater.new_agent_message([
                    new_text_part(
                        "I could not find a valid Larkspur SKU (like LK-1007) in "
                        "your request. Northwind Supply only quotes Larkspur "
                        "catalog SKUs. Please resend with the SKU."
                    )
                ])
            )
            return

        if region is None:
            # Ambiguous: the SKU may be stocked in more than one warehouse. Park
            # the task and ask -- the caller's next message resumes this task.
            await updater.requires_input(       # -> TASK_STATE_INPUT_REQUIRED
                updater.new_agent_message([
                    new_text_part(
                        f"{sku} is stocked in more than one Northwind warehouse. "
                        f"Which region should I quote -- {', '.join(REGIONS)}?"
                    )
                ])
            )
            return

        answer = format_quote(quote(sku, region))
        await updater.complete(                 # -> TASK_STATE_COMPLETED
            updater.new_agent_message([new_text_part(answer)])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


# --- Agent Card + server assembly --------------------------------------------

SUPPLIER_SKILL = AgentSkill(
    id="restock_quote",
    name="Restock lead time & wholesale availability",
    description=(
        "Given a Larkspur SKU, quote Northwind Supply's wholesale price, "
        "on-hand availability, and restock lead time. If the warehouse region "
        "is unspecified, the agent asks which region before quoting."
    ),
    tags=["supply-chain", "wholesale", "restock", "b2b"],
    examples=[
        "What's the restock lead time for LK-1007?",
        "Wholesale availability of LK-1015 from the west warehouse?",
    ],
)


def build_agent_card(base_url: str) -> AgentCard:
    """The Agent Card served at the well-known path.

    ``base_url`` is where this server is actually reachable (e.g.
    ``http://127.0.0.1:53017``); the JSON-RPC transport interface advertised in
    the card must point at it so a client that reads the card knows where to POST.
    """
    rpc_url = base_url.rstrip("/") + "/"
    return AgentCard(
        name="Northwind Supply",
        description=(
            "Wholesale supplier agent for Larkspur Outfitters: restock lead times "
            "and wholesale availability for catalog SKUs, quoted per warehouse "
            "region."
        ),
        version="1.0.0",
        provider=AgentProvider(
            organization="Northwind Supply Co.",
            url="https://northwind.example.com",
        ),
        supported_interfaces=[
            AgentInterface(
                url=rpc_url,
                protocol_binding=TransportProtocol.JSONRPC,
                protocol_version="1.0",
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[SUPPLIER_SKILL],
    )


def create_server(host: str = "127.0.0.1", port: int = 8080) -> Starlette:
    """Build the Starlette app for Northwind Supply bound to ``host:port``.

    The card's advertised URL is baked from ``host``/``port``, so pass the same
    values you hand uvicorn. Returns a plain ASGI app -- the caller runs it
    (``uvicorn.run`` for a script, or ``serve_in_background`` for a notebook).
    """
    base_url = f"http://{host}:{port}"
    card = build_agent_card(base_url)
    handler = DefaultRequestHandler(
        agent_executor=SupplierAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_agent_card_routes(agent_card=card, card_url=AGENT_CARD_WELL_KNOWN_PATH)
    routes += create_jsonrpc_routes(request_handler=handler, rpc_url="/")
    return Starlette(routes=routes)


def free_port() -> int:
    """Ask the OS for an unused TCP port (bind to 0, read it back, release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def serve_in_background(host: str = "127.0.0.1", port: int | None = None,
                        ready_timeout: float = 10.0):
    """Run the server in a uvicorn daemon thread; guarantee teardown on exit.

    Yields the ``base_url`` once the server reports started. On leaving the
    ``with`` block the server is signalled to stop and the thread is joined, so a
    notebook cell can never hang on a live server or leave the port bound. Pick a
    free port automatically when ``port`` is ``None``.
    """
    if port is None:
        port = free_port()
    app = create_server(host=host, port=port)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + ready_timeout
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError(f"server did not start within {ready_timeout}s")

    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def serve(host: str = "127.0.0.1", port: int | None = None) -> None:
    """Blocking foreground serve -- for ``__main__`` / a terminal, never a cell."""
    if port is None:
        port = free_port()
    print(f"Northwind Supply A2A server on http://{host}:{port}")
    print(f"Agent Card: http://{host}:{port}{AGENT_CARD_WELL_KNOWN_PATH}")
    uvicorn.run(create_server(host=host, port=port), host=host, port=port,
                log_level="info")


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Northwind Supply A2A server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int,
                        default=int(os.environ["A2A_PORT"]) if os.environ.get("A2A_PORT") else None)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
