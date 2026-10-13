# Findly — AI Shopping Decision Assistant

React/Vite frontend for the FastAPI backend. Currently matches backend
**Phase 2, Steps 1-5** (see the backend's `project_context.md` §18 for the
full rollout status — Steps 6-11 aren't built yet, and a couple of pieces
below are explicitly interim).

## Design concept

The UI is intentionally **not** a traditional shopping marketplace. It follows:

**Discover → Choose → Tell us what matters → Compare → Decide**

The discovery screen shows a diverse set of products (20-35, as of Phase 2 —
was 4-5 in Phase 1). The comparison screen focuses on trade-offs rather
than a giant product grid.

## Run

1. Make sure the FastAPI backend is running on `http://localhost:8000`.
2. Copy `.env.example` to `.env` if you need a different backend URL.
3. Run:

```bash
npm install
npm run dev
```

Open the Vite URL shown in the terminal.

## What changed in Phase 2 (Steps 1-5)

- **Pick up to 5 products** in Discover (was up to 2).
- **Pick 1-3 shopping priorities** instead of exactly one, including a new
  **Early Delivery** option — the app blends whichever priorities you pick
  into one ranking.
- **New platform-selection step** between priorities and pincode. ⚠️
  **Interim state:** the platform list (`PLATFORMS` in `main.jsx`) is
  currently hardcoded to match the backend's default `TARGET_RETAILERS` —
  it's sent to the backend and stored, but doesn't yet change what gets
  searched (that's backend Steps 6-7). Replace this constant with a fetch
  to `GET /api/search/platforms` once that endpoint exists.
- **Pincode now actually does something** — the comparison screen's
  delivery estimate reflects a real pincode-tier + retailer-speed
  calculation, not just whatever SerpAPI happened to return.
- **Comparison screen shows multiple priorities** ("Priorities: Lowest
  price + Early delivery") when more than one was selected.

## Backend endpoints used

- `POST /api/search/discover`
- `POST /api/search/preferences` — now sends `priorities` (array) and
  `selected_platforms` (array), not a single `priority` string
- `POST /api/search/compare` — now returns `priorities` (array) in the
  response, not a single `priority`

`GET /api/search/platforms` doesn't exist on the backend yet (Step 6) —
the frontend doesn't call it.

The backend already has permissive CORS enabled for local development.

## Notes

- Delivery is displayed whenever the backend's pincode-based heuristic
  produces an estimate (which it now does whenever a valid pincode was
  given — see above). It's still labeled as an estimate, never a live
  retailer promise.
- Product URLs open the retailer in a new tab.
- No retailer credentials or API keys belong in the frontend.
- The platform-selection UI currently reuses the existing `priority-card`/
  `priority-grid` CSS classes rather than introducing new ones, so it's
  visually consistent without needing a `styles.css` change. If you want
  dedicated platform-pill styling, that's a `styles.css` change we haven't
  made.

## Phase 2 — run & test

```bash
pip install -r requirements-dev.txt
cp .env.example .env          # add GEMINI_API_KEY and SERPAPI_API_KEY
python -m pytest -q           # 34 automated tests, no network, no API cost
uvicorn app.main:app --reload # backend on :8000
python scripts/smoke_test.py  # live end-to-end check (uses real API quota)
```
