"""
Phase 2 Step 11 (automated half): the whole user journey through the REAL
routers and pipeline, with only the outside world (SerpAPI, Gemini, image
fetching) replaced by fakes. Run it any time with:  python -m pytest -q
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.dependencies import (
    get_color_validation_service, get_gemini_service, get_image_matching_service, get_serpapi_service, get_store,
)
from app.models.schemas import ParsedQuery
from app.routers.search import router
from app.storage.memory_store import InMemorySessionStore

SETTINGS = Settings(_env_file=None)


class FakeSerp:
    def __init__(self):
        self.queries = []

    async def search_shopping(self, query, num_results=20):
        self.queries.append(query)
        first = query.split()[0]
        if first in {"Myntra", "Meesho", "Amazon"}:
            # 3 right-gender listings + 1 men's listing, all on the platform
            titles = [f"Women red wrap dress style {i}" for i in range(3)] + ["Men red polo"]
            return [{"title": f"{t} {first}", "price": f"₹{400 + 37 * i}", "source": first,
                     "thumbnail": f"img-{first}-{i}", "link": "https://x"} for i, t in enumerate(titles)]
        # discovery
        return [{"title": f"Women Red Dress {i}", "price": f"₹{900 + 111 * i}", "source": src,
                 "thumbnail": f"disc-{i}", "rating": 4.0 + i / 10, "reviews": 50 * (i + 1), "link": "https://x"}
                for i, src in enumerate(["Amazon", "Flipkart", "Ajio", "Google", "Amazon", "Ajio"])]


class FakeGemini:
    def parse_query(self, q):
        return ParsedQuery(category="dress", color="red", gender="women")

    def generate_platform_queries(self, products, platforms, gender=None):
        return {(p.id, d): "women red wrap dress" for p in products for d in platforms}

    def explain_tradeoffs(self, products, priorities):
        return {p.id: "note" for p in products}, f"summary for {len(priorities)} priorities"


class PassColor:
    async def filter_by_color(self, products, color):
        return products


class FakeMatcher:
    """Pretends Meesho candidates look nothing like the picks; others match."""

    async def filter_matches(self, candidates, references):
        out = []
        for c in candidates:
            if c.source_domain == "meesho.com":
                continue
            c = c.model_copy()
            c.visual_similarity_score = 0.9
            out.append(c)
        return out


@pytest.fixture()
def client_and_serp():
    store, serp = InMemorySessionStore(), FakeSerp()
    app = FastAPI()
    app.include_router(router)
    o = app.dependency_overrides
    o[get_store] = lambda: store
    o[get_serpapi_service] = lambda: serp
    o[get_gemini_service] = lambda: FakeGemini()
    o[get_color_validation_service] = lambda: PassColor()
    o[get_image_matching_service] = lambda: FakeMatcher()
    o[get_settings] = lambda: SETTINGS
    return TestClient(app), serp


def test_platforms_endpoint_lists_configured_retailers(client_and_serp):
    client, _ = client_and_serp
    ids = [p["id"] for p in client.get("/api/search/platforms").json()["platforms"]]
    assert ids == SETTINGS.target_retailers_list


def test_whole_journey(client_and_serp):
    client, serp = client_and_serp

    d = client.post("/api/search/discover", json={"query": "red dress for women"}).json()
    products = d["discovery_products"]
    assert len(products) == 6  # fewer than DISCOVERY_MIN is fine: real availability

    picks = [products[0]["id"], products[1]["id"]]
    prefs = client.post("/api/search/preferences", json={
        "session_id": d["session_id"], "selected_product_ids": picks,
        "priorities": ["lowest_price", "early_delivery"], "pincode": "411001",
        "selected_platforms": ["myntra.com", "meesho.com"],
    })
    assert prefs.status_code == 200

    res = client.post("/api/search/compare", json={"session_id": d["session_id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    compared = body["compared_products"]

    # Step 7 + 8: platform-name-first queries, one per (pick x platform), Gemini-written text
    assert sorted(q for q in serp.queries if q.split()[0] in {"Myntra", "Meesho"}) == [
        "Meesho women red wrap dress", "Meesho women red wrap dress",
        "Myntra women red wrap dress", "Myntra women red wrap dress"]

    # gender filter: no men's listing survives
    assert not any("Men red polo" in p["title"] for p in compared)

    # Step 9: Meesho candidates failed image match -> coverage says 0; Myntra has some, with scores
    cov = {c["id"]: c for c in body["platform_coverage"]}
    assert cov["meesho.com"]["candidates_found"] == 0 and cov["meesho.com"]["label"] == "Meesho"
    assert cov["myntra.com"]["candidates_found"] > 0
    assert all(p["visual_similarity_score"] == 0.9 for p in compared if p["source_domain"] == "myntra.com")

    # user's picks always present
    assert set(picks) <= {p["id"] for p in compared}

    # Step 5 + 10: every product has a delivery estimate and one bar per selected priority
    assert all(p["estimated_delivery_days"] for p in compared)
    for p in compared:
        assert set(p["priority_match"]) == {"lowest_price", "early_delivery"}

    # ranking order is best-first, size capped
    scores = [p["score"] for p in compared]
    assert scores == sorted(scores, reverse=True)
    assert len(compared) <= SETTINGS.COMPARISON_MAX_COUNT
    assert body["overall_summary"] == "summary for 2 priorities"


def test_unknown_platform_and_missing_preferences_are_rejected(client_and_serp):
    client, _ = client_and_serp
    d = client.post("/api/search/discover", json={"query": "red dress"}).json()
    bad = client.post("/api/search/preferences", json={
        "session_id": d["session_id"], "selected_product_ids": [d["discovery_products"][0]["id"]],
        "priorities": ["quality"], "pincode": "411001", "selected_platforms": ["evil.com"]})
    assert bad.status_code == 400
    early = client.post("/api/search/compare", json={"session_id": d["session_id"]})
    assert early.status_code == 400
    assert client.post("/api/search/compare", json={"session_id": "nope"}).status_code == 404
