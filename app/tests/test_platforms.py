"""
Phase 2 Step 7: platform-targeted retrieval (platform_search.py) and its
wiring into POST /api/search/compare.

No network, no API keys: SerpAPI and Gemini are replaced with small fakes.
The async code is driven with asyncio.run(), so no pytest plugin is needed.
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.dependencies import (
    get_gemini_service,
    get_image_matching_service,
    get_serpapi_service,
    get_store,
)
from app.models.schemas import ParsedQuery, Product, ShoppingPriority
from app.routers.search import router
from app.services.platform_search import build_platform_query, filter_to_platform, search_platforms
from app.storage.memory_store import InMemorySessionStore

SETTINGS = Settings(_env_file=None)  # defaults: 5 platforms, 10 raw, keep 3, concurrency 5


def product(pid, title="Red Dress", source="Google", domain=None, price=999.0):
    return Product(id=pid, title=title, source=source, source_domain=domain, price=price)


class FakeSerp:
    """Pretends to be SerpApiService. For a query starting with a platform name,
    returns 4 listings from that platform plus 2 from other retailers."""

    def __init__(self, delay=0.0):
        self.calls = []  # (query, num_results)
        self.in_flight = 0
        self.max_in_flight = 0
        self._delay = delay

    async def search_shopping(self, query, num_results=20):
        self.calls.append((query, num_results))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self._delay)
        self.in_flight -= 1
        platform = query.split()[0]
        sources = [platform] * 4 + ["Ajio" if platform != "Ajio" else "Meesho"] * 2
        return [
            {"title": f"{query} item {i}", "price": f"₹{500 + i}", "source": src, "link": "https://example.com/x"}
            for i, src in enumerate(sources)
        ]


# ---------- pure helpers ----------

def test_build_platform_query_puts_platform_first():
    assert build_platform_query("Myntra", "  red floral dress ") == "Myntra red floral dress"


def test_filter_to_platform_keeps_only_matching_domain_in_order():
    items = [
        product("a", domain="myntra.com"),
        product("b", domain="ajio.com"),
        product("c", domain=None),  # untaggable retailer -> dropped
        product("d", domain="myntra.com"),
    ]
    assert [p.id for p in filter_to_platform(items, "myntra.com")] == ["a", "d"]


# ---------- search_platforms ----------

def test_one_query_per_product_platform_pair_with_platform_name_first():
    serp = FakeSerp()
    asyncio.run(search_platforms(serp, SETTINGS, [product("p1", "Blue Kurta"), product("p2", "Red Dress")],
                                 ["myntra.com", "ajio.com"]))
    assert sorted(q for q, _ in serp.calls) == [
        "Ajio Blue Kurta", "Ajio Red Dress", "Myntra Blue Kurta", "Myntra Red Dress",
    ]
    assert {n for _, n in serp.calls} == {SETTINGS.PLATFORM_RAW_RESULTS_PER_QUERY}


def test_results_are_filtered_to_platform_capped_and_tagged_with_provenance():
    serp = FakeSerp()
    result = asyncio.run(search_platforms(serp, SETTINGS, [product("p1", "Blue Kurta")], ["myntra.com"]))
    found = result.candidates
    assert len(found) == SETTINGS.PLATFORM_CANDIDATES_PER_QUERY  # 4 on-platform available, capped at 3
    assert all(r.source_domain == "myntra.com" for r in found)  # the 2 Ajio listings were dropped
    assert all(r.matched_from_product_id == "p1" for r in found)
    assert result.coverage == {"myntra.com": SETTINGS.PLATFORM_CANDIDATES_PER_QUERY}


def test_concurrency_is_limited_by_the_semaphore():
    serp = FakeSerp(delay=0.01)
    limited = Settings(PLATFORM_SEARCH_CONCURRENCY=2, _env_file=None)
    asyncio.run(search_platforms(serp, limited, [product("p1"), product("p2"), product("p3")],
                                 ["myntra.com", "ajio.com", "amazon.in"]))
    assert len(serp.calls) == 9
    assert serp.max_in_flight == 2


@pytest.mark.parametrize("products,platforms", [([], ["myntra.com"]), ([product("p1")], [])])
def test_nothing_to_search_means_no_calls(products, platforms):
    serp = FakeSerp()
    result = asyncio.run(search_platforms(serp, SETTINGS, products, platforms))
    assert result.candidates == []
    assert result.coverage == {d: 0 for d in platforms}
    assert serp.calls == []


# ---------- /compare wiring ----------

class FakeGemini:
    def generate_platform_queries(self, products, platforms, gender=None):
        return {}  # -> platform_search uses its deterministic phrases

    def explain_tradeoffs(self, products, priorities):
        return {}, "summary"


class PassthroughMatcher:
    """Stands in for ImageMatchingService: keeps every candidate."""

    async def filter_matches(self, candidates, references):
        return candidates


def test_compare_searches_only_the_selected_platforms():
    store = InMemorySessionStore()
    selected = product("p1", "Blue Kurta", source="Google")
    session = store.create_session("kurta", ParsedQuery(), [selected])
    store.update_preferences(session.session_id, ["p1"], [ShoppingPriority.LOWEST_PRICE], "411001", ["myntra.com"])

    serp = FakeSerp()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_serpapi_service] = lambda: serp
    app.dependency_overrides[get_gemini_service] = lambda: FakeGemini()
    app.dependency_overrides[get_image_matching_service] = lambda: PassthroughMatcher()
    app.dependency_overrides[get_settings] = lambda: SETTINGS

    res = TestClient(app).post("/api/search/compare", json={"session_id": session.session_id})

    assert res.status_code == 200
    assert [q for q, _ in serp.calls] == ["Myntra Blue Kurta"]  # one product x one platform
    sources = {p["source"] for p in res.json()["compared_products"]}
    assert sources == {"Google", "Myntra"}  # the selected product itself + Myntra candidates, no Ajio