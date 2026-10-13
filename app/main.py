import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import search

settings = get_settings()
logging.basicConfig(level=settings.LOG_LEVEL)

app = FastAPI(
    title="AI Shopping Decision Assistant — Phase 2",
    description=(
        "Discover -> Learn Preferences -> Search Across Market -> Compare -> "
        "Explain Trade-offs -> Decide"
    ),
    version="0.2.0",
)

# Permissive for local dev; tighten before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gemini_configured": settings.has_gemini_key,
        "serpapi_configured": settings.has_serpapi_key,
        # Phase 2: image matching + color validation both need Gemini vision.
        "image_matching_enabled": settings.has_gemini_key,
    }


@app.get("/")
def root():
    return {
        "name": "AI Shopping Decision Assistant",
        "phase": "Phase 2",
        "docs": "/docs",
        "flow": [
            "GET /api/search/platforms",
            "POST /api/search/discover",
            "POST /api/search/preferences",
            "POST /api/search/compare",
        ],
    }
