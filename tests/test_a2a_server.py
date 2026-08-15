"""Offline checks for the Northwind Supply A2A server (chapter 14).

No network and no running server: everything here is about the objects the
factory builds and the deterministic quoting logic. The end-to-end lifecycle
(card resolution over HTTP, the input-required multi-turn flow) is exercised live
in the chapter notebook, not in this suite.
"""

import sys
from pathlib import Path

# The server package lives at the repo root (a2a_servers/), alongside src/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from a2a.types import AgentCard, AgentSkill
from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH, TransportProtocol

from a2a_servers import supplier_agent as sa
from shoplab import world


def test_well_known_path_is_the_spec_path():
    # Guards against SDK drift: the A2A spec mandates this exact path.
    assert AGENT_CARD_WELL_KNOWN_PATH == "/.well-known/agent-card.json"


def test_agent_card_has_required_fields():
    card = sa.build_agent_card("http://127.0.0.1:9999")
    assert isinstance(card, AgentCard)
    assert card.name and card.description and card.version
    assert card.default_input_modes and card.default_output_modes
    # At least one skill, well-formed.
    assert len(card.skills) >= 1
    skill = card.skills[0]
    assert isinstance(skill, AgentSkill)
    assert skill.id and skill.name and skill.description
    assert len(skill.tags) >= 1
    assert len(skill.examples) >= 1


def test_agent_card_advertises_jsonrpc_interface_at_given_url():
    card = sa.build_agent_card("http://127.0.0.1:9999")
    assert len(card.supported_interfaces) >= 1
    iface = card.supported_interfaces[0]
    assert iface.protocol_binding == TransportProtocol.JSONRPC
    assert iface.url == "http://127.0.0.1:9999/"


def test_create_server_registers_well_known_and_rpc_routes():
    app = sa.create_server(host="127.0.0.1", port=9999)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert AGENT_CARD_WELL_KNOWN_PATH in paths
    assert "/" in paths          # JSON-RPC endpoint


def test_valid_skus_match_the_catalog():
    assert sa._valid_skus() == {p["sku"] for p in world.load_products()}


def test_quote_is_deterministic():
    a = sa.quote("LK-1007", "west")
    b = sa.quote("LK-1007", "west")
    assert a == b
    # Region shifts only the lead time, never price or availability.
    east = sa.quote("LK-1007", "east")
    assert east["wholesale_price_usd"] == a["wholesale_price_usd"]
    assert east["available_units"] == a["available_units"]
    assert east["lead_time_business_days"] > a["lead_time_business_days"]


def test_quote_fields_and_math():
    q = sa.quote("lk-1007", "West")   # case-insensitive inputs
    prod = next(p for p in world.load_products() if p["sku"] == "LK-1007")
    assert q["sku"] == "LK-1007"
    assert q["region"] == "west"
    assert q["wholesale_price_usd"] == round(prod["price_usd"] * 0.60, 2)
    assert q["lead_time_business_days"] > 0
    assert q["available_units"] >= 0
    assert q["backordered"] == (q["available_units"] == 0)


def test_quote_rejects_bad_inputs():
    with pytest.raises(ValueError):
        sa.quote("LK-9999", "west")     # not a Larkspur SKU
    with pytest.raises(ValueError):
        sa.quote("LK-1007", "north")    # not a real warehouse region


def test_parse_request_extracts_sku_and_region():
    sku, region = sa._parse_request("lead time for LK-1007 in the west warehouse")
    assert sku == "LK-1007"
    assert region == "west"


def test_parse_request_ambiguous_when_region_missing():
    sku, region = sa._parse_request("What's the restock lead time for LK-1015?")
    assert sku == "LK-1015"
    assert region is None            # -> triggers the input-required branch


def test_parse_request_rejects_unknown_sku():
    sku, region = sa._parse_request("restock LK-8888 please, west warehouse")
    assert sku is None               # not in the catalog
    assert region == "west"


def test_format_quote_mentions_key_facts():
    text = sa.format_quote(sa.quote("LK-1007", "west"))
    assert "LK-1007" in text
    assert "west" in text
    assert "business days" in text
