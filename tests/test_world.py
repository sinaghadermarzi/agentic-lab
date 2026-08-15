"""Loaders return the right shapes; search_policy behaves as a retriever should."""

from shoplab import world


def test_load_products():
    products = world.load_products()
    assert isinstance(products, list) and len(products) == 30
    assert all(isinstance(p, dict) and "sku" in p and "price_usd" in p for p in products)


def test_load_customers():
    customers = world.load_customers()
    assert isinstance(customers, list) and len(customers) == 15
    assert all(isinstance(c, dict) and "customer_id" in c and "tier" in c for c in customers)


def test_load_orders():
    orders = world.load_orders()
    assert isinstance(orders, list) and len(orders) == 40
    assert all(isinstance(o, dict) and isinstance(o["items"], list) for o in orders)


def test_load_policies():
    policies = world.load_policies()
    assert isinstance(policies, list) and len(policies) == 12
    assert all(set(p) == {"id", "title", "text"} for p in policies)


def test_load_tickets():
    tickets = world.load_tickets()
    assert isinstance(tickets, dict)
    assert len(tickets["train"]) == 20
    assert len(tickets["dev"]) == 12
    assert len(tickets["test"]) == 8


def test_load_injections():
    injections = world.load_injections()
    assert isinstance(injections, list) and len(injections) == 10
    assert all(isinstance(i, dict) and "is_attack" in i for i in injections)


def test_search_policy_returns_k_dicts():
    hits = world.search_policy("refund", k=2)
    assert len(hits) == 2
    for hit in hits:
        assert set(hit) == {"id", "title", "text", "score"}
        assert isinstance(hit["score"], float)


def test_search_policy_obvious_query_ranks_return_policy():
    hits = world.search_policy("refund for opened box", k=2)
    top2 = {h["id"] for h in hits}
    assert top2 & {"pol-restocking", "pol-returns"}


def test_search_policy_respects_k():
    assert len(world.search_policy("refund", k=1)) == 1
    assert len(world.search_policy("refund", k=5)) == 5
    assert len(world.search_policy("refund", k=12)) == 12


def test_search_policy_unknown_words_no_crash():
    hits = world.search_policy("zxqvwm flibberty ungrokkable", k=2)
    assert len(hits) == 2
    assert all("id" in h for h in hits)
    assert all(h["score"] == 0.0 for h in hits)
