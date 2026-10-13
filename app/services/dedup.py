"""
Deduplication of normalized products.

Phase 1 uses a deterministic near-duplicate heuristic (normalized title
similarity + same retailer + close price) since we don't have embeddings
yet. Phase 2 replaces `_titles_similar` with a text-embedding cosine
similarity check without touching the rest of this module's interface.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.models.schemas import Product

_TITLE_SIMILARITY_THRESHOLD = 0.85
_PRICE_TOLERANCE_PCT = 0.03  # 3%


def deduplicate(products: list[Product]) -> list[Product]:
    """Exact-id dedup first (same title+source+price hash), then a
    near-duplicate pass across remaining items."""
    seen_ids: set[str] = set()
    exact_deduped: list[Product] = []
    for p in products:
        if p.id in seen_ids:
            continue
        seen_ids.add(p.id)
        exact_deduped.append(p)

    return _near_duplicate_pass(exact_deduped)


def _near_duplicate_pass(products: list[Product]) -> list[Product]:
    kept: list[Product] = []
    for candidate in products:
        is_duplicate = False
        for existing in kept:
            if _is_near_duplicate(candidate, existing):
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(candidate)
    return kept


def _is_near_duplicate(a: Product, b: Product) -> bool:
    if a.source != b.source:
        return False  # same product on different retailers is NOT a dup — that's the point of comparison
    if not _titles_similar(a.title, b.title):
        return False
    if a.price is not None and b.price is not None:
        if a.price == 0 or b.price == 0:
            return False
        pct_diff = abs(a.price - b.price) / max(a.price, b.price)
        if pct_diff > _PRICE_TOLERANCE_PCT:
            return False
    return True


def _titles_similar(t1: str, t2: str) -> bool:
    n1, n2 = _normalize_title(t1), _normalize_title(t2)
    ratio = SequenceMatcher(None, n1, n2).ratio()
    return ratio >= _TITLE_SIMILARITY_THRESHOLD


def _normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
