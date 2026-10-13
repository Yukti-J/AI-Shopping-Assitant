"""
Cross-platform image-similarity matching (Phase 2, Step 9 / Req 7).

Problem: platform_search.py finds listings on Myntra/Ajio/etc. by *text*
("Myntra women red floral wrap dress"). Text matches are loose — the top
Myntra result may be a different dress entirely. This module checks the
thumbnails: does the candidate from platform B actually LOOK like the product
the shopper picked on platform A?

Approach decision (this was "still undecided" in project_context.md §18):
Gemini vision, not a local CLIP model. Reasons:
  - zero new dependencies (open_clip pulls in PyTorch, ~2 GB, slow installs),
  - reuses the GEMINI_API_KEY the app already needs,
  - we only need a yes/no-ish "same product?" verdict, not a vector index.
Trade-off: it costs one vision call per (candidate, picked product) pair
instead of a free local embedding. Results are cached per pair, and the
number of calls is bounded by PLATFORM_CANDIDATES_PER_QUERY x products x
platforms, throttled by IMAGE_MATCH_CONCURRENCY. If cost ever matters more
than simplicity, swap `_ask_gemini` for a local-embedding implementation —
the public interface (`filter_matches`) would not change.

The score is a 0-1 "visual similarity" Gemini reports against a fixed rubric
(see _PROMPT). It is NOT a mathematical cosine similarity, but it is compared
against the same IMAGE_SIMILARITY_THRESHOLD setting and stored in the same
`Product.visual_similarity_score` field, so the rest of the system is
unaffected by how the number is produced.

Three outcomes per candidate — kept deliberately distinct:
  MATCH     score >= threshold                  -> kept, score recorded
  NO MATCH  score <  threshold, or the candidate's own thumbnail is missing /
            unreadable                          -> dropped
  UNKNOWN   no API key, picked product has no usable image, or the Gemini
            call itself failed (quota, timeout) -> kept, score left None
Rationale for UNKNOWN: an outage on our side must not silently wipe out the
whole comparison; that matches the graceful-degradation rule in §8.

Like color_validation.py this module owns its own Gemini vision calls; it
never ranks anything (ranking.py) and never searches (platform_search.py).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Optional

import httpx
import google.generativeai as genai

from app.core.config import get_settings
from app.models.schemas import Product

logger = logging.getLogger(__name__)

_PROMPT = (
    "Image 1 is a product a shopper liked. Image 2 is a candidate listing from a "
    "different store. Decide how visually similar the two products are, judging "
    "ONLY the product itself (ignore background, model, watermark, photo style).\n"
    "Scoring guide:\n"
    "  0.9-1.0  same product or a near-identical look (same item type, cut, colour, pattern)\n"
    "  0.75-0.9 very close alternative (same item type and colour, small design differences)\n"
    "  0.4-0.75 same broad category but clearly different design/colour/pattern\n"
    "  0.0-0.4  different kind of product\n"
    'Respond with ONLY a JSON object, no markdown fences, no preamble: {"similarity": <0.0-1.0>}'
)

_FETCH_TIMEOUT_SECONDS = 8.0


class ImageMatchingService:
    def __init__(self):
        settings = get_settings()
        self._enabled = settings.has_gemini_key
        self._threshold = settings.IMAGE_SIMILARITY_THRESHOLD
        if self._enabled:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._model = genai.GenerativeModel(settings.gemini_vision_model)
        else:
            self._model = None
            logger.warning("GEMINI_API_KEY not set — image matching disabled; candidates will NOT be image-verified.")
        self._semaphore = asyncio.Semaphore(settings.IMAGE_MATCH_CONCURRENCY)
        # (reference_product_id, candidate_product_id) -> score. None = unknown.
        self._cache: dict[tuple[str, str], Optional[float]] = {}
        # thumbnail url -> (bytes, mime) so the same picked product's image is
        # downloaded once, not once per candidate.
        self._image_cache: dict[str, Optional[tuple[bytes, str]]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def filter_matches(self, candidates: list[Product], references: list[Product]) -> list[Product]:
        """Verifies each candidate against the picked product it was found for
        (`matched_from_product_id`). Returns NEW Product copies for the ones
        that survive, with `visual_similarity_score` set where it was
        verified. Order is preserved."""
        if not candidates or not self._enabled:
            return candidates

        refs_by_id = {r.id: r for r in references}
        verdicts = await asyncio.gather(*(self._score_one(c, refs_by_id.get(c.matched_from_product_id or "")) for c in candidates))

        kept: list[Product] = []
        for candidate, (decision, score) in zip(candidates, verdicts):
            if decision == "no_match":
                continue
            copy = candidate.model_copy()
            copy.visual_similarity_score = score
            kept.append(copy)
        logger.info("Image matching: kept %d/%d platform candidates (threshold %.2f)", len(kept), len(candidates), self._threshold)
        return kept

    async def _score_one(self, candidate: Product, reference: Optional[Product]) -> tuple[str, Optional[float]]:
        """-> ("match" | "no_match" | "unknown", score)"""
        if reference is None or not reference.thumbnail_url:
            return "unknown", None  # nothing to compare against — can't judge
        if not candidate.thumbnail_url:
            return "no_match", None  # can't verify its look -> don't trust it

        key = (reference.id, candidate.id)
        if key not in self._cache:
            self._cache[key] = await self._compute_score(reference, candidate)
        score = self._cache[key]
        if score is None:
            # Distinguish "candidate image unreadable" from "our side failed"
            # inside _compute_score by caching a sentinel; see below.
            return "unknown", None
        if score < 0:
            return "no_match", None  # sentinel: candidate image could not be fetched
        return ("match" if score >= self._threshold else "no_match"), score

    async def _compute_score(self, reference: Product, candidate: Product) -> Optional[float]:
        """Score in [0,1]; -1.0 = candidate image unreadable (drop); None = our side failed (keep)."""
        async with self._semaphore:
            ref_img = await self._get_image(reference.thumbnail_url)
            if ref_img is None:
                return None  # picked product's image unreadable -> unknown, not the candidate's fault
            cand_img = await self._get_image(candidate.thumbnail_url)
            if cand_img is None:
                return -1.0
            return await asyncio.to_thread(self._ask_gemini, ref_img, cand_img)

    def _ask_gemini(self, ref_img: tuple[bytes, str], cand_img: tuple[bytes, str]) -> Optional[float]:
        """Synchronous vision call (run via asyncio.to_thread). None on any failure."""
        try:
            response = self._model.generate_content(
                [
                    _PROMPT,
                    "Image 1:", {"mime_type": ref_img[1], "data": ref_img[0]},
                    "Image 2:", {"mime_type": cand_img[1], "data": cand_img[0]},
                ],
                generation_config={"temperature": 0},
            )
            data = _safe_json_parse(response.text)
            if not data:
                return None
            return max(0.0, min(1.0, float(data["similarity"])))
        except Exception as exc:  # noqa: BLE001 — external API: keep candidate as "unknown"
            logger.warning("Image matching: Gemini vision call failed: %r", exc)
            return None

    async def _get_image(self, url: str) -> Optional[tuple[bytes, str]]:
        if url in self._image_cache:
            return self._image_cache[url]
        result: Optional[tuple[bytes, str]] = None
        try:
            if url.startswith("data:"):
                # SerpAPI sometimes inlines thumbnails as base64 data URIs.
                raw = base64.b64decode(url.split(",", 1)[1])
            else:
                async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    raw = resp.content
            if raw:
                result = (raw, _sniff_mime(raw))
        except (httpx.HTTPError, ValueError, IndexError) as exc:
            logger.warning("Image matching: could not load image %s: %r", url[:80], exc)
        self._image_cache[url] = result
        return result


def _sniff_mime(data: bytes) -> str:
    """Best-effort image type from magic bytes (thumbnails are not always JPEG)."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF":
        return "image/gif"
    return "image/jpeg"


def _safe_json_parse(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        parsed = json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None