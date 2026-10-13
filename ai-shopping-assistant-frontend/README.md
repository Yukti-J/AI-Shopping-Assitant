# Findly — AI Shopping Decision Assistant

React/Vite frontend for the Phase 1 FastAPI backend.

## Design concept

The UI is intentionally **not** a traditional shopping marketplace. It follows:

**Discover → Choose → Tell us what matters → Compare → Decide**

The discovery screen shows a small set of diverse products. The comparison screen focuses on trade-offs rather than a giant product grid.

## Run

1. Make sure the FastAPI backend is running on `http://localhost:8000`.
2. Copy `.env.example` to `.env` if you need a different backend URL.
3. Run:

```bash
npm install
npm run dev
```

Open the Vite URL shown in the terminal.

## Backend endpoints used

- `POST /api/search/discover`
- `POST /api/search/preferences`
- `POST /api/search/compare`

The backend already has permissive CORS enabled for local development.

## Notes

- Delivery is displayed only when the backend provides a delivery signal. The current backend documents this as best-effort/estimated rather than pincode-confirmed.
- Product URLs open the retailer in a new tab.
- No retailer credentials or API keys belong in the frontend.

## Phase 2 final additions (Steps 6-10)

- The platform list is fetched from `GET /api/search/platforms` (no hardcoded list).
- Comparison cards show a **match-% bar per selected priority** (100% = best option in
  this list, not an absolute grade) and a **look-alike %** badge when the backend
  image-verified the product against one you picked.
- If a chosen platform returned nothing usable, a banner says so (`platform_coverage`).
