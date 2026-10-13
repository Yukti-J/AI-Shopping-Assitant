"""
Normalization: raw, heterogeneous SerpAPI shopping_results entries ->
common Product schema. This is the ONLY place that should know about
SerpAPI's raw field names, so if we ever add another retrieval source
(direct retailer API, another SERP provider), we add a sibling normalizer
here rather than touching ranking/dedup/routers.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from app.core.config import get_settings
from app.models.schemas import DeliveryConfidence, Product

_PRICE_RE = re.compile(r"[\d,]+\.?\d*")


def normalize_serpapi_result(raw: dict[str, Any]) -> Optional[Product]:
    """Maps one SerpAPI google_shopping result dict to a Product.
    Returns None if the result is too incomplete to be useful (no title
    or no price — both are needed for meaningful comparison)."""
    title = raw.get("title")
    if not title:
        return None

    price = _parse_price(raw.get("price"))
    original_price = _parse_price(raw.get("original_price") or raw.get("extracted_old_price"))
    source = raw.get("source") or "Unknown retailer"
    source_domain = _guess_domain(source, raw.get("link"))

    rating = raw.get("rating")
    reviews_count = raw.get("reviews")

    product_id = _make_product_id(title=title, source=source, price=price)

    delivery_estimate, delivery_confidence = _extract_delivery(raw)

    return Product(
        id=product_id,
        title=title,
        brand=raw.get("brand"),
        price=price,
        currency="INR",
        original_price=original_price,
        rating=float(rating) if rating is not None else None,
        reviews_count=int(reviews_count) if isinstance(reviews_count, (int, float)) else None,
        source=source,
        source_domain=source_domain,
        product_url=raw.get("product_link") or raw.get("link"),
        thumbnail_url=raw.get("thumbnail"),
        delivery_estimate=delivery_estimate,
        delivery_confidence=delivery_confidence,
        extracted_attributes={},
        raw_snippet=raw.get("snippet"),
    )


def normalize_batch(raw_results: list[dict[str, Any]]) -> list[Product]:
    products = []
    for raw in raw_results:
        p = normalize_serpapi_result(raw)
        if p is not None:
            products.append(p)
    return products


def _parse_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _PRICE_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _guess_domain(source_name: str, link: Optional[str]) -> Optional[str]:
    known = get_settings().target_retailers_list
    haystack = f"{source_name} {link or ''}".lower()
    for domain in known:
        root = domain.split(".")[0]
        if root in haystack:
            return domain
    return None


def _make_product_id(title: str, source: str, price: Optional[float]) -> str:
    basis = f"{title.strip().lower()}|{source.strip().lower()}|{price}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _extract_delivery(raw: dict[str, Any]) -> tuple[Optional[str], DeliveryConfidence]:
    """
    SerpAPI's google_shopping engine sometimes includes a 'delivery' field
    on shopping_results, but it's inconsistent across retailers and not
    pincode-aware. We surface it when present and mark it ESTIMATED (not
    CONFIRMED) since it's Google's summary, not a retailer's live quote.
    """
    delivery = raw.get("delivery")
    if delivery:
        return str(delivery), DeliveryConfidence.ESTIMATED
    return None, DeliveryConfidence.UNKNOWN
