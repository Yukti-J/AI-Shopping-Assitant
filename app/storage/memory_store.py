"""
In-memory session store.

DELIBERATE MVP SHORTCUT: the project brief calls for Redis + PostgreSQL,
but for Phase 1 we skip both. This class is the single seam that holds
session state (discover -> preferences -> compare). Swapping it for a
Redis-backed implementation later means implementing this same interface
against Redis and changing one import in dependencies.py — nothing else
in the app should reach into storage directly.

Known limitation: state is lost on process restart and does not scale
beyond a single worker process. Fine for local MVP testing, not for
production. See project_context.md > Known Limitations.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

from app.models.schemas import Product, ParsedQuery, ShoppingPriority


@dataclass
class ShoppingSession:
    session_id: str
    created_at: float = field(default_factory=time.time)
    original_query: Optional[str] = None
    parsed_query: Optional[ParsedQuery] = None
    discovery_products: list[Product] = field(default_factory=list)
    selected_product_ids: list[str] = field(default_factory=list)
    # Phase 2 (Req 4): single priority -> 1-3, weights blended in ranking.py
    priorities: list[ShoppingPriority] = field(default_factory=list)
    pincode: Optional[str] = None
    # Phase 2 (Req 5): platforms to search in the compare stage. Stored here
    # alongside priorities/pincode since all three are set together in
    # /api/search/preferences. Read by /compare (platform_search.py, Step 7).
    selected_platforms: list[str] = field(default_factory=list)
    compared_products: list[Product] = field(default_factory=list)


class InMemorySessionStore:
    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: dict[str, ShoppingSession] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds

    def create_session(self, query: str, parsed_query: ParsedQuery, discovery_products: list[Product]) -> ShoppingSession:
        session_id = str(uuid.uuid4())
        session = ShoppingSession(
            session_id=session_id,
            original_query=query,
            parsed_query=parsed_query,
            discovery_products=discovery_products,
        )
        with self._lock:
            self._evict_expired()
            self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[ShoppingSession]:
        with self._lock:
            self._evict_expired()
            return self._sessions.get(session_id)

    def update_preferences(
        self,
        session_id: str,
        selected_product_ids: list[str],
        priorities: list[ShoppingPriority],
        pincode: str,
        selected_platforms: list[str],
    ) -> Optional[ShoppingSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.selected_product_ids = selected_product_ids
            session.priorities = priorities
            session.pincode = pincode
            session.selected_platforms = selected_platforms
            return session

    def save_comparison(self, session_id: str, compared_products: list[Product]) -> Optional[ShoppingSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.compared_products = compared_products
            return session

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.created_at > self._ttl]
        for sid in expired:
            del self._sessions[sid]


# Single process-wide instance (fine for MVP; would become a Redis client in prod)
_store: Optional[InMemorySessionStore] = None


def get_session_store() -> InMemorySessionStore:
    global _store
    if _store is None:
        from app.core.config import get_settings
        _store = InMemorySessionStore(ttl_seconds=get_settings().SESSION_TTL_SECONDS)
    return _store