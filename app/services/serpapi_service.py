"""
SerpAPI is a CANDIDATE RETRIEVAL mechanism only. It must never be treated
as the final recommendation engine — no ranking or filtering decisions
belong here. This module's only job is: take search strings, hit SerpAPI's
Google Shopping engine, and return raw results for normalization.py to
turn into Product objects.

Phase 2 (Req 1): the discover step now makes a single search_shopping()
call with the user's raw query (no more Gemini-rewritten variants fanned
out via search_multiple()). It requests up to ~40 raw results so that
select_diverse_discovery_set() has enough of a pool to pick 20-35 diverse,
color-valid products from after normalization/validation/dedup.
search_multiple() is currently unused: discover makes one call, and the
compare stage's platform_search.py calls search_shopping() directly so it
can throttle concurrency. It's kept as a small general-purpose helper.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search"


class SerpApiService:
    def __init__(self):
        settings = get_settings()
        self._api_key = settings.SERPAPI_API_KEY
        self._country = settings.SERPAPI_COUNTRY
        self._language = settings.SERPAPI_LANGUAGE
        self._enabled = settings.has_serpapi_key

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def search_shopping(self, query: str, num_results: int = 20) -> list[dict[str, Any]]:
        """Runs one Google Shopping search via SerpAPI, returns raw shopping_results.

        Phase 2 note: the discover step calls this with num_results=~40
        (config: DISCOVERY_MAX_COUNT + headroom for validation/dedup loss).
        `num` is passed to the API itself, not just used to slice locally —
        SerpAPI's default page size is smaller than 40, so without this the
        discover step would silently get fewer raw candidates than intended.
        """
        if not self._enabled:
            logger.warning("SERPAPI_API_KEY not set — returning empty candidate list for %r", query)
            return []

        params = {
            "engine": "google_shopping",
            "q": query,
            "gl": self._country,
            "hl": self._language,
            "num": num_results,
            "api_key": self._api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(SERPAPI_ENDPOINT, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("SerpAPI request failed for query %r: %s", query, exc)
            return []

        results = data.get("shopping_results", []) or []
        return results[:num_results]

    async def search_multiple(self, queries: list[str], per_query_results: int = 15) -> list[dict[str, Any]]:
        """Fan out several search strings and flatten the raw results.
        Caller (normalization/dedup) is responsible for merging/deduping.

        Phase 2: currently unused (see module docstring). Not throttled —
        platform_search.py has its own semaphore-limited fan-out instead.
        """
        import asyncio

        if not queries:
            return []
        tasks = [self.search_shopping(q, num_results=per_query_results) for q in queries]
        results_lists = await asyncio.gather(*tasks, return_exceptions=False)
        flattened: list[dict[str, Any]] = []
        for results in results_lists:
            flattened.extend(results)
        return flattened