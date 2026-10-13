"""
Gemini is used ONLY for natural-language understanding and explanation
generation — never for deterministic filtering, ranking, or scoring.
That logic lives in ranking.py and must stay auditable and testable
without hitting an LLM.

Responsibilities:
1. parse_query(): free text -> ParsedQuery (structured filters only, as of
   Phase 2 — see Req 1). It no longer produces `search_queries` variants;
   the discover router sends the user's original query to SerpAPI directly,
   single call, no rewriting. The extracted fields (category/color/gender/
   style_keywords/occasion/min_price/max_price) still feed later Phase 2
   steps: color validation needs `color`, platform-query generation needs
   the rest.
2. explain_tradeoffs(): a ranked product list -> short natural-language
   trade-off narrative per product + an overall summary.

3. generate_platform_queries(): (Phase 2, Step 8) the user's picked products
   -> a short, platform-specific search phrase per (product, platform). One
   Gemini call covers every pair. It only WRITES search text; platform_search.py
   still prepends the platform name, filters results and does all retrieval,
   and falls back to its deterministic phrase builder for anything missing.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import google.generativeai as genai

from app.core.config import get_settings
from app.models.schemas import ParsedQuery, Product, ShoppingPriority

logger = logging.getLogger(__name__)

_QUERY_PARSE_SYSTEM_PROMPT = """You are a shopping query parser for an Indian e-commerce assistant.
Given a user's free-text shopping query, extract structured filters that
downstream steps (color validation, platform-query generation) will use.

Respond with ONLY a JSON object, no markdown fences, no preamble, matching
exactly this shape:
{
  "category": string or null,
  "subcategory": string or null,
  "color": string or null,
  "gender": string or null,
  "style_keywords": [string, ...],
  "occasion": string or null,
  "min_price": number or null,
  "max_price": number or null
}

Rules:
- If no price range is mentioned, leave min_price/max_price null.
- Keep style_keywords short (1-3 words each).

Note: do NOT generate search query strings here. The discover step now
sends the user's original query to the search API as-is, single call,
no query rewriting (Phase 2, Req 1).
"""

_PLATFORM_QUERY_SYSTEM_PROMPT = """You write search phrases for an Indian online-shopping assistant.
The shopper picked some products they like. For each product and each retailer
listed, write ONE short search phrase that would find the same kind of product
(same garment/item type, colour, pattern, cut and target gender) in that
retailer's catalogue.

Rules:
- 3 to 8 words per phrase.
- Do NOT include the retailer's name, the product's brand, prices, sizes,
  model numbers or marketing words ("premium", "best", "latest").
- Keep the target gender (women / men / kids) if the product has one.
- Adapt vocabulary lightly to the retailer (fashion-first stores such as
  Myntra and Ajio use fashion terms; Amazon and Flipkart use plain generic
  terms; Meesho uses simple everyday terms) but never change the product type.

Respond with ONLY a JSON object, no markdown fences, no preamble:
{
  "queries": {
    "<product_id>": {"<retailer name>": "<search phrase>", ...},
    ...
  }
}
"""

_TRADEOFF_SYSTEM_PROMPT = """You are a shopping advisor explaining trade-offs between products.
You will receive a JSON list of already-ranked products (with price, rating,
reviews_count, source, a numeric score, and priority_match: how close each
product is to the best option for each of the user's priorities, 0-100) and the
user's 1-3 stated shopping priorities. Your job is NOT to re-rank anything —
ranking is already decided.

For EACH product, write one concise sentence (max 30 words) explaining what
you'd trade off by picking it relative to the others (e.g. "Cheapest of the
group but has fewer reviews than the top-rated options").

Mention the user's priorities where relevant (e.g. "strong on delivery speed
but weaker on reviews"). Then write one overall_summary paragraph (max 80
words) synthesizing the comparison across ALL of the user's stated priorities.

Respond with ONLY a JSON object, no markdown fences:
{
  "product_notes": {"<product_id>": "<one sentence>", ...},
  "overall_summary": "<paragraph>"
}
"""


class GeminiService:
    def __init__(self):
        settings = get_settings()
        self._enabled = settings.has_gemini_key
        self._model_name = settings.GEMINI_MODEL
        if self._enabled:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._model = genai.GenerativeModel(self._model_name)
        else:
            self._model = None
            logger.warning("GEMINI_API_KEY not set — GeminiService running in fallback mode.")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def parse_query(self, raw_query: str) -> ParsedQuery:
        if not self._enabled:
            return self._fallback_parsed_query(raw_query)

        try:
            prompt = f"{_QUERY_PARSE_SYSTEM_PROMPT}\n\nUser query: \"{raw_query}\""
            response = self._model.generate_content(prompt)
            data = _safe_json_parse(response.text)
            if data is None:
                logger.warning("Gemini query parse returned non-JSON; using fallback.")
                return self._fallback_parsed_query(raw_query)
            return ParsedQuery(**data)
        except Exception as exc:  # noqa: BLE001 — external API, want broad catch + fallback
            logger.exception("Gemini parse_query failed: %s", exc)
            return self._fallback_parsed_query(raw_query)

    def explain_tradeoffs(
        self, products: list[Product], priorities: "list[ShoppingPriority] | ShoppingPriority"
    ) -> tuple[dict[str, str], str]:
        """Returns (product_id -> note, overall_summary).

        Phase 2 (Step 11 polish): takes the full 1-3 priority list, not just
        the primary one. A single ShoppingPriority is still accepted.
        """
        if isinstance(priorities, ShoppingPriority):
            priorities = [priorities]
        if not self._enabled or not products:
            return self._fallback_tradeoffs(products, priorities)

        try:
            compact = [
                {
                    "id": p.id,
                    "title": p.title,
                    "price": p.price,
                    "rating": p.rating,
                    "reviews_count": p.reviews_count,
                    "source": p.source,
                    "estimated_delivery_days": p.estimated_delivery_days,
                    "score": p.score,
                    "priority_match": p.priority_match,
                }
                for p in products
            ]
            prompt = (
                f"{_TRADEOFF_SYSTEM_PROMPT}\n\n"
                f"User priorities: {', '.join(pr.value for pr in priorities)}\n\n"
                f"Products: {json.dumps(compact)}"
            )
            response = self._model.generate_content(prompt)
            data = _safe_json_parse(response.text)
            if not data:
                return self._fallback_tradeoffs(products, priorities)
            return data.get("product_notes", {}), data.get("overall_summary", "")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gemini explain_tradeoffs failed: %s", exc)
            return self._fallback_tradeoffs(products, priorities)

    def generate_platform_queries(
        self,
        products: list[Product],
        platforms: dict[str, str],
        gender: Optional[str] = None,
    ) -> dict[tuple[str, str], str]:
        """Phase 2 Step 8. `platforms` maps domain -> label ({"myntra.com": "Myntra"}).

        Returns {(product_id, platform_domain): phrase}. Anything Gemini
        skipped or garbled is simply absent, and the caller
        (platform_search.py) falls back to its deterministic phrase for that
        pair — so this method can never make a search worse than "no Gemini".
        Never raises. Synchronous (like the rest of this class): call it via
        asyncio.to_thread from async code.
        """
        if not self._enabled or not products or not platforms:
            return {}

        try:
            compact = [
                {"id": p.id, "title": p.title, "brand": p.brand, "price": p.price}
                for p in products
            ]
            prompt = (
                f"{_PLATFORM_QUERY_SYSTEM_PROMPT}\n\n"
                f"Target gender (may be null): {gender}\n"
                f"Retailers: {json.dumps(list(platforms.values()))}\n"
                f"Products: {json.dumps(compact)}"
            )
            response = self._model.generate_content(prompt)
            data = _safe_json_parse(response.text)
            if not data or not isinstance(data.get("queries"), dict):
                logger.warning("Gemini platform-query response had no usable 'queries'; using fallback phrases.")
                return {}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gemini generate_platform_queries failed: %s", exc)
            return {}

        label_to_domain = {label.lower(): domain for domain, label in platforms.items()}
        result: dict[tuple[str, str], str] = {}
        valid_ids = {p.id for p in products}
        for product_id, per_platform in data["queries"].items():
            if product_id not in valid_ids or not isinstance(per_platform, dict):
                continue
            for label, phrase in per_platform.items():
                domain = label_to_domain.get(str(label).strip().lower())
                cleaned = _clean_query_phrase(phrase, platforms.values())
                if domain and cleaned:
                    result[(product_id, domain)] = cleaned
        return result

    # ---------------- fallbacks (no API key / API failure) ----------------

    @staticmethod
    def _fallback_parsed_query(raw_query: str) -> ParsedQuery:
        """Deterministic, dumb-but-functional fallback so the app degrades
        gracefully instead of breaking when Gemini is unavailable.

        Phase 2: no longer populates `search_queries` — the router sends
        `raw_query` straight to SerpAPI regardless of whether this fallback
        or the real Gemini parse ran.
        """
        return ParsedQuery(
            style_keywords=raw_query.split()[:3],
        )

    @staticmethod
    def _fallback_tradeoffs(
        products: list[Product], priorities: list[ShoppingPriority]
    ) -> tuple[dict[str, str], str]:
        notes = {}
        for p in products:
            bits = []
            if p.price is not None:
                bits.append(f"₹{p.price:.0f}")
            if p.rating is not None:
                bits.append(f"{p.rating}★")
            if p.reviews_count is not None:
                bits.append(f"{p.reviews_count} reviews")
            notes[p.id] = f"{p.source}: " + ", ".join(bits) if bits else p.source
        summary = (
            f"Showing {len(products)} options ranked for {', '.join(repr(pr.value) for pr in priorities)}. "
            "Gemini explanations are unavailable right now, so trade-offs above "
            "are shown as raw price/rating/review signals instead."
        )
        return notes, summary


def _safe_json_parse(text: str) -> Optional[dict]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return None


_MAX_QUERY_WORDS = 10


def _clean_query_phrase(phrase: object, platform_labels) -> Optional[str]:
    """Defensive clean-up of a Gemini-written phrase: strings only, platform
    names stripped (the code prepends the platform itself), whitespace
    collapsed, capped at 10 words. Returns None if nothing usable is left."""
    if not isinstance(phrase, str):
        return None
    text = phrase.replace("\u2019", "'")
    for label in platform_labels:
        text = re.sub(rf"\b{re.escape(label)}\b", " ", text, flags=re.IGNORECASE)
    words = re.sub(r"[\"\n\r]", " ", text).split()
    if len(words) < 2:
        return None
    return " ".join(words[:_MAX_QUERY_WORDS])