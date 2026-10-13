"""Phase 2 Step 9: image matching decisions (match / no_match / unknown), no network."""
import asyncio

from app.models.schemas import Product
from app.services.image_matching import ImageMatchingService


def prod(pid, thumb="ok", ref=None):
    return Product(id=pid, title=pid, source="S", price=1.0, thumbnail_url=thumb, matched_from_product_id=ref)


class FakeMatcher(ImageMatchingService):
    def __init__(self, scores, threshold=0.75, enabled=True):
        self._enabled, self._threshold = enabled, threshold
        self._semaphore = asyncio.Semaphore(4)
        self._cache, self._image_cache = {}, {}
        self.scores, self.gemini_calls = scores, 0  # thumb url -> score (None = Gemini failure)

    async def _get_image(self, url):
        return None if url == "unreadable" else (url.encode(), "image/jpeg")

    def _ask_gemini(self, ref_img, cand_img):
        self.gemini_calls += 1
        return self.scores[cand_img[0].decode()]


def run(matcher, cands, refs):
    return asyncio.run(matcher.filter_matches(cands, refs))


REF = prod("ref", thumb="refimg")


def test_match_kept_with_score_and_nomatch_dropped():
    m = FakeMatcher({"good": 0.9, "bad": 0.3})
    out = run(m, [prod("c1", "good", "ref"), prod("c2", "bad", "ref")], [REF])
    assert [(p.id, p.visual_similarity_score) for p in out] == [("c1", 0.9)]


def test_threshold_is_inclusive():
    out = run(FakeMatcher({"edge": 0.75}), [prod("c", "edge", "ref")], [REF])
    assert len(out) == 1


def test_candidate_without_or_with_unreadable_image_is_dropped():
    out = run(FakeMatcher({}), [prod("a", None, "ref"), prod("b", "unreadable", "ref")], [REF])
    assert out == []


def test_our_side_failures_keep_candidate_as_unknown():
    # Gemini failure -> kept, score None
    out = run(FakeMatcher({"x": None}), [prod("c", "x", "ref")], [REF])
    assert [(p.id, p.visual_similarity_score) for p in out] == [("c", None)]
    # picked product's own image unreadable -> kept, unknown
    out = run(FakeMatcher({"x": 0.1}), [prod("c", "x", "ref")], [prod("ref", thumb="unreadable")])
    assert len(out) == 1 and out[0].visual_similarity_score is None


def test_disabled_service_passes_everything_through_unchanged():
    cands = [prod("c", "x", "ref")]
    assert run(FakeMatcher({}, enabled=False), cands, [REF]) == cands


def test_results_are_cached_per_pair():
    m = FakeMatcher({"good": 0.9})
    run(m, [prod("c", "good", "ref")], [REF])
    run(m, [prod("c", "good", "ref")], [REF])
    assert m.gemini_calls == 1
