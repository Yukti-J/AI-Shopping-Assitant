"""
Pincode-tier + retailer-speed delivery estimation (Phase 2, Req 4).

Phase 1 collected a pincode but never used it — SerpAPI's google_shopping
results don't reliably include live, pincode-aware delivery dates (see
normalization.py::_extract_delivery and project_context.md's Known
Limitations). This module is the heuristic the Early Delivery priority
needs instead: it makes NO network calls and talks to NO shipping/carrier
API. It maps (pincode prefix, retailer) -> a plausible
`estimated_delivery_days` integer using two small static tables.

This is explicitly a placeholder, not a real logistics integration — the
architecture doc flags swapping in a real delivery-estimation API as
future (post-Phase-2) work. Nothing here should be read as a delivery
promise: every product this touches gets DeliveryConfidence.ESTIMATED,
never CONFIRMED.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.models.schemas import DeliveryConfidence, Product

logger = logging.getLogger(__name__)

# --- Pincode tier table ----------------------------------------------------
# Keyed by the pincode's first 2 digits, which roughly correspond to
# India's postal zones. Intentionally small and approximate — a real
# implementation would use a proper pincode/locality database. Anything
# not listed here falls through to "tier3" (see _tier_for_pincode).
_METRO_PREFIXES = {
    "11",  # Delhi/NCR
    "40",  # Mumbai
    "41",  # Pune
    "56",  # Bengaluru
    "60",  # Chennai
    "70",  # Kolkata
    "50",  # Hyderabad
}
_TIER2_PREFIXES = {
    "38", "39",  # Gujarat (Ahmedabad, Surat)
    "30", "31", "32",  # Rajasthan (Jaipur, Jodhpur)
    "20", "21", "22", "23",  # Uttar Pradesh
    "44", "45",  # Madhya Pradesh
}

_TIER_BASE_DAYS = {
    "metro": 2,
    "tier2": 4,
    "tier3": 6,
}

# --- Retailer dispatch-speed modifier --------------------------------------
# Added on top of the pincode tier's base days. Negative = faster than
# baseline. Keys match normalization.py's source_domain values (which come
# from config.TARGET_RETAILERS) — a retailer not in this table gets no
# adjustment, not an error.
_RETAILER_SPEED_MODIFIER_DAYS: dict[str, int] = {
    "amazon.in": -1,
    "flipkart.com": -1,
    "myntra.com": 0,
    "ajio.com": 0,
    "meesho.com": 1,  # typically slower dispatch than the larger platforms
}

_MIN_DAYS = 1  # floor — a metro + fast-retailer combo should never estimate 0 or negative days


class DeliveryEstimationService:
    """Stateless on purpose: no I/O, no API calls, so this is trivially
    unit-testable and safe to call synchronously in bulk."""

    def estimate_batch(self, products: list[Product], pincode: Optional[str]) -> list[Product]:
        """Returns NEW Product copies with estimated_delivery_days and
        delivery_confidence populated. If pincode is missing/blank,
        returns products unchanged — no guess without at least a pincode
        to anchor it (graceful degradation, same principle as the rest of
        the pipeline)."""
        if not pincode or not pincode.strip():
            logger.debug("No pincode on session — skipping delivery estimation for %d products.", len(products))
            return products

        tier = self._tier_for_pincode(pincode)
        base_days = _TIER_BASE_DAYS[tier]

        estimated: list[Product] = []
        for p in products:
            modifier = self._modifier_for_source(p.source_domain)
            days = max(_MIN_DAYS, base_days + modifier)

            p_copy = p.model_copy()
            p_copy.estimated_delivery_days = days
            # Always ESTIMATED, never CONFIRMED — see module docstring.
            p_copy.delivery_confidence = DeliveryConfidence.ESTIMATED
            # Don't clobber a human-readable estimate normalization.py
            # already pulled from SerpAPI's own 'delivery' field, if any —
            # only fill in when there's nothing there yet.
            if not p_copy.delivery_estimate:
                p_copy.delivery_estimate = f"{days} day{'s' if days != 1 else ''} (estimated)"
            estimated.append(p_copy)

        return estimated

    @staticmethod
    def _tier_for_pincode(pincode: str) -> str:
        prefix = pincode.strip()[:2]
        if prefix in _METRO_PREFIXES:
            return "metro"
        if prefix in _TIER2_PREFIXES:
            return "tier2"
        return "tier3"

    @staticmethod
    def _modifier_for_source(source_domain: Optional[str]) -> int:
        if not source_domain:
            return 0
        return _RETAILER_SPEED_MODIFIER_DAYS.get(source_domain.lower(), 0)