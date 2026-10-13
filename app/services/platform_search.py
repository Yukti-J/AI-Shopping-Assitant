"""
Platform-targeted retrieval for the compare stage (Phase 2, Step 7).

Why this module exists: SerpAPI's Google Shopping engine can't be pinned to
one retailer. The documented `site:` operator returns zero results (tested
during Phase 2 planning). What does work is a two-part workaround:

  1. Put the platform name FIRST in the query ("Myntra <product title>") so
     Google's shopping index leans toward that retailer's listings.
  2. Then FILTER: keep only results whose retailer actually is that
     platform. Phrasing only nudges the results, so the filter is what
     makes the platform guarantee real.

This module only retrieves and filters candidates. Like serpapi_service.py,
it makes no ranking decisions (ranking.py) and does no image verification
(Step 9). Step 8 will swap the query *text* for Gemini-written,
platform-specific queries; the retrieval + filter machinery here stays.

Step 8 (done): `search_platforms(..., queries=...)` accepts Gemini-written
phrases keyed by (product_id, platform_domain). Any pair without one falls back
to build_search_phrase(), so Gemini being down/garbled never breaks retrieval.
The platform name is still prepended HERE (QUERY_TEMPLATE), never trusted to Gemini.

Relevance guards added after the first live run:
- Queries are built from a SIMPLIFIED title (brand dropped, ads/specs after
  a "|" cut, ~8 words, gender added). Searching Meesho for an Amazon seller's
  exact title can't work — the brand and phrasing don't exist there.
- Candidates that clearly target the opposite gender are dropped.
- Per-platform coverage is returned so the UI can say "no Meesho listings
  found" instead of silently showing only other platforms.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import Settings
from app.models.schemas import Product
from app.services.gender import ALL_GENDER_WORDS, matches_gender, words
from app.services.normalization import normalize_batch
from app.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)

# Single place to tune the phrasing. Platform name first, then the product.
QUERY_TEMPLATE = "{platform} {query}"


_CUT_RE = re.compile(r"\s[|\-–—]\s|[|(\[]")  # " | ", " - ", or an opening bracket
_MAX_BRAND_WORDS = 3  # a gender word within the first N words marks where the brand ends
_MAX_PHRASE_WORDS = 8


def build_search_phrase(title: str, gender: Optional[str] = None, brand: Optional[str] = None) -> str:
    """Turns a long marketplace title into a short, retailer-neutral query.

    "AUSK Women's Casual Summer Polo Knit T-Shirt | Zip Collar Top | Half..."
      -> "Women's Casual Summer Polo Knit T-Shirt"

    1. cut at the first " | " / " - " / bracket (the rest is ad copy/specs)
    2. drop the brand: an explicit `brand` prefix, or any words before a
       gender word that appears within the first few words
    3. keep at most 8 words
    4. if no gender word is left and the search has a target gender, add it
    """
    head = _CUT_RE.split(title, maxsplit=1)[0].replace("’", "'").strip()
    if brand and head.lower().startswith(brand.lower()):
        head = head[len(brand):].strip(" -–—:,")
    tokens = head.split()
    for i, token in enumerate(tokens[: _MAX_BRAND_WORDS + 1]):
        if set(words(token)) & ALL_GENDER_WORDS:
            tokens = tokens[i:]
            break
    phrase = " ".join(tokens[:_MAX_PHRASE_WORDS])
    if gender and not (set(words(phrase)) & ALL_GENDER_WORDS):
        phrase = f"{gender} {phrase}"
    return phrase.strip()


@dataclass
class PlatformSearchResult:
    candidates: list[Product] = field(default_factory=list)
    # platform domain -> how many candidates survived all filters. Every
    # requested platform is present, so 0 means "searched, found nothing".
    coverage: dict[str, int] = field(default_factory=dict)


def build_platform_query(platform_label: str, query: str) -> str:
    """'Myntra' + 'red floral dress' -> 'Myntra red floral dress'."""
    return QUERY_TEMPLATE.format(platform=platform_label, query=query.strip()).strip()


def filter_to_platform(products: list[Product], platform_domain: str) -> list[Product]:
    """Keeps only products sold by `platform_domain` (e.g. 'myntra.com').

    normalization.py already tags each product's `source_domain` by matching
    the retailer name/link against TARGET_RETAILERS, so this is a plain
    equality check. Products it couldn't tag (source_domain=None) are
    dropped — an unverifiable platform is the same as a wrong one here.
    Order is preserved, so Google's relevance order survives the filter.
    """
    return [p for p in products if p.source_domain == platform_domain]


async def search_platforms(
    serpapi: SerpApiService,
    settings: Settings,
    products: list[Product],
    platforms: list[str],
    gender: Optional[str] = None,
    queries: Optional[dict[tuple[str, str], str]] = None,
) -> PlatformSearchResult:
    """For every (selected product x selected platform) pair: search that
    platform for that product, filter to the platform, keep the top few.

    `gender` ('women' / 'men' / None) drops candidates that clearly target
    the other gender and is added to queries that don't mention one.

    `queries` (Step 8): optional {(product_id, platform_domain): phrase} from
    GeminiService.generate_platform_queries(). Missing pairs use the
    deterministic build_search_phrase() instead.

    Returns the candidates plus per-platform coverage. Each candidate carries `matched_from_product_id`
    = the selected product whose query surfaced it. That's provenance, not
    proof of a match — Step 9 will verify with image similarity.

    Cost note: this makes len(products) * len(platforms) SerpAPI calls
    (worst case 5 x 5 = 25), throttled by PLATFORM_SEARCH_CONCURRENCY.
    """
    if not products or not platforms:
        return PlatformSearchResult(coverage={d: 0 for d in platforms})

    semaphore = asyncio.Semaphore(settings.PLATFORM_SEARCH_CONCURRENCY)

    async def search_one(platform_domain: str, product: Product) -> list[Product]:
        phrase = (queries or {}).get((product.id, platform_domain)) or build_search_phrase(
            product.title, gender, product.brand
        )
        query = build_platform_query(settings.platform_label(platform_domain), phrase)
        async with semaphore:
            raw = await serpapi.search_shopping(query, num_results=settings.PLATFORM_RAW_RESULTS_PER_QUERY)
        candidates = normalize_batch(raw)
        on_platform = filter_to_platform(candidates, platform_domain)
        relevant = [c for c in on_platform if matches_gender(c.title, gender)]
        kept = relevant[: settings.PLATFORM_CANDIDATES_PER_QUERY]
        for candidate in kept:
            candidate.matched_from_product_id = product.id
        logger.info(
            "platform search %r: %d raw -> %d on %s -> %d right gender -> kept %d",
            query, len(raw), len(on_platform), platform_domain, len(relevant), len(kept),
        )
        return kept

    pairs = [(d, p) for d in platforms for p in products]
    groups = await asyncio.gather(*(search_one(d, p) for d, p in pairs))

    result = PlatformSearchResult(coverage={d: 0 for d in platforms})
    for (platform_domain, _), group in zip(pairs, groups):
        result.candidates.extend(group)
        result.coverage[platform_domain] += len(group)
    return result