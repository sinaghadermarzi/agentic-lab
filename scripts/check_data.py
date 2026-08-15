#!/usr/bin/env python3
"""Integrity checks for the Larkspur Outfitters micro-world (data/*.json).

Run from the repo root:  python3 scripts/check_data.py

docs/WORLD.md is normative: the data files, shoplab/rules.py, and this script
must agree exactly. Checks accumulate into a failures list and each group
prints a PASS/FAIL line; any failure exits 1. INFO lines are diagnostics
(price spread, decisions by split, retrieval hit rates), not checks.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shoplab.rules import decide          # noqa: E402
from shoplab.world import search_policy   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

failures = []
_group_start = 0


def hard(cond, msg):
    if not cond:
        failures.append(msg)


def group(name):
    """Print PASS/FAIL for every hard() since the previous group() call."""
    global _group_start
    fresh = failures[_group_start:]
    print(f"{'FAIL' if fresh else 'PASS'} {name}"
          + (f" ({len(fresh)} failure{'s' if len(fresh) > 1 else ''})" if fresh else ""))
    _group_start = len(failures)


# --- file presence + JSON validity -------------------------------------------
FILES = ["products.json", "customers.json", "orders.json", "policies.json",
         "tickets.json", "injections.json"]
loaded = {}
for name in FILES:
    path = DATA / name
    if not path.exists():
        hard(False, f"{name} missing from data/")
        continue
    try:
        loaded[name] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        hard(False, f"{name} is not valid JSON: {e}")
group("files present and valid JSON")
if failures:  # nothing else can run without the data
    print("\nFAILURES:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)

products = loaded["products.json"]
customers = loaded["customers.json"]
orders = loaded["orders.json"]
policies = loaded["policies.json"]
tickets = loaded["tickets.json"]
injections = loaded["injections.json"]

# --- products ----------------------------------------------------------------
CATEGORIES = {"apparel", "camp", "hydration", "footwear", "accessories"}
hard(len(products) == 30, f"products: {len(products)} rows, expected 30")
skus = [p["sku"] for p in products]
hard(skus == [f"LK-{n}" for n in range(1001, 1031)],
     "products: skus are not the sequential LK-1001..LK-1030")
for p in products:
    hard(p["category"] in CATEGORIES, f"{p['sku']}: bad category {p['category']!r}")
    hard(round(p["price_usd"], 2) == p["price_usd"],
         f"{p['sku']}: price {p['price_usd']} not two decimals")
    hard(8 <= p["price_usd"] <= 420,
         f"{p['sku']}: price {p['price_usd']} outside the $8-$420 spread")
hard({p["category"] for p in products} == CATEGORIES,
     "products: not all five categories are used")
low_stock = [p["sku"] for p in products if p["stock"] <= p["reorder_threshold"]]
hard(len(low_stock) == 3, f"products: {len(low_stock)} low-stock, expected 3 ({low_stock})")
hazmat = [p["sku"] for p in products if p["hazmat"]]
hard(len(hazmat) == 2, f"products: {len(hazmat)} hazmat, expected 2 ({hazmat})")
group("products (30 rows, ids, categories, prices, 3 low-stock, 2 hazmat)")

# --- customers ---------------------------------------------------------------
hard(len(customers) == 15, f"customers: {len(customers)} rows, expected 15")
cids = [c["customer_id"] for c in customers]
hard(cids == [f"CUST-{n:02d}" for n in range(1, 16)],
     "customers: ids are not the sequential CUST-01..CUST-15")
tiers = {}
for c in customers:
    tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    hard(c["email"].endswith("@example.com"),
         f"{c['customer_id']}: email does not end @example.com")
hard(tiers == {"vip": 3, "member": 5, "standard": 7},
     f"customers: tier counts {tiers}, expected 3 vip / 5 member / 7 standard")
returners = [c for c in customers if c["serial_returner"]]
hard(len(returners) == 2,
     f"customers: {len(returners)} serial returners, expected 2")
hard(sorted(c["tier"] for c in returners) == ["member", "standard"],
     "customers: serial returners must be one standard and one member (never vip)")
group("customers (15 rows, ids, tiers 3/5/7, 2 serial returners, emails)")

# --- orders ------------------------------------------------------------------
price_by_sku = {p["sku"]: p["price_usd"] for p in products}
SHIPPING = {0.00, 5.95, 12.50, 24.00}
CARRIERS = {"Cascadia Post", "Bluebird Express", "TruckIt"}
COUNTRIES = {"US", "CA", "DE", "JP", "AU"}
DATE_LO, DATE_HI = date(2026, 6, 1), date(2026, 8, 31)

hard(len(orders) == 40, f"orders: {len(orders)} rows, expected 40")
oids = [o["order_id"] for o in orders]
hard(oids == [f"ORD-{n}" for n in range(7301, 7341)],
     "orders: ids are not the sequential ORD-7301..ORD-7340")
status_counts = {}
for o in orders:
    oid = o["order_id"]
    status_counts[o["status"]] = status_counts.get(o["status"], 0) + 1
    hard(1 <= len(o["items"]) <= 3, f"{oid}: {len(o['items'])} items, expected 1-3")
    for item in o["items"]:
        hard(1 <= item["qty"] <= 3, f"{oid}: qty {item['qty']} outside 1-3")
        hard(item["unit_price_usd"] == price_by_sku.get(item["sku"]),
             f"{oid}: {item['sku']} unit_price {item['unit_price_usd']} != "
             f"catalog price {price_by_sku.get(item['sku'])}")
    computed = round(sum(i["qty"] * i["unit_price_usd"] for i in o["items"])
                     + o["shipping_usd"], 2)
    hard(computed == round(o["total_usd"], 2),
         f"{oid}: total {o['total_usd']} != items+shipping {computed}")
    hard(o["shipping_usd"] in SHIPPING, f"{oid}: bad shipping {o['shipping_usd']}")
    hard(o["carrier"] in CARRIERS, f"{oid}: bad carrier {o['carrier']!r}")
    hard(o["destination_country"] in COUNTRIES,
         f"{oid}: bad destination {o['destination_country']!r}")
    needs_delivery = o["status"] in ("delivered", "returned", "refunded")
    hard(("delivered_at" in o) == needs_delivery,
         f"{oid}: delivered_at present iff delivered/returned/refunded "
         f"(status {o['status']!r})")
    placed = date.fromisoformat(o["placed_at"])
    hard(DATE_LO <= placed <= DATE_HI, f"{oid}: placed_at {o['placed_at']} not Jun-Aug 2026")
    if "delivered_at" in o:
        delivered = date.fromisoformat(o["delivered_at"])
        hard(DATE_LO <= delivered <= DATE_HI,
             f"{oid}: delivered_at {o['delivered_at']} not Jun-Aug 2026")
        hard(placed <= delivered, f"{oid}: placed_at after delivered_at")
hard(status_counts == {"delivered": 30, "shipped": 3, "placed": 3,
                       "returned": 2, "refunded": 1, "cancelled": 1},
     f"orders: status counts {status_counts}, expected 30/3/3/2/1/1")
intl = sum(1 for o in orders if o["destination_country"] != "US")
hard(4 <= intl <= 5, f"orders: {intl} international, expected 4-5")
group("orders (40 rows, ids, arithmetic, prices, statuses, dates)")

# --- policies ----------------------------------------------------------------
EXPECTED_POLICIES = [
    ("pol-returns", "Returns Window"),
    ("pol-restocking", "Refund Method & Restocking Fee"),
    ("pol-damaged", "Damaged in Transit"),
    ("pol-defective", "Defective Items & Warranty"),
    ("pol-exchanges", "Exchanges & Replacements"),
    ("pol-store-credit", "Store Credit"),
    ("pol-shipping", "Shipping & Carriers"),
    ("pol-international", "International Returns"),
    ("pol-hazmat", "Battery & Hazmat Shipping"),
    ("pol-loyalty", "Loyalty Tiers"),
    ("pol-fraud", "Fraud & Abuse Escalation"),
    ("pol-price-adjust", "Price Adjustments"),
]
hard(len(policies) == 12, f"policies: {len(policies)} docs, expected 12")
hard([(p["id"], p["title"]) for p in policies] == EXPECTED_POLICIES,
     "policies: ids/titles do not match the fixed list in docs/WORLD.md")
for p in policies:
    n_words = len(p["text"].split())
    hard(n_words <= 180, f"{p['id']}: text is {n_words} words, max 180")
group("policies (12 docs, exact ids and titles, <= 180 words)")

# --- tickets: splits, ids, referential integrity -----------------------------
SPLIT_RANGES = {"train": (2201, 2220), "dev": (2221, 2232), "test": (2233, 2240)}
splits = {name: tickets.get(name, []) for name in SPLIT_RANGES}
all_tickets = [(name, t) for name, rows in splits.items() for t in rows]
hard(len(splits["train"]) == 20, f"train split has {len(splits['train'])}, expected 20")
hard(len(splits["dev"]) == 12, f"dev split has {len(splits['dev'])}, expected 12")
hard(len(splits["test"]) == 8, f"test split has {len(splits['test'])}, expected 8")
for name, (lo, hi) in SPLIT_RANGES.items():
    got = [t["ticket_id"] for t in splits[name]]
    hard(got == [f"TKT-{n}" for n in range(lo, hi + 1)],
         f"{name}: ticket ids are not the sequential TKT-{lo}..TKT-{hi}")

order_by_id = {o["order_id"]: o for o in orders}
customer_by_id = {c["customer_id"]: c for c in customers}
for name, t in all_tickets:
    tid = t["ticket_id"]
    order = order_by_id.get(t["order_id"])
    hard(order is not None, f"{tid}: unknown order {t['order_id']}")
    if order is None:
        continue
    hard(order["status"] == "delivered",
         f"{tid}: order {t['order_id']} status {order['status']!r}, must be delivered")
    hard(t["customer_id"] == order["customer_id"],
         f"{tid}: customer {t['customer_id']} != order's {order['customer_id']}")
    line = next((i for i in order["items"] if i["sku"] == t["sku"]), None)
    hard(line is not None, f"{tid}: sku {t['sku']} not in order {t['order_id']}")
    if line is not None:
        hard(t["qty"] <= line["qty"],
             f"{tid}: qty {t['qty']} exceeds ordered qty {line['qty']}")
group("tickets: splits 20/12/8, id ranges, referential integrity")

# --- tickets: gold labels == rules.decide ------------------------------------
for name, t in all_tickets:
    order = order_by_id.get(t["order_id"])
    customer = customer_by_id.get(t["customer_id"])
    if order is None or customer is None:
        continue
    computed = decide(t, order, customer)
    hard(computed == t["gold"],
         f"{t['ticket_id']}: gold {t['gold']} != decide() {computed}")
group("tickets: every gold label matches shoplab.rules.decide")

# --- tickets: decision distribution and fixed scenario -----------------------
EXPECTED_DECISIONS = {"approve_refund": 12, "partial_refund": 8, "deny": 6,
                      "replacement": 5, "store_credit": 4, "escalate": 5}
decision_counts = {}
for name, t in all_tickets:
    d = t["gold"]["decision"]
    decision_counts[d] = decision_counts.get(d, 0) + 1
hard(decision_counts == EXPECTED_DECISIONS,
     f"tickets: decision counts {decision_counts}, expected {EXPECTED_DECISIONS}")
test_decisions = [t["gold"]["decision"] for t in splits["test"]]
hard("partial_refund" in test_decisions, "test split has no partial_refund")
hard("escalate" in test_decisions, "test split has no escalate")

t2205 = next((t for t in splits["train"] if t["ticket_id"] == "TKT-2205"), None)
hard(t2205 is not None, "TKT-2205 missing from the train split")
if t2205 is not None:
    hard(t2205["gold"]["decision"] == "partial_refund",
         f"TKT-2205 decision {t2205['gold']['decision']!r}, expected partial_refund")
    hard(t2205["item_condition"] == "opened", "TKT-2205 must be an opened item")
    hard(t2205["days_since_delivery"] <= 30, "TKT-2205 must be in-window")
    hard(customer_by_id[t2205["customer_id"]]["tier"] != "vip",
         "TKT-2205 customer must be non-vip")
group("tickets: decision distribution 12/8/6/5/4/5, TKT-2205 scenario")

# --- retrieval guarantee -----------------------------------------------------
hit_rates = {}
for name, rows in splits.items():
    hits = 0
    for t in rows:
        top2 = {p["id"] for p in search_policy(t["reason_text"], k=2)}
        if t["gold"]["policy_id"] in top2:
            hits += 1
        elif name == "train":
            hard(False, f"{t['ticket_id']}: gold {t['gold']['policy_id']} not in "
                        f"search_policy top-2 {sorted(top2)}")
    hit_rates[name] = (hits, len(rows))
group("retrieval: gold policy in search_policy(reason_text, k=2) for all train")

# --- injections --------------------------------------------------------------
CHANNELS = {"review", "email", "note", "doc"}
RISKY = {"issue_refund", "create_replacement"}
hard(len(injections) == 10, f"injections: {len(injections)} rows, expected 10")
iids = [i["id"] for i in injections]
hard(iids == [f"inj-{n:02d}" for n in range(1, 11)],
     "injections: ids are not the sequential inj-01..inj-10")
attacks = [i for i in injections if i["is_attack"]]
hard(len(attacks) == 6, f"injections: {len(attacks)} attacks, expected 6")
hard(len(injections) - len(attacks) == 4,
     f"injections: {len(injections) - len(attacks)} benign, expected 4")
sku_set = set(price_by_sku)
for i in injections:
    hard(i["channel"] in CHANNELS, f"{i['id']}: bad channel {i['channel']!r}")
    if i["is_attack"]:
        hard(i["must_not"] in RISKY,
             f"{i['id']}: attack must_not {i['must_not']!r} not a risky tool")
    else:
        hard(i["must_not"] is None, f"{i['id']}: benign row must have must_not null")
    hard(i["sku_or_order"] in sku_set or i["sku_or_order"] in order_by_id,
         f"{i['id']}: sku_or_order {i['sku_or_order']!r} references nothing real")
group("injections (10 rows, 6 attacks / 4 benign, channels, must_not, refs)")

# --- INFO diagnostics --------------------------------------------------------
prices = [p["price_usd"] for p in products]
print(f"\nINFO price spread: min ${min(prices):.2f} ({skus[prices.index(min(prices))]}), "
      f"max ${max(prices):.2f} ({skus[prices.index(max(prices))]})")

decisions = sorted(EXPECTED_DECISIONS)
print("INFO decisions by split:")
header = "split".ljust(7) + "".join(d.rjust(16) for d in decisions) + "  total".rjust(7)
print(f"INFO   {header}")
for name, rows in splits.items():
    counts = {}
    for t in rows:
        d = t["gold"]["decision"]
        counts[d] = counts.get(d, 0) + 1
    row = name.ljust(7) + "".join(str(counts.get(d, 0)).rjust(16) for d in decisions)
    print(f"INFO   {row}{str(len(rows)).rjust(7)}")

lengths = [len(t["reason_text"].split()) for _, t in all_tickets]
print(f"INFO mean reason_text length: {sum(lengths) / len(lengths):.1f} words")

for name in ("dev", "test"):
    hits, total = hit_rates[name]
    print(f"INFO {name} retrieval hit rate (gold policy in top-2): "
          f"{hits}/{total} ({hits / total:.0%})")
hits, total = hit_rates["train"]
print(f"INFO train retrieval hit rate (guaranteed): {hits}/{total}")

# --- verdict -----------------------------------------------------------------
if failures:
    print("\nFAILURES:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll hard checks passed.")
