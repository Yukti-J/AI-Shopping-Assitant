"""
Centralized configuration. All environment-dependent values must be read
from here, never hardcoded or read from os.environ elsewhere.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


# Display names for the platform picker, keyed by the domains used in
# TARGET_RETAILERS. A retailer missing from this map still works: it gets a
# label derived from its domain (see Settings.platform_label).
_PLATFORM_LABELS = {
    "amazon.in": "Amazon",
    "flipkart.com": "Flipkart",
    "myntra.com": "Myntra",
    "ajio.com": "Ajio",
    "meesho.com": "Meesho",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Required secrets (no defaults on purpose: fail fast if missing) ---
    GEMINI_API_KEY: str = ""
    SERPAPI_API_KEY: str = ""

    # --- Tuning / optional ---
    GEMINI_MODEL: str = "gemini-3.8-flash"
    # Model for image inputs (color validation + image matching). Leave empty
    # to reuse GEMINI_MODEL. Already present in your .env, now actually read.
    GEMINI_VISION_MODEL: str = ""
    SERPAPI_COUNTRY: str = "in"
    SERPAPI_LANGUAGE: str = "en"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    TARGET_RETAILERS: str = "amazon.in,myntra.com,flipkart.com,ajio.com,meesho.com"

    # --- Behavioral knobs (kept out of code so they're easy to tune) ---
    # Phase 2 (Req 3): DISCOVERY_RESULT_COUNT (fixed 4-5) replaced by a range;
    # select_diverse_discovery_set() targets ~25-30, never below MIN unless
    # the true candidate pool is smaller.
    DISCOVERY_MIN_COUNT: int = 20
    DISCOVERY_MAX_COUNT: int = 35
    COMPARISON_MIN_COUNT: int = 10
    COMPARISON_MAX_COUNT: int = 12
    SESSION_TTL_SECONDS: int = 60 * 60  # 1 hour, in-memory sessions expire
    # Phase 2 (Req 7): minimum cosine similarity for image_matching.py to
    # treat a cross-platform candidate as a genuine match.
    IMAGE_SIMILARITY_THRESHOLD: float = 0.75
    # Phase 2 (Step 7): platform-targeted retrieval in the compare stage
    # (platform_search.py). One SerpAPI call is made per (selected product x
    # selected platform), so these knobs directly control API cost + latency.
    PLATFORM_RAW_RESULTS_PER_QUERY: int = 10  # raw results requested; the source filter drops off-platform ones
    PLATFORM_CANDIDATES_PER_QUERY: int = 3    # on-platform candidates kept per (product, platform) query
    PLATFORM_SEARCH_CONCURRENCY: int = 5      # max simultaneous SerpAPI calls
    # Phase 2 (Step 9): cap on simultaneous Gemini vision calls while
    # image-matching platform candidates against the user's picks.
    IMAGE_MATCH_CONCURRENCY: int = 6

    @property
    def target_retailers_list(self) -> list[str]:
        return [r.strip() for r in self.TARGET_RETAILERS.split(",") if r.strip()]

    def platform_label(self, domain: str) -> str:
        """Human-readable name for a TARGET_RETAILERS domain, e.g. 'amazon.in' -> 'Amazon'."""
        return _PLATFORM_LABELS.get(domain, domain.split(".")[0].capitalize())

    @property
    def gemini_vision_model(self) -> str:
        return self.GEMINI_VISION_MODEL.strip() or self.GEMINI_MODEL

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def has_serpapi_key(self) -> bool:
        return bool(self.SERPAPI_API_KEY)


@lru_cache
def get_settings() -> Settings:
    return Settings()