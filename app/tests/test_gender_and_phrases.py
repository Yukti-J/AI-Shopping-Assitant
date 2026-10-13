from app.services.gender import classify_gender, infer_gender, matches_gender, normalize_gender
from app.services.platform_search import build_search_phrase


def test_women_is_never_mistaken_for_men():
    assert classify_gender("Women's Casual Top") == "women"
    assert classify_gender("Men Solid Polo") == "men"
    assert classify_gender("Unisex tee for men and women") is None


def test_matches_gender_only_drops_clear_opposites():
    assert matches_gender("Men Solid Polo", "women") is False
    assert matches_gender("Plain Cotton Top", "women") is True
    assert matches_gender("Anything", None) is True


def test_normalize_and_infer():
    assert normalize_gender("Female") == "women"
    assert normalize_gender("unisex") is None
    assert infer_gender(["Women Kurta", "Ladies Top"]) == "women"
    assert infer_gender(["Women Kurta", "Men Shirt"]) is None


def test_build_search_phrase_cuts_ad_copy_and_brand():
    phrase = build_search_phrase("AUSK Women's Casual Summer Polo Knit T-Shirt | Zip Collar Top | Half Sleeve")
    assert phrase == "Women's Casual Summer Polo Knit T-Shirt"


def test_build_search_phrase_adds_missing_gender():
    assert build_search_phrase("Red Floral Wrap Dress", gender="women").startswith("women ")
