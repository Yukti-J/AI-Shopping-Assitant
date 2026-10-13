"""
Common data schemas.

Product is the normalized schema every retailer/SerpAPI result gets mapped
into before any ranking/dedup logic touches it. This is the seam that lets
Phase 2 (embeddings, image similarity) plug in without touching retrieval
or ranking code.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ShoppingPriority(str, Enum):
    BEST_VALUE = "best_value"
    PREMIUM = "premium"
    QUALITY = "quality"
    LOWEST_PRICE = "lowest_price"
    BEST_REVIEWS = "best_reviews"
    EARLY_DELIVERY = "early_delivery"  # Phase 2 (Req 4)


class DeliveryConfidence(str, Enum):
    """
    SerpAPI's Google Shopping engine does not reliably return delivery
    dates. Rather than fabricate a date, we surface a confidence label so
    the frontend/user knows whether a date is a real signal or a rough
    estimate. See project_context.md > Known Limitations.
    """
    CONFIRMED = "confirmed"       # retailer explicitly reported it
    ESTIMATED = "estimated"       # heuristic based on retailer + pincode
    UNKNOWN = "unknown"           # no signal available


class Product(BaseModel):
    """Normalized product — the common schema all retailers map into."""
    id: str  # stable hash derived from source+title+price, used for dedup
    title: str
    brand: Optional[str] = None
    price: Optional[float] = None
    currency: str = "INR"
    original_price: Optional[float] = None  # for discount display
    rating: Optional[float] = None  # 0-5
    reviews_count: Optional[int] = None
    source: str  # retailer name, e.g. "Amazon.in", "Myntra"
    source_domain: Optional[str] = None
    product_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    delivery_estimate: Optional[str] = None  # human-readable, e.g. "3-5 days"
    delivery_confidence: DeliveryConfidence = DeliveryConfidence.UNKNOWN
    extracted_attributes: dict = Field(default_factory=dict)  # color, material, etc.
    raw_snippet: Optional[str] = None  # short description/snippet from search result

    # --- Phase 2 additions ---
    # Req 4: pincode-tier + retailer-speed heuristic (delivery_estimation.py).
    # Distinct from delivery_estimate/delivery_confidence above, which are
    # Phase 1's best-effort/unused fields — this is the number Early Delivery
    # ranking and the frontend actually use.
    estimated_delivery_days: Optional[int] = None
    # Req 7: cross-platform image-similarity match (image_matching.py)
    visual_similarity_score: Optional[float] = None  # cosine similarity, 0-1
    matched_from_product_id: Optional[str] = None  # which selected product this was matched against

    # Populated only after ranking
    score: Optional[float] = None
    score_breakdown: Optional[dict] = None
    trade_off_note: Optional[str] = None
    # Req 8: per-priority relative match %, e.g. {"early_delivery": 82.0}.
    # Keyed only by the priorities the user actually selected (1-3 entries).
    priority_match: dict[str, float] = Field(default_factory=dict)


class ParsedQuery(BaseModel):
    """Gemini's structured extraction of a free-text shopping query."""
    category: Optional[str] = None
    subcategory: Optional[str] = None
    color: Optional[str] = None
    gender: Optional[str] = None
    style_keywords: list[str] = Field(default_factory=list)
    occasion: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    search_queries: list[str] = Field(default_factory=list)  # ready-to-use search strings


# ---------------- API request/response contracts ----------------

class DiscoverRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Free-text shopping query, e.g. 'red dress'")


class DiscoverResponse(BaseModel):
    session_id: str
    parsed_query: ParsedQuery
    discovery_products: list[Product]
    message: str


class Platform(BaseModel):
    """One searchable retailer, as offered to the frontend's platform picker."""
    id: str     # retailer domain, e.g. "amazon.in" — this exact value is sent back in selected_platforms
    label: str  # display name, e.g. "Amazon"


class PlatformsResponse(BaseModel):
    platforms: list[Platform]


class PreferencesRequest(BaseModel):
    session_id: str
    # Phase 2 raises the selection cap from 1-2 to 1-5 (project_context.md §17)
    selected_product_ids: list[str] = Field(..., min_length=1, max_length=5)
    # Phase 2 (Req 4): exactly one priority becomes 1-3, weights blended in ranking.py
    priorities: list[ShoppingPriority] = Field(..., min_length=1, max_length=3)
    pincode: str = Field(..., min_length=4, max_length=10)
    # Phase 2 (Req 5): platforms to search in the compare stage, populated
    # from GET /api/search/platforms. Values are restricted to whatever's
    # configured as searchable (see platform_search.py, step 7).
    selected_platforms: list[str] = Field(..., min_length=1)


class PreferencesResponse(BaseModel):
    session_id: str
    acknowledged_selection: list[str]
    priorities: list[ShoppingPriority]
    pincode: str
    selected_platforms: list[str]
    message: str


class CompareRequest(BaseModel):
    session_id: str


class PlatformCoverage(BaseModel):
    """How many comparison candidates the search found on one selected platform."""
    id: str
    label: str
    candidates_found: int  # 0 = we searched it and found nothing usable


class CompareResponse(BaseModel):
    session_id: str
    priorities: list[ShoppingPriority]  # Phase 2: was a single `priority`
    compared_products: list[Product]
    overall_summary: str
    total_candidates_considered: int
    total_after_dedup: int
    platform_coverage: list[PlatformCoverage] = Field(default_factory=list)