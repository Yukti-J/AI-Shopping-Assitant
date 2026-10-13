"""
Ranking is deterministic and auditable — NOT delegated to Gemini. Gemini
only explains the trade-offs of an already-decided ranking (see
gemini_service.explain_tradeoffs). Keeping this separate means the
ranking logic can be unit-tested without any API calls or API costs,
and the "why was this ranked here" answer is always inspectable via
score_breakdown.
"""
from __future__ import annotations

import logging

from app.models.schemas import Product, ShoppingPriority

logger = logging.getLogger(__name__)

# Weights per priority: (price_weight, rating_weight, reviews_weight, delivery_weight)
# price_weight applies to INVERSE normalized price (lower price = higher
# score); delivery_weight applies to INVERSE normalized delivery days
# (fewer days = higher score). Every row sums to 1.0 on its own — that
# matters for how multi-priority blending works below.
#
# Phase 2 (Req 4): gained the delivery_weight column and the
# EARLY_DELIVERY row, which concentrates its weight there.
_PRIORITY_WEIGHTS: dict[ShoppingPriority, tuple[float, float, float, float]] = {
    ShoppingPriority.LOWEST_PRICE: (0.75, 0.15, 0.10, 0.00),
    ShoppingPriority.BEST_VALUE: (0.40, 0.35, 0.25, 0.00),
    ShoppingPriority.PREMIUM: (0.05, 0.55, 0.15, 0.00),  # premium favors rating + (elsewhere) higher price band
    ShoppingPriority.QUALITY: (0.10, 0.55, 0.35, 0.00),
    ShoppingPriority.BEST_REVIEWS: (0.10, 0.30, 0.60, 0.00),
    ShoppingPriority.EARLY_DELIVERY: (0.10, 0.15, 0.05, 0.70),
}

# PREMIUM's reward for being in the upper price band is a bonus *on top of*
# the weight-tuple dot product (see _priority_contribution), same as Phase 1.
_PREMIUM_PRICE_BAND_BONUS = 0.25


def rank_products(products: list[Product], priorities: list[ShoppingPriority]) -> list[Product]:
    """Returns a NEW list, sorted best-first, with .score and
    .score_breakdown populated on each product.

    Phase 2 (Req 4): `priority` (single) -> `priorities` (1-3). Each
    selected priority contributes its own full weighted score for a
    product (see _priority_contribution); the product's final `.score` is
    the MEAN of those per-priority scores. Because every weight row sums
    to 1.0, the mean of several such dot products is mathematically
    identical to dotting the mean of the weight tuples against the
    component scores — so this is "averaging the weight tuples" from the
    architecture doc, just computed in the order that also gives us each
    priority's contribution separately for score_breakdown, for free.
    """
    if not products:
        return []
    if not priorities:
        raise ValueError("rank_products requires at least one priority")

    priced = [p for p in products if p.price is not None]
    prices = [p.price for p in priced] if priced else [0.0]
    min_price, max_price = min(prices), max(prices)

    ratings = [p.rating for p in products if p.rating is not None]
    max_rating = max(ratings) if ratings else 5.0

    reviews = [p.reviews_count for p in products if p.reviews_count is not None]
    max_reviews = max(reviews) if reviews else 1

    delivery_days = [p.estimated_delivery_days for p in products if p.estimated_delivery_days is not None]
    min_days, max_days = (min(delivery_days), max(delivery_days)) if delivery_days else (0, 0)
    if not delivery_days and ShoppingPriority.EARLY_DELIVERY in priorities:
        logger.info(
            "EARLY_DELIVERY selected but no candidate has estimated_delivery_days "
            "set (delivery_estimation.py likely wasn't run, or pincode was missing) "
            "— delivery_score will be 0.0 for everyone, so this priority won't "
            "meaningfully differentiate products this round."
        )

    scored: list[Product] = []
    contributions_by_id: dict[str, dict[str, float]] = {}
    for p in products:
        component_scores = {
            "price": _normalize_price_score(p.price, min_price, max_price),
            "rating": (p.rating / max_rating) if (p.rating is not None and max_rating > 0) else 0.0,
            "reviews": (p.reviews_count / max_reviews) if (p.reviews_count is not None and max_reviews > 0) else 0.0,
            "delivery": _normalize_delivery_score(p.estimated_delivery_days, min_days, max_days),
        }
        price_band_fraction = (
            (p.price - min_price) / (max_price - min_price) if (p.price is not None and max_price > min_price) else 0.0
        )

        per_priority_contribution: dict[str, float] = {}
        for priority in priorities:
            per_priority_contribution[priority.value] = round(
                _priority_contribution(priority, component_scores, price_band_fraction), 4
            )

        contributions_by_id[p.id] = per_priority_contribution
        total = sum(per_priority_contribution.values()) / len(priorities)

        p_copy = p.model_copy()
        p_copy.score = round(total, 4)
        p_copy.score_breakdown = {
            "component_scores": {k: round(v, 3) for k, v in component_scores.items()},
            # Each selected priority's own full (unblended) weighted score —
            # this is the auditability the architecture doc asks for:
            # "score_breakdown shows each priority's contribution
            # separately, not just a merged number." .score above is just
            # their mean.
            "priority_contributions": per_priority_contribution,
            "blend_method": f"mean of {len(priorities)} selected priorit{'y' if len(priorities) == 1 else 'ies'}",
        }
        scored.append(p_copy)

    # Phase 2 (Req 8 / Step 10): per-priority "match %". Needs the whole pool
    # (each priority is scored relative to the best product for THAT
    # priority), so it's a second pass after every contribution is known.
    best_per_priority = {
        pr.value: max((c[pr.value] for c in contributions_by_id.values()), default=0.0) for pr in priorities
    }
    for p_copy in scored:
        p_copy.priority_match = compute_priority_match(contributions_by_id[p_copy.id], best_per_priority)

    scored.sort(key=lambda x: x.score or 0.0, reverse=True)
    return scored


def compute_priority_match(contributions: dict[str, float], best_per_priority: dict[str, float]) -> dict[str, float]:
    """One product's match % per selected priority, 0-100.

    match% = this product's own score for the priority / the best score ANY
    candidate got for that priority. So the best option for 'early_delivery'
    shows 100% on that bar, and a product with half that priority-score shows
    ~50%. It is deliberately *relative to the candidates on screen*, not an
    absolute quality grade — the UI labels it "vs. best option here". Built
    from the same _priority_contribution() numbers as the blended ranking, so
    the bars can never disagree with the ordering.

    If nobody scored above 0 for a priority (e.g. no delivery data at all),
    everyone gets 0.0 rather than a misleading 100%.
    """
    result: dict[str, float] = {}
    for priority_value, own in contributions.items():
        best = best_per_priority.get(priority_value, 0.0)
        result[priority_value] = round(min(100.0, 100.0 * own / best), 1) if best > 0 else 0.0
    return result


def _priority_contribution(
    priority: ShoppingPriority, component_scores: dict[str, float], price_band_fraction: float
) -> float:
    """One priority's own full weighted score for a product — i.e. what
    rank_products() would have returned in Phase 1 if only this priority
    had been selected. Shared by rank_products() (for the blended .score
    and score_breakdown) and reusable as-is by Step 10's per-priority
    match-% calculation (compute_priority_match below), since that's defined
    as "reusing the existing _PRIORITY_WEIGHTS row for just that priority."
    """
    price_w, rating_w, reviews_w, delivery_w = _PRIORITY_WEIGHTS[priority]
    contribution = (
        price_w * component_scores["price"]
        + rating_w * component_scores["rating"]
        + reviews_w * component_scores["reviews"]
        + delivery_w * component_scores["delivery"]
    )
    if priority == ShoppingPriority.PREMIUM:
        contribution += _PREMIUM_PRICE_BAND_BONUS * price_band_fraction
    return contribution


def select_diverse_discovery_set(products: list[Product], min_count: int, max_count: int) -> list[Product]:
    """
    Diversity heuristic for the discovery set: spread picks across distinct
    sources and across the price range so the user sees genuinely different
    options, not near-identical listings from one retailer.

    Phase 2 (Req 3): the old fixed `count` (4-5) becomes a range. Returns as
    many diverse, deduped, color-valid products as available, up to
    `max_count`. Only returns fewer than `min_count` if the true candidate
    pool (after normalization/color-validation/dedup, upstream of this
    function) is genuinely smaller than that — never an artificial cap.
    Round-robin-by-retailer logic itself is unchanged from Phase 1.
    """
    if len(products) <= max_count:
        if len(products) < min_count:
            logger.info(
                "Discovery pool has only %d candidates after upstream "
                "filtering (wanted >= %d). Returning all of them — this "
                "reflects real result availability, not a bug.",
                len(products),
                min_count,
            )
        return products

    by_source: dict[str, list[Product]] = {}
    for p in products:
        by_source.setdefault(p.source, []).append(p)

    # sort each source's bucket by price so we can pick spread points later
    for bucket in by_source.values():
        bucket.sort(key=lambda p: p.price if p.price is not None else float("inf"))

    sources_sorted = sorted(by_source.keys())
    selected: list[Product] = []
    seen_ids: set[str] = set()

    # round-robin across sources for retailer diversity
    idx = 0
    while len(selected) < max_count and any(by_source.values()):
        source = sources_sorted[idx % len(sources_sorted)]
        bucket = by_source.get(source, [])
        if bucket:
            candidate = bucket.pop(0)
            if candidate.id not in seen_ids:
                selected.append(candidate)
                seen_ids.add(candidate.id)
        idx += 1
        if all(len(b) == 0 for b in by_source.values()):
            break

    return selected[:max_count]


def pin_selected(ranked: list[Product], selected_ids: list[str], max_count: int) -> list[Product]:
    """Final comparison list: every product the user picked (they asked to
    compare those), then the best-ranked others up to `max_count`.

    Ranking is pure price/rating/delivery, so without this the user's own
    picks can be pushed out by cheaper look-alikes. `ranked` is already
    sorted best-first and the result keeps that order.
    """
    selected = set(selected_ids)
    keep = {p.id for p in ranked if p.id in selected}
    for p in ranked:
        if len(keep) >= max_count:
            break
        keep.add(p.id)
    return [p for p in ranked if p.id in keep]


def _normalize_price_score(price: float | None, min_price: float, max_price: float) -> float:
    if price is None:
        return 0.0
    if max_price == min_price:
        return 1.0
    # invert: lower price -> higher score
    return 1.0 - ((price - min_price) / (max_price - min_price))


def _normalize_delivery_score(days: int | None, min_days: int, max_days: int) -> float:
    """Same inversion pattern as price: fewer days -> higher score.
    Unknown delivery (no estimate at all) scores 0.0 — conservative on
    purpose, since EARLY_DELIVERY shouldn't reward a product just because
    we failed to estimate its delivery time."""
    if days is None:
        return 0.0
    if max_days == min_days:
        return 1.0
    return 1.0 - ((days - min_days) / (max_days - min_days))