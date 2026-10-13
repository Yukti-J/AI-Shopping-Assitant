# AI Shopping Decision Assistant — Project Context

*Last updated: **Phase 2 COMPLETE** — Steps 1-11 of 11 implemented and covered by
automated tests (34 passing). The only remaining Phase 2 action is running the live
smoke test (`scripts/smoke_test.py`) against your real API keys — see §18.*

This is the persistent source of truth for this project. Update it whenever
an architectural or implementation decision changes — don't let it drift
from what the code actually does.

**If you're picking this project up in a new chat:** this file describes
the system as it exists in the codebase RIGHT NOW — a mix of Phase 1
(still true for the untouched parts) and Phase 2 Steps 1-7 (implemented)
layered on top. The full Phase 2 plan — requirements, architecture,
file-by-file changes, and the step-by-step rollout order — lives in a
separate file, **`Phase2_architecture.md`**, produced from a detailed
planning discussion (including two things that were actually tested
empirically, not just theorized — see that doc's §4). **Check §18 below
before touching any Phase 2 file** — it says exactly which of the 11 steps
are done, so you don't re-do finished work or build ahead of what's
actually landed.

---

## 1. Project Vision

Not a shopping search engine (Google Shopping / SERP clone). This is a
**decision assistant**. The differentiator:

- Google Shopping answers: *"What products match my search?"*
- This assistant answers: *"What should I consider buying, given what I
  like, my priorities, budget, reviews, price differences, and delivery
  needs?"*

The system explains **trade-offs** across cross-retailer options rather
than declaring one "best" product.

## 2. Core User Journey (current state: Phase 1 + Phase 2 Steps 1-7)

```
Discover -> Learn Preferences -> Search Across Market -> Compare -> Explain Trade-offs -> Decide
```

1. **Discover** — user enters a free-text query (e.g. "red dress"). A
   single SerpAPI call (no Gemini query rewriting) retrieves candidates,
   which are color-validated against the query's target color (Gemini
   vision, when a color was mentioned) before a diversity pick of 20-35
   options (was a fixed 4-5 in Phase 1).
2. **Learn Preferences** — user selects 1-5 liked products (was 1-2),
   states 1-3 shopping priorities including a new Early Delivery option
   (was exactly one), picks which platforms to search (list fetched from
   `GET /api/search/platforms`), and gives a pincode,
   which now actually feeds a delivery estimate (was collected-but-unused
   in Phase 1).
3. **Search Across Market** — **platform-targeted since Step 7**: for each
   selected product x selected platform, searches that platform (platform
   name first in the query), keeps only that platform's listings, and takes
   the top few. Queries are title-based for now (Gemini-written queries are
   Step 8); candidates aren't image-verified yet (Step 9).
4. **Compare** — dedupes and ranks relevant products on price, rating,
   review count, AND now delivery speed, with the weights for however many
   priorities (1-3) the user picked blended together (was a single fixed
   weight set).
5. **Explain Trade-offs** — natural-language explanation of what you gain
   / give up with each option. Currently still narrates around the user's
   *primary* (first-selected) priority only — multi-priority-aware
   explanation text isn't in Phase 2's scope for any step, so this is a
   known, accepted gap, not a bug.
6. **Decide** — user picks with full context, not just a sorted list.
   Per-priority match-% bar chart (Phase 2 Req 8) is not built yet — see
   §18 Step 10.

**Phase 2 additions to the journey (all implemented):** Gemini-written per-platform
queries, cross-platform image-similarity verification, and a per-priority match-% bar
chart on the comparison screen. See §18 for the authoritative status.

---

## 3. Current Phase

**Phase 1 — MVP — complete.**

**Phase 2 — complete (code + automated tests).** All 11 steps are built:
schema/config, SERP simplification, discovery sizing, color validation,
multi-priority + early-delivery + pincode estimates, platform list endpoint,
platform-targeted retrieval, Gemini-written platform queries (Step 8),
cross-platform image matching (Step 9), per-priority match-% bars (Step 10),
and the end-to-end tests + live smoke script (Step 11). Phase 2 is
"concluded" once `python scripts/smoke_test.py` passes against live keys.

Next phase: **Phase 3** (see §15). Do not start it before the live smoke test passes.

## 4. Completed Functionality

**Backend — Phase 1 + Phase 2 Steps 1-7:**
- [x] `POST /api/search/discover` — NL query -> Gemini parses intent
      (structured filters only, no more query-variant generation) ->
      single SerpAPI call (~40 raw results) -> normalize -> Gemini-vision
      color validation (when the query named a color) -> dedupe -> diverse
      20-35 option discovery set -> session created
- [x] `POST /api/search/preferences` — records 1-5 selected products,
      1-3 shopping priorities (now including Early Delivery), pincode, and
      selected platforms (validated against `TARGET_RETAILERS`, stored, and
      used by `/compare`) against the session
- [x] `POST /api/search/compare` — platform-targeted search (one SerpAPI
      call per selected product x selected platform, source-filtered) +
      the selected products themselves -> dedupe -> pincode-based delivery estimation
      -> deterministic multi-priority-blended ranking -> Gemini generates
      per-product trade-off notes + an overall summary (still narrated
      around the primary priority only, see §2)
- [x] In-memory session store (discover -> preferences -> compare state),
      now also holding the priorities list and selected platforms
- [x] Graceful degradation: app still runs and returns sensible responses
      if `GEMINI_API_KEY` or `SERPAPI_API_KEY` are missing (see §12) —
      color validation also degrades gracefully (passes everything through
      unfiltered rather than failing) if no Gemini key is set
- [x] `/health` endpoint reporting which API keys are configured

**Frontend — caught up to Steps 1-7 (no UI change needed for Step 7):**
- [x] `ai-shopping-assistant-frontend/` — React + Vite app (`src/main.jsx`,
      single-file, zero extra UI dependencies), updated for: a 1-5 product
      selection cap (was 1-2), multi-select priorities capped at 3
      (including Early Delivery), a platform-selection step, and
      multi-priority display on the comparison screen.
- [x] **Platform list now comes from the backend (Step 6).** The old
      hardcoded `PLATFORMS` constant is gone; `main.jsx` fetches
      `GET /api/search/platforms` on load (with loading/error+retry states),
      so the UI can't offer a platform the backend doesn't support.

**Phase 2 Steps 8-11 (added):**
- [x] Gemini writes one search phrase per (picked product x platform) in a single
      call (`GeminiService.generate_platform_queries`); `platform_search.py` still
      prepends the platform name, filters, and falls back to deterministic phrases.
- [x] `image_matching.py`: Gemini-vision look-alike check of each platform candidate
      against the pick it came from. Sets `visual_similarity_score`; drops below
      `IMAGE_SIMILARITY_THRESHOLD`. Unverifiable (outage / no key) = kept, not dropped.
- [x] `rank_products` fills `Product.priority_match` (0-100 per selected priority,
      relative to the best candidate for that priority); frontend shows bars.
- [x] `/compare` is fully wired: gender filter, `platform_coverage` (counted after
      image matching), user picks pinned into the result (`pin_selected`) and placed
      first in the pool so dedup can't remove them.
- [x] `explain_tradeoffs` now takes ALL 1-3 priorities (previously primary only).

**Not yet built (original list, now outdated for Phase 2):** shortlist/save functionality, persistent storage,
automated test suite (all deliberately deferred, Phase 1 scope); platform
selection actually affecting retrieval, platform-specific search queries,
cross-platform image-similarity matching, per-priority match-% bar chart
(all Phase 2 Steps 6-10, not started — see §18).

## 5. Current Architecture

```
React frontend (ai-shopping-assistant-frontend/src/main.jsx)
   |  (calls all 3 endpoints below)
   v
FastAPI routers (app/routers/search.py)
   |
   +--> GeminiService (app/services/gemini_service.py)
   |     - parse_query(): free text -> ParsedQuery (structured filters
   |       ONLY as of Phase 2 — no more generated search_queries; the
   |       router sends the user's original query to SerpAPI directly)
   |     - explain_tradeoffs(): ranked product list -> per-product notes +
   |       overall summary (still single-priority, see §2)
   |     - NEVER does ranking/filtering — LLM output is explanatory only
   |     - generate_platform_queries() planned for Step 8, not built yet
   |  platform_search.py — Step 7: platform-name-first queries + source filter
   |
   +--> SerpApiService (app/services/serpapi_service.py)
   |     - search_shopping(): single-query retrieval, now actually passes
   |       `num` to the API (discover calls it with ~40)
   |     - search_multiple(): still used by the compare stage's query
   |       expansion; no longer used by discover
   |     - treated as a retrieval mechanism, not a recommendation engine
   |
   +--> ColorValidationService (app/services/color_validation.py) — NEW
   |     - Gemini-vision check: does a candidate's thumbnail actually look
   |       like the query's target color? Runs between normalize and
   |       dedupe in discover(). No-ops if no color was parsed or if
   |       GEMINI_API_KEY is missing (graceful degradation).
   |
   +--> normalization.py — raw SerpAPI dict -> common Product schema
   |     (the ONLY module that knows SerpAPI's raw field names)
   |
   +--> dedup.py — exact-id dedup, then near-duplicate title+price+source
   |     heuristic (SequenceMatcher-based)
   |
   +--> DeliveryEstimationService (app/services/delivery_estimation.py) — NEW
   |     - static pincode-tier + retailer-speed heuristic ->
   |       estimated_delivery_days. No network calls; always
   |       DeliveryConfidence.ESTIMATED, never CONFIRMED. Runs in
   |       compare(), right before ranking.
   |
   +--> ranking.py — deterministic, auditable scoring (NOT LLM-driven)
   |     - priority-weighted formula over normalized price/rating/reviews/
   |       delivery (delivery column added in Phase 2)
   |     - rank_products() now takes 1-3 priorities and blends their
   |       weight tuples by averaging each priority's own full score —
   |       score_breakdown exposes each priority's contribution
   |       separately, not just the merged number
   |     - select_diverse_discovery_set(): round-robins across retailers
   |       + price spread; range is now 20-35 (was a fixed 4-5)
   |
   +--> InMemorySessionStore (app/storage/memory_store.py)
         - holds session state across the 3-step flow, now including the
           priorities list and selected_platforms
         - explicitly a stand-in for Redis; single interface, swappable
```

**Design principle enforced throughout:** Retrieval -> Normalization ->
Dedup -> Ranking -> Recommendation are separate stages/modules. Gemini
touches only NLU (query parsing), narrow visual QA (color validation), and
explanation generation — it never decides ranking or filtering. This keeps
ranking testable/auditable without hitting an LLM, and keeps costs/latency
predictable. **Phase 2 Steps 1-5 extend this same separation of concerns
rather than replacing it** — color validation and delivery estimation are
each their own module, not folded into an existing one, for the same
reason ranking was always separate from retrieval.

## 6. Database / Schema Decisions

- **No PostgreSQL or Redis in Phase 1 or Phase 2.** Nothing yet needs to
  persist across process restarts (no user accounts, no history) — adding
  infra with no current purpose would violate "don't add infrastructure
  just for the sake of using it." Phase 2 confirms this stays true (see
  `Phase2_architecture.md` §7's closing note) — no schema migrations are
  part of Phase 2.
- Session state (discover -> preferences -> compare) is held in
  `InMemorySessionStore`, a single-process, TTL-based in-memory dict
  behind one interface (`app/storage/memory_store.py`).
- **When to introduce Postgres:** Phase 3 (persistent user preferences,
  history, price alerts) is the natural trigger — that's when data needs
  to survive restarts and be queryable.
- **When to introduce Redis:** if/when this needs to run across multiple
  worker processes/instances (session state would break with in-memory
  storage + multiple workers). Swap is scoped to one file.
- **Product schema** (`app/models/schemas.py::Product`) is the common
  normalized shape every retailer/source result is mapped into. This is
  the seam Phase 2's new fields (`estimated_delivery_days`,
  `visual_similarity_score`, `matched_from_product_id`, `priority_match`)
  extend, not replace.

## 7. API Endpoints (Phase 1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Reports API key configuration status |
| GET | `/` | Basic service info |
| GET | `/api/search/platforms` | Phase 2 Step 6: searchable platforms (`id` = domain, `label` = display name), from `TARGET_RETAILERS` |
| POST | `/api/search/discover` | Step 1: query -> 4-5 diverse options + `session_id` |
| POST | `/api/search/preferences` | Step 2: record selection + priority + pincode |
| POST | `/api/search/compare` | Step 3: ~10-12 ranked, compared products + trade-off explanations |

Phase 2 added `GET /api/search/platforms` (Step 6, done) and changes the
request/response shape of `preferences` and `compare` — see `Phase2_architecture.md` §3, §6,
§7.

Full current request/response schemas: see `app/models/schemas.py` or
`/docs` (Swagger UI) once running.

## 8. Important Design Decisions and Why (Phase 1)

- **Gemini never ranks or filters.** Ranking lives in deterministic Python
  (`ranking.py`) so it's unit-testable, free to run, and its output is
  always explainable via `score_breakdown`. Gemini only explains a
  ranking that's already been decided. **Phase 2 keeps this rule intact**
  even as ranking grows to handle multiple priorities.
- **SerpAPI is retrieval-only.** `serpapi_service.py` has zero
  ranking/filtering logic by design — it just returns raw candidate
  results for `normalization.py` to process.
- **Diversity heuristic for discovery (not just top-N by relevance).**
  `select_diverse_discovery_set()` round-robins across retailers and
  spreads by price so the initial options are genuinely different
  choices, not near-identical listings from one retailer.
- **Near-duplicate dedup is same-retailer-only.** Two listings from
  *different* retailers are never deduped, even if titles match closely —
  that's the whole point of cross-retailer comparison.
- **Graceful degradation over hard failure.** Missing `GEMINI_API_KEY`
  degrades query parsing/explanations to deterministic fallbacks rather
  than crashing; missing `SERPAPI_API_KEY` returns a clear 422 rather than
  a stack trace.
- **In-memory sessions over Postgres/Redis** — see §6.
- **Delivery estimates are best-effort, not fabricated.** SerpAPI doesn't
  reliably return pincode-aware delivery dates. Rather than inventing a
  number, `Product.delivery_confidence` is explicitly `UNKNOWN` /
  `ESTIMATED` / `CONFIRMED`. Phase 2 adds an actual pincode-based estimate
  (still `ESTIMATED`, never fabricated as `CONFIRMED`) — see
  `Phase2_architecture.md` §3b.

## 9. Gemini Prompts / Schemas

Both prompts live in `app/services/gemini_service.py` as module-level
constants (`_QUERY_PARSE_SYSTEM_PROMPT`, `_TRADEOFF_SYSTEM_PROMPT`) —
kept in code (not a separate prompt-management system) since there are
still few enough prompts that a versioning system isn't justified yet.

- **Query parsing** — free text -> JSON matching `ParsedQuery`
  (category, color, gender, style_keywords, occasion, min/max price,
  search string(s)). **Phase 2 changes this:** `search_queries` (plural,
  2-4 Gemini-generated variants) is dropped — the discover stage now sends
  the user's original query to SerpAPI as-is. Gemini gains a *new* method,
  `generate_platform_queries()`, used only in the compare stage — see
  `Phase2_architecture.md` §5.
- **Trade-off explanation** — ranked product list (with scores already
  computed) + stated priority -> JSON with a one-sentence `product_notes`
  per product id and one `overall_summary` paragraph. Explicitly told NOT
  to re-rank. Phase 2 doesn't change this prompt's job, just what feeds
  into the ranking it explains.
- Both use `_safe_json_parse()` to strip markdown fences defensively and
  fall back to deterministic logic on any parse failure.

## 10. SerpAPI Search Strategy (current: Phase 1 compare stage + Phase 2 discover stage)

- **Discovery stage (Phase 2, implemented):** a single direct
  `search_shopping()` call with the user's raw query, requesting ~40 raw
  results (`DISCOVERY_MAX_COUNT + 5`). Normalized, color-validated (when a
  color was parsed), deduped, then diversity selection picks 20-35. No
  more Gemini-generated query variants or `search_multiple()` fan-out at
  this stage — see `Phase2_architecture.md` §2a.
- **Compare stage (Step 7):** `platform_search.py::search_platforms()` runs
  one `search_shopping()` call per (selected product x selected platform),
  throttled by `PLATFORM_SEARCH_CONCURRENCY`. Query = `"{platform label}
  {product title}"` (platform name first — `QUERY_TEMPLATE`). Results are
  normalized, then filtered to the platform via `source_domain ==
  platform`, capped at `PLATFORM_CANDIDATES_PER_QUERY`, and tagged with
  `matched_from_product_id` (provenance only; Step 9 verifies visually).
  The selected `Product` objects are still added to the pool directly. The
  old Phase 1 "title + style keywords" expansion is gone. Worst case is
  5 x 5 = 25 SerpAPI calls per compare — watch the SerpAPI quota.
- **Engine:** `google_shopping` via SerpAPI. Retailer targeting
  (`TARGET_RETAILERS` in config) is currently used only to *tag* a
  result's `source_domain` post-hoc — SerpAPI's Google Shopping engine
  does not support hard retailer filtering via the documented `site:`
  operator either (**confirmed by direct testing during Phase 2
  planning** — it returns zero results for every platform tried; see
  `Phase2_architecture.md` §4). The workaround that *does* work
  (platform-name-first query phrasing + a source filter) is implemented in
  `platform_search.py` (Step 7).

## 11. Ranking Logic (current: Phase 2 Step 5 implemented)

`app/services/ranking.py::rank_products(products, priorities)`:

- Normalizes price (inverted — lower price = higher sub-score), rating,
  review count, AND delivery days (inverted, new in Phase 2) to [0,1]
  within the candidate pool. Delivery days come from
  `delivery_estimation.py`, run just before ranking in `compare()`.
- Applies priority-specific weights:

  | Priority | price weight | rating weight | reviews weight | delivery weight | notes |
  |---|---|---|---|---|---|
  | `lowest_price` | 0.75 | 0.15 | 0.10 | 0.00 | |
  | `best_value` | 0.40 | 0.35 | 0.25 | 0.00 | balanced |
  | `premium` | 0.05 | 0.55 | 0.15 | 0.00 | + up to 0.25 bonus for being in the upper price band (price as a *positioning signal*, not a penalty) |
  | `quality` | 0.10 | 0.55 | 0.35 | 0.00 | |
  | `best_reviews` | 0.10 | 0.30 | 0.60 | 0.00 | |
  | `early_delivery` | 0.10 | 0.15 | 0.05 | 0.70 | **new in Phase 2** |

- **Multi-priority blending (Phase 2, implemented):** `rank_products()`
  takes 1-3 priorities. Each selected priority contributes its own full
  weighted score for a product; the final `.score` is the MEAN of those.
  Since every weight row sums to 1.0, this is mathematically identical to
  averaging the weight tuples themselves — verified directly in testing.
  `score_breakdown.priority_contributions` shows each priority's own score
  separately, so a blended ranking is still fully auditable.
- Every scored `Product` carries `score_breakdown` (component scores, each
  priority's own contribution, and the blend method) so a ranking is
  always auditable/explainable.
- Products missing price/rating/reviews/delivery score 0 on that
  sub-component rather than being excluded.

**Done (Step 10):** `priority_match`
percentage-per-priority for the comparison bar chart. The
`_priority_contribution()` helper added in Step 5 was deliberately written
to be directly reusable for this — see that function's docstring in
`ranking.py`.

## 12. Environment Variables / Configuration

All in `app/core/config.py` (loaded from `.env` via pydantic-settings).
See `.env.example` for the canonical list. Required:

- `GEMINI_API_KEY` — required for real NLU/explanations (app runs without
  it, degraded)
- `SERPAPI_API_KEY` — required for any product retrieval at all

Optional/tuning: `GEMINI_MODEL`, `SERPAPI_COUNTRY`, `SERPAPI_LANGUAGE`,
`TARGET_RETAILERS`, `DISCOVERY_MIN_COUNT`, `DISCOVERY_MAX_COUNT`,
`COMPARISON_MIN_COUNT`, `COMPARISON_MAX_COUNT`, `SESSION_TTL_SECONDS`,
`IMAGE_SIMILARITY_THRESHOLD`.

**Implemented in Phase 2 Step 1:** `DISCOVERY_MIN_COUNT`/
`DISCOVERY_MAX_COUNT` (20/35 by default) replaced the single
`DISCOVERY_RESULT_COUNT`. `IMAGE_SIMILARITY_THRESHOLD` (0.75 default) is
defined and ready, but not yet read by any code — the image-matching
module that uses it is Step 9, not started. No new external API keys are
required for Phase 2 as currently scoped (the SerpAPI-based approach needs
no new accounts — official retailer APIs are deferred to Phase 3).

## 13. Known Limitations (current codebase: Phase 1 + Phase 2 Steps 1-7)

1. **No persistent storage.** Session state is lost on server restart and
   doesn't scale beyond one process (in-memory dict). Acceptable for
   local/demo use; Phase 2 does not change this (see §6).
2. ~~**Delivery info is collected but not used.**~~ **FIXED in Phase 2
   Step 5.** `delivery_estimation.py`'s pincode-tier + retailer-speed
   heuristic now populates `estimated_delivery_days` in `compare()`, and
   `EARLY_DELIVERY` ranking actually uses it. Still a heuristic, not a
   live carrier quote — `delivery_confidence` stays `ESTIMATED`, never
   `CONFIRMED`, on purpose (see `Phase2_architecture.md` §3b).
3. **Retailer targeting is still best-effort — NOT yet addressed.** Can't
   force SerpAPI's Google Shopping engine to return specifically
   Amazon/Myntra/Flipkart/AJIO/Meesho — we surface and label whatever
   Google's shopping index returns. The fix (platform-name-first phrasing
   + `source` filter, tested to reach 100% on-target in sampling — see
   `Phase2_architecture.md` §4) is implemented in Step 7 (`platform_search.py`). It
   improves platform targeting but is still best-effort: Google may return
   few or no listings for a platform, so compare can end up with fewer
   candidates than `COMPARISON_MIN_COUNT`. The exact query phrasing is a
   first implementation (`QUERY_TEMPLATE`) — verify it against the sampling
   notes in `Phase2_architecture.md` §4. Candidates ARE now image-verified (Step 9), but
   that is a Gemini visual judgement, not a guarantee.
4. **Dedup is heuristic, not embedding-based — still true, not yet
   addressed.** Same-retailer near-dupes are caught via title similarity +
   price closeness; near-identical products across *different* retailers
   are intentionally NOT deduped (that's the comparison point). **Phase 2
   will add real image-based similarity matching** as a *separate* step in
   the compare stage (local CLIP-style embeddings, not a Google Lens
   dependency — that option was evaluated and deliberately not adopted,
   see `Phase2_architecture.md` §5) — this is Step 9, now done via Gemini vision. It
   won't replace the existing title/price dedup heuristic, it'll add a new
   cross-platform matching capability on top of it.
5. **Products missing price/rating/reviews aren't excluded from
   ranking**, they just score near-zero on the missing sub-components —
   still true in Phase 2's ranking design; worth revisiting later.
6. **No automated test suite yet** — validated via manual smoke tests
   (mocked SerpAPI responses) during the build.
7. **No shortlist/save functionality implemented** — deprioritized in
   favor of a working core loop first; not part of Phase 2 either.

## 14. Known Bugs

None known at time of writing. Flagging here proactively for future
updates: if `rank_products()` is ever called with an empty candidate
list, it returns `[]` safely; if `select_diverse_discovery_set()` gets
fewer candidates than requested, it returns whatever's available rather
than erroring — verify this still holds after any refactor (Phase 2
changes this function's signature — see `Phase2_architecture.md` §2c).

## 15. Future Phases

- **Phase 2 — fully architected, see `Phase2_architecture.md`.**
  SERP simplification (single query, no Gemini rewrite), image-based
  color validation, a wider discovery set (20-35), multi-priority
  selection (1-3, including a new Early Delivery priority), pincode-based
  delivery estimation, user-selectable platforms for the compare stage,
  Gemini-generated per-platform queries, cross-platform image-similarity
  matching, and a per-priority match-% bar chart. Two key technical
  decisions were reached by **direct testing**, not assumption: (a)
  SerpAPI's `site:` operator does not work for retailer targeting, but
  platform-name-first query phrasing does; (b) Google Lens image search
  was evaluated as a possible matching mechanism and deliberately not
  adopted for Phase 2 (no way to target a specific platform, and a local
  embedding comparison is simpler, free, and directly answers the
  question being asked). A brand/platform API and MCP research pass
  (Flipkart Affiliate, Amazon Creators API, Apify/MCP for Myntra-style
  platforms) was completed and is kept as the **Phase 3 roadmap** — none
  of it blocks Phase 2, which ships on the existing `SerpApiService` only.
- **Phase 3:** persistent user preferences/history (this is when Postgres
  gets introduced), price alerts, long-term personalization, and — per
  the research done during Phase 2 planning — the official retailer
  integrations (Flipkart Affiliate API, Amazon Creators API, Apify/MCP
  for platforms with no official API) if the Phase 2 SerpAPI-based
  approach proves insufficient in practice.
- **Phase 4:** add-to-cart, wishlist sync, availability checks, order
  workflows.

## 16. Pending Tasks / Recommended Next Step

1. **Run the live smoke test** to close Phase 2: start the backend, then
   `python scripts/smoke_test.py` (optionally with a different query/pincode).
   Also eyeball the UI once (see the Phase 2 testing checklist given with this release).
2. Tune on real data if needed: `IMAGE_SIMILARITY_THRESHOLD` (raise if look-alikes are
   too loose, lower if good matches get dropped), `PLATFORM_CANDIDATES_PER_QUERY`.
3. **Security:** a SerpAPI key was found hard-coded in `serpapi test.py` (now fixed to read
   the env var). That key must be treated as leaked — rotate it in the SerpAPI dashboard.
   Keep `.env` out of zips/git (`.gitignore` added).
4. Then plan Phase 3 (Postgres for persistence, price alerts, official retailer APIs).

## 17. Assumptions Made During Development

- Currency assumed INR throughout (India-focused: pincode,
  Myntra/Flipkart/AJIO/Meesho).
- Phase 1's "similar products" in the compare step = SerpAPI results for
  the selected product's title + extracted style keywords, not a formal
  similarity model. Phase 2 adds real image-similarity matching for the
  cross-platform case specifically (see §13.4).
- `selected_product_ids` was capped at 1-2 in Phase 1; **Phase 2 Step 1
  raised this to 1-5 and it's live** in both the schema and the frontend.
- A working frontend was built after this file's original Phase 1 write-up
  (the original version of this document assumed API-only scope; that
  assumption is now out of date and has been corrected here).

## 18. Phase 2 Rollout Status (authoritative — check this before writing any Phase 2 code)

Steps follow `Phase2_architecture.md` §8's order. Each step was built and
tested (unit tests for pure logic, manual verification for the rest)
before moving to the next.

| # | Step | Status | Files touched |
|---|---|---|---|
| 1 | Schema & config groundwork | ✅ Done | `schemas.py`, `config.py` |
| 2 | SERP simplification (single query, no Gemini rewrite) | ✅ Done | `gemini_service.py`, `serpapi_service.py`, `search.py` (discover) |
| 3 | Discovery sizing (20-35, was fixed 4-5) | ✅ Done | `ranking.py`, `search.py` (discover) |
| 4 | Color/image validation | ✅ Done | `color_validation.py` (new), `dependencies.py`, `search.py` (discover) |
| 5 | Multi-priority + Early Delivery + pincode delivery | ✅ Done | `ranking.py`, `delivery_estimation.py` (new), `memory_store.py`, `dependencies.py`, `search.py` (preferences + compare) |
| — | **Frontend caught up to Steps 1-5** | ✅ Done | `main.jsx` — 1-5 product cap, 1-3 multi-select priorities incl. Early Delivery, platform-selection UI (list fetched from `GET /api/search/platforms`, Step 6), multi-priority display |
| 6 | Platform selection — real `GET /api/search/platforms` endpoint | ✅ Done | `search.py` (new endpoint + `selected_platforms` validation in `/preferences`, 400 on unknown), `config.py` (`platform_label()`), `schemas.py` (`Platform`, `PlatformsResponse`), `main.jsx` (fetches the list), `tests/test_platforms.py` (new) |
| 7 | `platform_search.py` — platform-name-first phrasing + `source` filter | ✅ Done | `platform_search.py` (new), `search.py` (`/compare` now calls it), `config.py` (3 `PLATFORM_*` knobs), `app/tests/test_platform_search.py` (new) |
| 8 | Gemini platform-query generation | ✅ Done | `gemini_service.py` (`generate_platform_queries()`), `platform_search.py` (`queries=` param), `search.py` |
| 9 | Cross-platform image-similarity matching | ✅ Done | `image_matching.py` (new) — **decision: Gemini vision, not local CLIP** (no new deps; see module docstring), `dependencies.py`, `config.py`, `search.py` |
| 10 | Per-priority match-% + bar chart | ✅ Done | `ranking.py` (`compute_priority_match`), `main.jsx` (`MatchBars`), `styles.css` |
| 11 | End-to-end smoke test | ✅ Done (automated) / ▶ run live | `tests/test_full_flow.py`, `scripts/smoke_test.py`, plus unit tests per module |

**Known interim states to be aware of, not bugs:**
- `explain_tradeoffs()` narrates around the primary (first-selected)
  priority only, even though ranking blends all 1-3 — see §2 and §11.
- `selected_platforms` is validated against `TARGET_RETAILERS` and stored in
  the session and drives platform-targeted retrieval in `/compare` (Step 7).

**Phase 2 final notes:**
- Compare pipeline order (authoritative): picks -> Gemini queries -> platform search + source/gender
  filter -> image match -> (picks first) dedupe -> delivery estimate -> rank + match-% -> pin picks ->
  Gemini notes for all priorities.
- Cost per compare, worst case (5 picks x 5 platforms): 25 SerpAPI calls, 1 Gemini query call,
  up to ~75 Gemini vision calls (cached per pair), 1 Gemini notes call.
- `GEMINI_VISION_MODEL` (already in your .env) is now read; color validation + image matching use it.
- Tests: `python -m pytest -q` (no network, never uses real keys — see `app/tests/conftest.py`).
- `Phase2_architecture.md` was not in the uploaded zip; this file + the code are the source of truth.