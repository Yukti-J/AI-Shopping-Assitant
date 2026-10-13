"""
Dependency singletons, wired once here so routers stay thin and testable
(swap any of these for a mock in tests without touching router code).
"""
from functools import lru_cache

from app.services.color_validation import ColorValidationService
from app.services.delivery_estimation import DeliveryEstimationService
from app.services.gemini_service import GeminiService
from app.services.image_matching import ImageMatchingService
from app.services.serpapi_service import SerpApiService
from app.storage.memory_store import InMemorySessionStore, get_session_store


@lru_cache
def get_gemini_service() -> GeminiService:
    return GeminiService()


@lru_cache
def get_serpapi_service() -> SerpApiService:
    return SerpApiService()


@lru_cache
def get_color_validation_service() -> ColorValidationService:
    return ColorValidationService()


@lru_cache
def get_image_matching_service() -> ImageMatchingService:
    return ImageMatchingService()


@lru_cache
def get_delivery_estimation_service() -> DeliveryEstimationService:
    return DeliveryEstimationService()


def get_store() -> InMemorySessionStore:
    return get_session_store()