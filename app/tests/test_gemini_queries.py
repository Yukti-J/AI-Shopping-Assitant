"""Phase 2 Step 8: Gemini platform-query generation (no network: fake model)."""
import json
from types import SimpleNamespace

from app.models.schemas import Product, ShoppingPriority
from app.services.gemini_service import GeminiService, _clean_query_phrase

PLATFORMS = {"myntra.com": "Myntra", "amazon.in": "Amazon"}


def product(pid="p1"):
    return Product(id=pid, title="Brand Women Red Floral Wrap Dress | extra", source="Google", price=999.0)


class FakeModel:
    def __init__(self, text=None, raises=False):
        self.text, self.raises, self.calls = text, raises, 0

    def generate_content(self, *_a, **_k):
        self.calls += 1
        if self.raises:
            raise RuntimeError("quota")
        return SimpleNamespace(text=self.text)


def svc(model, enabled=True):
    s = GeminiService.__new__(GeminiService)
    s._enabled, s._model = enabled, model
    return s


def test_maps_labels_back_to_domains_in_one_call():
    model = FakeModel(json.dumps({"queries": {"p1": {"Myntra": "red floral wrap dress women", "Amazon": "women red wrap dress"}}}))
    out = svc(model).generate_platform_queries([product()], PLATFORMS, "women")
    assert out == {("p1", "myntra.com"): "red floral wrap dress women", ("p1", "amazon.in"): "women red wrap dress"}
    assert model.calls == 1


def test_platform_name_is_stripped_and_unknown_ids_ignored():
    model = FakeModel(json.dumps({"queries": {"p1": {"Myntra": "Myntra red wrap dress"}, "zzz": {"Myntra": "ignored dress"}}}))
    out = svc(model).generate_platform_queries([product()], PLATFORMS)
    assert out == {("p1", "myntra.com"): "red wrap dress"}


def test_garbage_json_exception_and_disabled_all_return_empty():
    assert svc(FakeModel("not json")).generate_platform_queries([product()], PLATFORMS) == {}
    assert svc(FakeModel(raises=True)).generate_platform_queries([product()], PLATFORMS) == {}
    assert svc(None, enabled=False).generate_platform_queries([product()], PLATFORMS) == {}


def test_clean_query_phrase_rules():
    assert _clean_query_phrase("one", []) is None            # too short
    assert _clean_query_phrase(123, []) is None              # not a string
    assert len(_clean_query_phrase("a b c d e f g h i j k l", []).split()) == 10


def test_explain_tradeoffs_accepts_list_or_single_priority_without_gemini():
    s = svc(None, enabled=False)
    _, summary = s.explain_tradeoffs([product()], [ShoppingPriority.QUALITY, ShoppingPriority.LOWEST_PRICE])
    assert "quality" in summary and "lowest_price" in summary
    _, summary = s.explain_tradeoffs([product()], ShoppingPriority.QUALITY)
    assert "quality" in summary
