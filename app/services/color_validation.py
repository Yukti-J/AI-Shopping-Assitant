"""
Color/image validation (Phase 2, Req 2).

Google Shopping titles/snippets often claim a color that the product photo
doesn't back up (a listing titled "Red Floral Wrap Dress" whose thumbnail is
clearly maroon or pink). This module catches that by asking Gemini's vision
input whether the product actually shown in the thumbnail looks like the
target color — title-only color claims are exactly the failure mode this
exists to catch.

Sequencing (enforced by the caller in routers/search.py, not here): this
runs after normalize_batch(), before deduplicate(). A mismatched-color
duplicate shouldn't count toward "how many candidates survive" for
diversity selection, so color validation has to happen first.

Design notes:
- This module owns its own Gemini vision calls rather than growing
  GeminiService's job. The check here ("does image X look like color Y")
  is a narrow visual QA task, not general NLU/explanation — kept separate
  on purpose, same seam discipline as ranking.py being separate from
  routers/search.py.
- Graceful degradation (matches the rest of the pipeline, see
  project_context.md §8): no GEMINI_API_KEY at all means we can't validate
  anything, so products pass through unfiltered rather than the whole
  discovery set silently emptying out. Once a key IS configured, a specific
  product failing its own check (bad fetch, low confidence, "no" verdict)
  legitimately gets dropped — that's the feature working, not degrading.
- Batched/concurrent via asyncio.gather (capped by a semaphore) so ~40
  candidates don't validate one at a time.
- Cache note (deviation from the architecture doc, documented here on
  purpose): the doc describes caching "per product.id for the life of the
  session," but discover() doesn't have a session_id yet at the point this
  runs (the session is created *after* the discovery set is picked) —
  fixing that would mean changing memory_store.py's session-creation
  timing, which is out of scope for this step. Instead the cache here is
  keyed by (product_id, color) at the service-singleton level. Since
  product_id is already a stable content hash, this gets the same
  de-duplication benefit and will transparently serve the compare stage
  (Step 9) too, without needing session plumbing. Trade-off: the cache has
  no eviction, so on a long-running process it grows unboundedly — fine at
  this project's current scale (single process, restarted often, no
  persistence goals per project_context.md §6), but worth revisiting if
  that ever changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx
import google.generativeai as genai

from app.core.config import get_settings
from app.models.schemas import Product

logger = logging.getLogger(__name__)

_COLOR_CHECK_PROMPT_TEMPLATE = (
    "Look at the main product in this image. Does it appear to be the "
    "color '{color}'? Respond with ONLY a JSON object, no markdown fences, "
    'no preamble: {{"matches": true or false, "confidence": <0.0-1.0>}}'
)

# Below this, treat as "no" — an ambiguous verdict isn't good enough to
# keep a candidate whose whole point is passing a color check.
_CONFIDENCE_THRESHOLD = 0.6
_FETCH_TIMEOUT_SECONDS = 8.0
# Cap concurrent Gemini vision calls so a 40-candidate discovery batch
# doesn't burst the API all at once.
_MAX_CONCURRENT_CHECKS = 8


class ColorValidationService:
    def __init__(self):
        settings = get_settings()
        self._enabled = settings.has_gemini_key
        if self._enabled:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._model = genai.GenerativeModel(settings.gemini_vision_model)
        else:
            self._model = None
            logger.warning(
                "GEMINI_API_KEY not set — color validation disabled; "
                "discovery candidates will NOT be filtered by color."
            )
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CHECKS)
        # (product_id, color_lower) -> verified match. See module docstring
        # for why this is keyed here instead of per-session.
        self._cache: dict[tuple[str, str], bool] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def filter_by_color(self, products: list[Product], color: Optional[str]) -> list[Product]:
        """Drops products whose thumbnail doesn't visually match `color`.

        No-ops (returns products unchanged) if `color` is falsy or the
        service is disabled — we only ever filter when we can actually
        check, per the graceful-degradation principle.
        """
        if not color or not self._enabled or not products:
            return products

        color_key = color.strip().lower()
        tasks = [self._check_one(p, color_key) for p in products]
        results = await asyncio.gather(*tasks)
        kept = [p for p, ok in zip(products, results) if ok]

        logger.info(
            "Color validation for '%s': kept %d/%d candidates",
            color,
            len(kept),
            len(products),
        )
        return kept

    async def _check_one(self, product: Product, color_key: str) -> bool:
        cache_key = (product.id, color_key)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not product.thumbnail_url:
            # No image to check — can't confirm the color claim, so it's
            # dropped rather than trusted on title alone (that's the exact
            # gap this module exists to close).
            self._cache[cache_key] = False
            return False

        async with self._semaphore:
            image_bytes = await self._fetch_image(product.thumbnail_url)
            if image_bytes is None:
                self._cache[cache_key] = False
                return False
            verdict = await asyncio.to_thread(self._ask_gemini, image_bytes, color_key)

        self._cache[cache_key] = verdict
        return verdict

    async def _fetch_image(self, url: str) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            logger.debug("Color validation: thumbnail fetch failed for %s: %s", url, exc)
            return None

    def _ask_gemini(self, image_bytes: bytes, color: str) -> bool:
        """Synchronous Gemini vision call, run off the event loop via
        asyncio.to_thread (see _check_one) so ~40 concurrent candidates
        don't block each other."""
        try:
            prompt = _COLOR_CHECK_PROMPT_TEMPLATE.format(color=color)
            image_part = {"mime_type": "image/jpeg", "data": image_bytes}
            response = self._model.generate_content([prompt, image_part])
            data = _safe_json_parse(response.text)
            if not data:
                return False
            matches = bool(data.get("matches"))
            confidence = float(data.get("confidence", 0.0))
            return matches and confidence >= _CONFIDENCE_THRESHOLD
        except Exception as exc:  # noqa: BLE001 — external API, want broad catch + safe default
            logger.debug("Color validation: Gemini vision check failed: %s", exc)
            return False


def _safe_json_parse(text: str) -> Optional[dict[str, Any]]:
    """Small local copy of gemini_service.py's helper — kept private to
    each module rather than importing the other's underscore-prefixed
    function across a module boundary."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return None