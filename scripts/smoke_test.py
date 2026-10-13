"""
Phase 2 live smoke test (Step 11, manual half).

Runs the real journey against your RUNNING backend with your REAL API keys:
    discover -> pick 2 -> preferences -> compare
and prints a PASS/FAIL checklist plus a readable summary of the result.

Usage (backend must be running on :8000):
    python scripts/smoke_test.py
    python scripts/smoke_test.py "black sneakers for men" 411001
Options via env: API_BASE=http://localhost:8000

Cost: roughly 1 + (2 picks x N platforms) SerpAPI calls and a few dozen
Gemini calls per run. Use sparingly on a free quota.
"""
import json
import os
import sys

import httpx

API = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
QUERY = sys.argv[1] if len(sys.argv) > 1 else "red dress for women"
PINCODE = sys.argv[2] if len(sys.argv) > 2 else "411001"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = ""):
    results.append((ok, label))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))


def call(client, method, path, **kw):
    r = client.request(method, f"{API}{path}", timeout=180, **kw)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def main():
    with httpx.Client() as c:
        print(f"Backend: {API}\nQuery: {QUERY!r}  Pincode: {PINCODE}\n")

        print("1. Health")
        code, h = call(c, "GET", "/health")
        check(code == 200, "backend reachable")
        check(h.get("gemini_configured") is True, "GEMINI_API_KEY configured")
        check(h.get("serpapi_configured") is True, "SERPAPI_API_KEY configured")
        if code != 200:
            sys.exit(1)

        print("\n2. Platforms (Step 6)")
        code, p = call(c, "GET", "/api/search/platforms")
        platforms = [x["id"] for x in p.get("platforms", [])]
        check(code == 200 and len(platforms) >= 2, "platform list returned", ", ".join(platforms))

        print("\n3. Discover (Steps 2-4)")
        code, d = call(c, "POST", "/api/search/discover", json={"query": QUERY})
        check(code == 200, "discover ok", d.get("detail", "") if code != 200 else "")
        if code != 200:
            sys.exit(1)
        disc = d["discovery_products"]
        check(len(disc) >= 10, f"discovery set size {len(disc)} (target 20-35; fewer means a thin result pool)")
        check(len({x["source"] for x in disc}) >= 2, "multiple retailers in discovery set")
        print(f"     parsed: {json.dumps({k: v for k, v in d['parsed_query'].items() if v})}")

        print("\n4. Preferences (Steps 5-6)")
        picks = [x["id"] for x in disc[:2]]
        chosen = platforms[:3]
        code, pr = call(c, "POST", "/api/search/preferences", json={
            "session_id": d["session_id"], "selected_product_ids": picks,
            "priorities": ["best_value", "early_delivery"], "pincode": PINCODE, "selected_platforms": chosen})
        check(code == 200, "preferences saved", pr.get("detail", "") if code != 200 else "")

        print("\n5. Compare (Steps 7-10)  -- this is the slow one, 30-90s is normal")
        code, r = call(c, "POST", "/api/search/compare", json={"session_id": d["session_id"]})
        check(code == 200, "compare ok", r.get("detail", "") if code != 200 else "")
        if code != 200:
            sys.exit(1)
        comp = r["compared_products"]
        check(len(comp) >= 3, f"{len(comp)} products compared")
        check(set(picks) <= {x["id"] for x in comp}, "your picks are all in the comparison")
        check(all(x.get("estimated_delivery_days") for x in comp), "every product has a delivery estimate")
        check(all(set(x["priority_match"]) == {"best_value", "early_delivery"} for x in comp), "match-% present for each selected priority")
        check(any(x.get("visual_similarity_score") is not None for x in comp), "image matching produced scores (needs Gemini)")
        cov = {x["id"]: x["candidates_found"] for x in r["platform_coverage"]}
        check(sum(cov.values()) > 0, "at least one platform returned verified candidates", json.dumps(cov))
        scores = [x["score"] for x in comp]
        check(scores == sorted(scores, reverse=True), "sorted best-first")
        check(bool(r["overall_summary"]), "summary text present")

        print("\nTop results:")
        for i, x in enumerate(comp[:6], 1):
            pm = ", ".join(f"{k} {v:.0f}%" for k, v in x["priority_match"].items())
            vs = x.get("visual_similarity_score")
            print(f"  #{i} {x['source']:<10} ₹{x['price'] or 0:>7.0f}  {x['title'][:50]:<50} | {pm}"
                  + (f" | look {vs:.2f}" if vs is not None else ""))
        print(f"\nCoverage: {cov}\nSummary: {r['overall_summary']}")

    failed = [l for ok, l in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        sys.exit(1)
    print("Phase 2 smoke test PASSED")


if __name__ == "__main__":
    main()