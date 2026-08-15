"""Larkspur Outfitters micro-world: data loading and policy search.

All course data lives in ``data/`` as hand-authored JSON (docs/WORLD.md is the
normative schema). Every loader parses its file fresh on each call -- no caching
magic, so edits to the data show up immediately. ``search_policy`` is the
course's tiny deterministic retriever over the 12 policy documents; chapter 00
builds it in-notebook and this module is its canonical home (sentinel region
below, byte-identical to the notebook).
"""

import json
import math
import os
import re
from pathlib import Path

DATA_DIR = (Path(os.environ["SHOPLAB_DATA"]) if os.environ.get("SHOPLAB_DATA")
            else Path(__file__).resolve().parents[2] / "data")


def _load(name):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run from the repo root or set SHOPLAB_DATA "
            f"to the directory that holds the course data files")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_products():
    """The 30-product catalog (list of dicts)."""
    return _load("products.json")


def load_customers():
    """The 15 customers (list of dicts)."""
    return _load("customers.json")


def load_orders():
    """The 40 orders (list of dicts)."""
    return _load("orders.json")


def load_policies():
    """The 12 policy documents (list of {"id", "title", "text"})."""
    return _load("policies.json")


def load_tickets():
    """The gold-labeled tickets ({"train": [...], "dev": [...], "test": [...]})."""
    return _load("tickets.json")


def load_injections():
    """The 10 prompt-injection fixtures for chapter 09 (list of dicts)."""
    return _load("injections.json")


# >>> shoplab.world.search_policy
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "i", "in", "is", "it", "my", "of", "on", "or",
    "that", "the", "this", "to", "was", "we", "with", "you",
}


def _tokenize(text):
    return [t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in _STOPWORDS]


def search_policy(query, k=2):
    """Return the k policy docs best matching `query` (IDF-weighted token overlap)."""
    policies = load_policies()
    doc_tokens = [set(_tokenize(p["title"] + " " + p["text"])) for p in policies]
    df = {}
    for tokens in doc_tokens:
        for tok in tokens:
            df[tok] = df.get(tok, 0) + 1
    idf = {tok: math.log(len(policies) / n) for tok, n in df.items()}
    q = set(_tokenize(query))
    scored = [(sum(idf[t] for t in q & tokens), p)
              for p, tokens in zip(policies, doc_tokens)]
    scored.sort(key=lambda pair: -pair[0])      # stable: ties keep policy order
    return [{"id": p["id"], "title": p["title"], "text": p["text"],
             "score": round(score, 4)}
            for score, p in scored[:k]]
# <<< shoplab.world.search_policy
