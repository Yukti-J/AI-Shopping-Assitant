"""
Deterministic gender helpers for relevance filtering in the compare stage.

Why this exists: a search for "casual tops for women" must never surface
men's t-shirts in the final comparison. Google Shopping titles usually say
who a product is for ("Women's", "Men Solid Polo"), so we can check that
with plain word matching — no LLM, fully testable.

Rules of thumb (kept deliberately conservative):
- Only EXACT words count, so "Women" is never mistaken for "men".
- A title that mentions both genders, or neither, is "unknown" and is NOT
  filtered out — we only drop a product when it clearly targets the other
  gender.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

WOMEN_WORDS = frozenset({"women", "woman", "womens", "ladies", "lady", "girl", "girls", "female", "females"})
MEN_WORDS = frozenset({"men", "man", "mens", "boy", "boys", "male", "males", "gents", "gentlemen"})
ALL_GENDER_WORDS = WOMEN_WORDS | MEN_WORDS

_WORD_RE = re.compile(r"[a-z]+")


def words(text: str) -> list[str]:
    """Lowercase letter-only words: "Women's Top" -> ["women", "s", "top"]."""
    return _WORD_RE.findall(text.replace("’", "'").lower())


def classify_gender(text: str) -> Optional[str]:
    """'women' or 'men' if the text clearly targets one gender, else None
    (neither mentioned, or both mentioned -> unisex/unknown)."""
    found = set(words(text))
    is_women = bool(found & WOMEN_WORDS)
    is_men = bool(found & MEN_WORDS)
    if is_women and not is_men:
        return "women"
    if is_men and not is_women:
        return "men"
    return None


def normalize_gender(value: Optional[str]) -> Optional[str]:
    """Maps whatever Gemini put in ParsedQuery.gender ('Women', 'female',
    "women's", 'unisex', None...) to 'women' / 'men' / None."""
    if not value:
        return None
    return classify_gender(value)


def infer_gender(titles: Iterable[str]) -> Optional[str]:
    """Fallback when the query itself didn't state a gender: if the products
    the user picked all clearly target the same gender, use that one."""
    classes = {classify_gender(t) for t in titles} - {None}
    return classes.pop() if len(classes) == 1 else None


def matches_gender(title: str, gender: Optional[str]) -> bool:
    """False only when `title` clearly targets the OPPOSITE gender."""
    if gender is None:
        return True
    found = classify_gender(title)
    return found is None or found == gender