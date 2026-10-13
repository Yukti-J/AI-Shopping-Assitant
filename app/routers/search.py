"""
The three-step shopping flow, as separate endpoints so the frontend can
show discovery -> preference questions -> comparison as distinct screens.

Retrieval -> Normalization -> Dedup -> Ranking -> Recommendation stay in
separate service modules; this router only orchestrates the sequence.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.core.dependencies import (
    get_color_validation_service,
    get_delivery_estimation_service,
    get_gemini_service,
    get_image_matching_service,
    get_serpapi_service,
    get_store,
)
from app.models.schemas import (
    CompareRequest,
    CompareResponse,
    DiscoverRequest,
    DiscoverResponse,
    Platform,
    PlatformCoverage,
    PlatformsResponse,
    PreferencesRequest,
    PreferencesResponse,
)
from app.services.color_validation import ColorValidationService
from app.services.dedup import deduplicate
from app.services.delivery_estimation import DeliveryEstimationService
from app.services.gemini_service import GeminiService
from app.services.gender import infer_gender, normalize_gender
from app.services.image_matching import ImageMatchingService
from app.services.normalization import normalize_batch
from app.services.platform_search import search_platforms
from app.services.ranking import pin_selected, rank_products, select_diverse_discovery_set
from app.services.serpapi_service import SerpApiService
from app.storage.memory_store import InMemorySessionStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/platforms", response_model=PlatformsResponse)
async def list_platforms(settings: Settings = Depends(get_settings)):
    """
    The platforms the user can choose to search in the compare stage.
    Single source of truth is config.TARGET_RETAILERS — the frontend renders
    whatever this returns, and /preferences validates against the same list.
    """
    return PlatformsResponse(
        platforms=[Platform(id=d, label=settings.platform_label(d)) for d in settings.target_retailers_list]
    )


@router.post("/discover", response_model=DiscoverResponse)
async def discover(
    request: DiscoverRequest,
    gemini: GeminiService = Depends(get_gemini_service),
    serpapi: SerpApiService = Depends(get_serpapi_service),
    color_validator: ColorValidationService = Depends(get_color_validation_service),
    store: InMemorySessionStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    parsed_query = gemini.parse_query(request.query)

    # Phase 2 (Req 1): one direct SerpAPI call with the user's original
    # query — no more Gemini-rewritten variants fanned out via
    # search_multiple(). Request headroom above DISCOVERY_MAX_COUNT since
    # normalization/dedup/color-validation will remove some candidates
    # before diversity selection ever sees them.
    raw_fetch_count = settings.DISCOVERY_MAX_COUNT + 5  # ~40 at current config
    raw_results = await serpapi.search_shopping(request.query, num_results=raw_fetch_count)
    products = normalize_batch(raw_results)

    # Phase 2 (Req 2): color validation runs here, between normalize and
    # dedupe — a mismatched-color duplicate shouldn't count toward "how
    # many candidates survive" for diversity selection. No-ops if the
    # parsed query has no color or Gemini is unavailable (see
    # color_validation.py's graceful-degradation notes).
    products = await color_validator.filter_by_color(products, parsed_query.color)

    products = deduplicate(products)

    if not products:
        raise HTTPException(
            status_code=422,
            detail=(
                "No products found for this query. This can happen if SERPAPI_API_KEY "
                "is not configured, or if the query returned no shopping results."
            ),
        )

    discovery_set = select_diverse_discovery_set(
        products,
        min_count=settings.DISCOVERY_MIN_COUNT,
        max_count=settings.DISCOVERY_MAX_COUNT,
    )
    session = store.create_session(query=request.query, parsed_query=parsed_query, discovery_products=discovery_set)

    return DiscoverResponse(
        session_id=session.session_id,
        parsed_query=parsed_query,
        discovery_products=discovery_set,
        message=(
            f"Found {len(discovery_set)} diverse options for '{request.query}'. "
            "Pick 1-5 you like, then tell us your shopping priorities."
        ),
    )


@router.post("/preferences", response_model=PreferencesResponse)
async def set_preferences(
    request: PreferencesRequest,
    store: InMemorySessionStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    session = store.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired. Start a new /discover search.")

    valid_ids = {p.id for p in session.discovery_products}
    invalid = [pid for pid in request.selected_product_ids if pid not in valid_ids]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown product id(s) {invalid} — must be from this session's discovery_products.",
        )

    # Phase 2 (Step 6): only platforms we actually support can be selected.
    allowed_platforms = set(settings.target_retailers_list)
    unknown_platforms = [p for p in request.selected_platforms if p not in allowed_platforms]
    if unknown_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platform(s) {unknown_platforms} — must be from GET /api/search/platforms.",
        )

    # Phase 2 (Step 5): the interim single-priority bridge from Steps 2-4
    # is gone — ShoppingSession now stores the full priorities list, and
    # selected_platforms is persisted too (validated in Step 6 and
    # used by /compare for platform-targeted retrieval since Step 7).
    store.update_preferences(
        session_id=request.session_id,
        selected_product_ids=request.selected_product_ids,
        priorities=request.priorities,
        pincode=request.pincode,
        selected_platforms=request.selected_platforms,
    )

    return PreferencesResponse(
        session_id=request.session_id,
        acknowledged_selection=request.selected_product_ids,
        priorities=request.priorities,
        pincode=request.pincode,
        selected_platforms=request.selected_platforms,
        message="Preferences saved. Call /api/search/compare with this session_id to get your comparison.",
    )


@router.post("/compare", response_model=CompareResponse)
async def compare(
    request: CompareRequest,
    gemini: GeminiService = Depends(get_gemini_service),
    serpapi: SerpApiService = Depends(get_serpapi_service),
    image_matcher: ImageMatchingService = Depends(get_image_matching_service),
    delivery_estimator: DeliveryEstimationService = Depends(get_delivery_estimation_service),
    store: InMemorySessionStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    """
    Compare-stage pipeline (Phase 2, Steps 7-10 wired together):

      selected picks -> Gemini writes per-platform queries (Step 8)
        -> platform-targeted SerpAPI search + source/gender filter (Step 7)
        -> image-similarity check against the pick each came from (Step 9)
        -> dedupe -> pincode delivery estimate -> blended ranking
        -> per-priority match % (Step 10) -> pin the user's picks
        -> Gemini trade-off notes for ALL selected priorities
    """
    session = store.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired. Start a new /discover search.")
    if not session.selected_product_ids or not session.priorities or not session.pincode:
        raise HTTPException(
            status_code=400,
            detail="Preferences not set for this session yet. Call /api/search/preferences first.",
        )

    selected_products = [p for p in session.discovery_products if p.id in session.selected_product_ids]

    # Target gender: what the query said ("red dress for women"), else what the
    # user's own picks clearly are. Used to drop opposite-gender listings.
    gender = normalize_gender(session.parsed_query.gender if session.parsed_query else None) or infer_gender(
        p.title for p in selected_products
    )

    # Step 8: one Gemini call writes a phrase for every (product, platform)
    # pair. It's synchronous, so run it off the event loop. {} on any failure
    # -> platform_search falls back to its deterministic phrases.
    platform_labels = {d: settings.platform_label(d) for d in session.selected_platforms}
    queries = await asyncio.to_thread(gemini.generate_platform_queries, selected_products, platform_labels, gender)

    # Step 7: platform-targeted retrieval.
    search_result = await search_platforms(
        serpapi, settings, selected_products, session.selected_platforms, gender=gender, queries=queries
    )
    platform_candidates = search_result.candidates

    # Step 9: keep only candidates whose thumbnail actually looks like the
    # pick they were found for. (Unverifiable ones are kept — see
    # image_matching.py; the user's own picks are never filtered.)
    platform_candidates = await image_matcher.filter_matches(platform_candidates, selected_products)

    # Coverage is reported AFTER image matching, so "found 3 on Myntra" means
    # 3 that survived, not 3 that were merely retrieved.
    coverage_counts = {d: 0 for d in session.selected_platforms}
    for c in platform_candidates:
        if c.source_domain in coverage_counts:
            coverage_counts[c.source_domain] += 1

    # The user's picks go FIRST so that if dedup finds a near-duplicate pair,
    # the pick (not the look-alike) is the one that survives.
    candidates = selected_products + platform_candidates

    total_before_dedup = len(candidates)
    candidates = deduplicate(candidates)
    total_after_dedup = len(candidates)

    # Req 4: pincode-based delivery estimates, before ranking.
    candidates = delivery_estimator.estimate_batch(candidates, session.pincode)

    ranked = rank_products(candidates, session.priorities)
    # Everything the user picked stays in the comparison; the best-ranked
    # others fill the remaining slots up to COMPARISON_MAX_COUNT.
    top_n = pin_selected(ranked, session.selected_product_ids, settings.COMPARISON_MAX_COUNT)
    if len(top_n) < settings.COMPARISON_MIN_COUNT:
        logger.info(
            "Only %d products available for comparison (wanted >= %d). "
            "This reflects real result availability, not a bug.",
            len(top_n),
            settings.COMPARISON_MIN_COUNT,
        )

    notes, overall_summary = gemini.explain_tradeoffs(top_n, session.priorities)
    for p in top_n:
        p.trade_off_note = notes.get(p.id)

    store.save_comparison(request.session_id, top_n)

    return CompareResponse(
        session_id=request.session_id,
        priorities=session.priorities,
        compared_products=top_n,
        overall_summary=overall_summary,
        total_candidates_considered=total_before_dedup,
        total_after_dedup=total_after_dedup,
        platform_coverage=[
            PlatformCoverage(id=d, label=platform_labels[d], candidates_found=n) for d, n in coverage_counts.items()
        ],
    )