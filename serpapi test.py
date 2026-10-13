"""
Test v3: does naturally mentioning a platform's name in the query text
(no site: operator) bias google_shopping results toward that platform?

e.g. "red dress myntra" or "red dress on myntra" instead of
"site:myntra.com red dress" (which we've now confirmed returns 0 results).

Usage:
    export SERPAPI_API_KEY=your_key_here
    python test_serpapi_keyword_bias.py
"""
import os
import sys
import time

import httpx

SERPAPI_ENDPOINT = "https://serpapi.com/search"
API_KEY = os.environ.get("SERPAPI_API_KEY", "")

if not API_KEY:
    print("ERROR: set SERPAPI_API_KEY in your environment first.")
    sys.exit(1)

BASE_QUERY = "women red floral wrap dress"

# (display name, fragment to match in `source` field, phrasing variants to try)
PLATFORMS = [
    ("Myntra", "myntra"),
    ("Ajio", "ajio"),
    ("Flipkart", "flipkart"),
]

VARIANTS = [
    "{q} {p}",
    "{q} on {p}",
    "{p} {q}",
    "{q} buy on {p}",
]


def run_query(q: str, timeout: float = 30.0, retries: int = 1) -> list[dict]:
    params = {
        "engine": "google_shopping",
        "q": q,
        "gl": "in",
        "hl": "en",
        "google_domain": "google.co.in",
        "api_key": API_KEY,
    }
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(SERPAPI_ENDPOINT, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("shopping_results", []) or []
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2)
                continue
    raise last_exc


def source_text(result: dict) -> str:
    return (result.get("source") or "").lower()


def main():
    print(f"Base query: {BASE_QUERY!r}\n")

    for display_name, fragment in PLATFORMS:
        print(f"=== {display_name} ===")
        for variant in VARIANTS:
            q = variant.format(q=BASE_QUERY, p=display_name)
            try:
                results = run_query(q)
            except httpx.HTTPError as exc:
                print(f"  {q!r} -> REQUEST FAILED: {exc}")
                continue

            total = len(results)
            on_target = sum(1 for r in results if fragment in source_text(r))
            pct = (on_target / total * 100) if total else 0
            print(f"  {q!r}")
            print(f"      total={total}  on_target={on_target}  ({pct:.0f}%)")
            if results[:2]:
                for r in results[:2]:
                    print(f"      - {r.get('title')!r} | source={r.get('source')!r}")
        print()

    print("Interpretation guide:")
    print("- rising on_target % across variants vs the earlier baseline (myntra was 5/40 ~12%)")
    print("  means keyword-biasing genuinely nudges the platform mix.")
    print("- flat/no improvement means this isn't a workable substitute either.")


if __name__ == "__main__":
    main()