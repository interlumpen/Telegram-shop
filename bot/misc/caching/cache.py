import asyncio
import json
from typing import Optional, Any
from redis.asyncio import Redis
from redis.exceptions import RedisError
from functools import wraps
from bot.logger_mesh import logger

_REDIS_DOWN = (RedisError, ConnectionError, TimeoutError, OSError)


class CacheManager:
    """Centralized caching manager with graceful Redis degradation"""

    # Cap on deferred invalidations held while Redis is down. Bounded so a long outage can't grow memory without limit;
    # on overflow fall back to replaying the known cache-key prefixes on recovery.
    _PENDING_CAP = 5000
    _KNOWN_PREFIXES = (
        "user:", "role:", "auth:role:", "category:", "category_items:",
        "item_info:", "item_values:", "item_infinite:", "avg_rating:",
        "user_count:", "admin_count:", "user_stats:", "user_items:", "stats:",
    )

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.default_ttl = 300
        self.hits = 0
        self.misses = 0
        self._healthy = True
        # Invalidations that failed while Redis was unavailable, replayed on recovery so a committed DB write is never masked by a stale cache entry until its TTL expires.
        self._pending_deletes: set[str] = set()
        self._pending_patterns: set[str] = set()
        self._pending_overflow = False

    def _defer_delete(self, key: str) -> None:
        if len(self._pending_deletes) >= self._PENDING_CAP:
            self._pending_overflow = True
            return
        self._pending_deletes.add(key)

    def _defer_pattern(self, pattern: str) -> None:
        if len(self._pending_patterns) >= self._PENDING_CAP:
            self._pending_overflow = True
            return
        self._pending_patterns.add(pattern)

    async def get(self, key: str, deserialize: bool = True) -> Optional[Any]:
        """Get value from cache with correct deserialization"""
        if not self._healthy:
            self.misses += 1
            return None
        try:
            # Redis returns bytes
            value = await self.redis.get(key)

            if value is None:
                self.misses += 1
                return None

            self.hits += 1

            if not deserialize:
                return value

            # Deserialize from JSON (only safe format)
            if isinstance(value, bytes):
                try:
                    decoded = value.decode('utf-8')
                    return json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.error(f"Failed to deserialize cache value for key {key}")
                    return None
            else:
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value

        except _REDIS_DOWN as e:
            self._healthy = False
            logger.warning(f"Redis unavailable (get): {e}")
            return None
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None

    async def set(
            self,
            key: str,
            value: Any,
            ttl: Optional[int] = None,
            serialize: bool = True
    ) -> bool:
        """Save the value to cache with correct serialization"""
        if not self._healthy:
            return False
        try:
            ttl = ttl or self.default_ttl

            if not serialize:
                await self.redis.setex(key, ttl, value)
                return True

            # Serialize to JSON only (no pickle — avoids RCE risk)
            try:
                serialized = json.dumps(value).encode('utf-8')
            except (TypeError, ValueError):
                try:
                    serialized = json.dumps(value, default=str).encode('utf-8')
                except (TypeError, ValueError):
                    serialized = str(value).encode('utf-8')

            await self.redis.setex(key, ttl, serialized)
            return True

        except _REDIS_DOWN as e:
            self._healthy = False
            logger.warning(f"Redis unavailable (set): {e}")
            return False
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a value from the cache"""
        if not self._healthy:
            # Redis is down: remember the invalidation so recovery can replay it.
            self._defer_delete(key)
            return False
        try:
            await self.redis.delete(key)
            return True
        except _REDIS_DOWN as e:
            self._healthy = False
            self._defer_delete(key)
            logger.warning(f"Redis unavailable (delete): {e}")
            return False
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False

    async def check_health(self) -> bool:
        """Ping Redis and restore healthy status if connection is back."""
        try:
            await self.redis.ping()
            was_unhealthy = not self._healthy
            if was_unhealthy:
                logger.info("Redis connection restored, re-enabling cache")
                self._healthy = True
            # Replay any invalidations deferred during the outage (also covers a
            # steady-state overflow flush) so committed writes stop serving stale.
            if was_unhealthy or self._pending_deletes or self._pending_patterns or self._pending_overflow:
                await self._replay_pending()
            return True
        except Exception:
            self._healthy = False
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys by pattern"""
        if not self._healthy:
            self._defer_pattern(pattern)
            return 0
        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern, count=500):
                keys.append(key)

            if keys:
                return await self.redis.delete(*keys)
            return 0
        except _REDIS_DOWN as e:
            self._healthy = False
            self._defer_pattern(pattern)
            logger.warning(f"Redis unavailable (invalidate): {e}")
            return 0
        except Exception as e:
            logger.error(f"Cache invalidate error for pattern {pattern}: {e}")
            return 0

    async def _replay_pending(self) -> None:
        """Replay invalidations that were deferred while Redis was down.

        Called from check_health once the connection is back. Best-effort: any
        key that fails here is simply re-deferred by delete()/invalidate_pattern.
        """
        if self._pending_overflow:
            # We lost track of exactly which keys changed — clear all known cache
            # namespaces so nothing stale survives, then reset.
            self._pending_overflow = False
            self._pending_deletes.clear()
            self._pending_patterns.clear()
            for prefix in self._KNOWN_PREFIXES:
                await self.invalidate_pattern(f"{prefix}*")
            return

        deletes = self._pending_deletes
        patterns = self._pending_patterns
        self._pending_deletes = set()
        self._pending_patterns = set()
        for key in deletes:
            await self.delete(key)
        for pattern in patterns:
            await self.invalidate_pattern(pattern)


# Single-flight locks for cache misses (in-process; single-instance deployment).
_result_locks: dict[str, asyncio.Lock] = {}


def cache_result(
        ttl: int = 300,
        key_prefix: str = "",
        key_func: Optional[callable] = None
):
    """Decorator for caching function results.

    Misses are single-flighted: when a hot key (e.g. stats:global) expires,
    concurrent callers wait for one recomputation instead of all running it.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Cache key generation
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Automatic key generation
                key_parts = [key_prefix or func.__name__]
                key_parts.extend(str(arg) for arg in args if not hasattr(arg, '__dict__'))
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)

            cache_manager = get_cache_manager()
            if not cache_manager:
                return await func(*args, **kwargs)

            cached = await cache_manager.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached

            lock = _result_locks.get(cache_key)
            if lock is None:
                lock = _result_locks[cache_key] = asyncio.Lock()
            try:
                async with lock:
                    cached = await cache_manager.get(cache_key)
                    if cached is not None:
                        return cached

                    result = await func(*args, **kwargs)

                    if result is not None:
                        await cache_manager.set(cache_key, result, ttl)
                        logger.debug(f"Cache set for {cache_key}")
                    return result
            finally:
                _result_locks.pop(cache_key, None)

        return wrapper

    return decorator


# Singleton for cache manager
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> Optional[CacheManager]:
    """get singleton instance cache manager"""
    return _cache_manager


async def init_cache_manager(redis: Redis):
    """Initialize cache manager"""
    global _cache_manager
    _cache_manager = CacheManager(redis)
    logger.info("Cache manager initialized")
