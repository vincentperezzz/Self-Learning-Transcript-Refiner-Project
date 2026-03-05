"""Redis caching layer for hot-path lookups (N-gram frequencies, lexicon rules)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection (lazy singleton)
# ---------------------------------------------------------------------------

_client: redis.Redis | None = None

# Default TTL for cached entries (5 minutes)
DEFAULT_TTL: int = 300


def _get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def close_redis() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def cache_get(key: str) -> Optional[Any]:
    """Return deserialized value from cache, or None on miss."""
    try:
        raw = _get_redis().get(key)
        if raw is not None:
            return json.loads(raw)
    except (redis.RedisError, json.JSONDecodeError) as exc:
        logger.warning("Redis GET failed for %s: %s", key, exc)
    return None


def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    """Serialize and store a value with TTL."""
    try:
        _get_redis().setex(key, ttl, json.dumps(value))
    except redis.RedisError as exc:
        logger.warning("Redis SET failed for %s: %s", key, exc)


def cache_delete(key: str) -> None:
    """Remove a key from cache."""
    try:
        _get_redis().delete(key)
    except redis.RedisError as exc:
        logger.warning("Redis DELETE failed for %s: %s", key, exc)


def cache_invalidate_prefix(prefix: str) -> None:
    """Delete all keys matching a prefix (use sparingly)."""
    try:
        r = _get_redis()
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match=f"{prefix}*", count=100)
            if keys:
                r.delete(*keys)
            if cursor == 0:
                break
    except redis.RedisError as exc:
        logger.warning("Redis SCAN/DELETE failed for prefix %s: %s", prefix, exc)


# ---------------------------------------------------------------------------
# Domain-specific cache keys
# ---------------------------------------------------------------------------

def ngram_cache_key(w1: str, w2: str, w3: str) -> str:
    return f"ngram:{w1}:{w2}:{w3}"


def ngram_alt_cache_key(w1: str, w2: str) -> str:
    return f"ngram_alt:{w1}:{w2}"


def ngram_alt_suffix_cache_key(w2: str, w3: str) -> str:
    return f"ngram_alt_sfx:{w2}:{w3}"


def lexicon_cache_key(anchor_mode: Optional[str] = None) -> str:
    return f"lexicon:{anchor_mode or 'all'}"
