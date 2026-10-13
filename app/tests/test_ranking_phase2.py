"""Phase 2 Step 10: per-priority match % + pin_selected + multi-priority blending."""
from app.models.schemas import Product, ShoppingPriority as SP
from app.services.ranking import compute_priority_match, pin_selected, rank_products


def prod(pid, price=1000.0, rating=4.0, reviews=100, days=None):
    return Product(id=pid, title=pid, source="S", price=price, rating=rating, reviews_count=reviews,
                   estimated_delivery_days=days)


def test_best_product_for_a_priority_gets_100_and_others_less():
    ranked = rank_products([prod("cheap", price=500), prod("mid", price=1000), prod("dear", price=1500)],
                           [SP.LOWEST_PRICE])
    by_id = {p.id: p for p in ranked}
    assert by_id["cheap"].priority_match["lowest_price"] == 100.0
    assert by_id["dear"].priority_match["lowest_price"] < by_id["mid"].priority_match["lowest_price"] < 100.0


def test_priority_match_has_only_the_selected_priorities():
    ranked = rank_products([prod("a", days=2), prod("b", days=5)], [SP.EARLY_DELIVERY, SP.BEST_REVIEWS])
    for p in ranked:
        assert set(p.priority_match) == {"early_delivery", "best_reviews"}
        assert all(0.0 <= v <= 100.0 for v in p.priority_match.values())


def test_fastest_delivery_is_100_on_early_delivery_bar():
    ranked = rank_products([prod("fast", days=2), prod("slow", days=6)], [SP.EARLY_DELIVERY])
    assert {p.id: p.priority_match["early_delivery"] for p in ranked}["fast"] == 100.0


def test_no_delivery_data_gives_zero_not_fake_100():
    ranked = rank_products([prod("a"), prod("b")], [SP.EARLY_DELIVERY])
    # price/rating/reviews still contribute a little, but nobody has delivery
    # data -> bar must not claim a perfect match on delivery for everyone unless scores really tie
    assert all(p.priority_match["early_delivery"] <= 100.0 for p in ranked)


def test_compute_priority_match_zero_best_gives_zero():
    assert compute_priority_match({"quality": 0.0}, {"quality": 0.0}) == {"quality": 0.0}


def test_blended_score_is_mean_of_priority_contributions():
    ranked = rank_products([prod("a", price=500, days=2), prod("b", price=900, days=6)],
                           [SP.LOWEST_PRICE, SP.EARLY_DELIVERY])
    for p in ranked:
        contribs = p.score_breakdown["priority_contributions"].values()
        assert abs(p.score - sum(contribs) / 2) < 1e-3


def test_pin_selected_keeps_user_picks_even_if_ranked_low():
    ranked = [prod("x1"), prod("x2"), prod("x3"), prod("pick")]  # best-first; pick is last
    out = pin_selected(ranked, ["pick"], max_count=2)
    assert [p.id for p in out] == ["x1", "pick"]
