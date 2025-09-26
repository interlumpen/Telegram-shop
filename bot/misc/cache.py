import json
import pickle
from typing import Optional, Any
from redis.asyncio import Redis
from functools import wraps
from bot.logger_mesh import logger


class CacheManager:
    """Centralized caching manager"""

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.default_ttl = 300
        self.hits = 0
        self.misses = 0

    async def get(self, key: str, deserialize: bool = True) -> Optional[Any]:
        """Get value from cache with correct deserialization"""
        try:
            # Redis returns bytes
            value = await self.redis.get(key)

            if value is None:
                self.misses += 1
                return None

            self.hits += 1

            if not deserialize:
                return value

            # Trying different ways of deserializing
            if isinstance(value, bytes):
                # Try JSON first
                try:
                    decoded = value.decode('utf-8')
                    return json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    # If not JSON, try pickle
                    try:
                        return pickle.loads(value)
                    except Exception:
                        logger.error(f"Failed to deserialize cache value for key {key}")
                        return None
            else:
                # If there's already a line
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value

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
        try:
            ttl = ttl or self.default_ttl

            if not serialize:
                await self.redis.setex(key, ttl, value)
                return True

            # Try serializing to JSON (more efficient)
            try:
                serialized = json.dumps(value).encode('utf-8')
            except (TypeError, ValueError):
                # Try JSON with default=str for complex objects
                try:
                    serialized = json.dumps(value, default=str).encode('utf-8')
                except (TypeError, ValueError):
                    # If JSON still fails, use pickle
                    try:
                        serialized = pickle.dumps(value)
                    except Exception:
                        # If even pickle fails, convert to string as last resort
                        serialized = str(value).encode('utf-8')

            await self.redis.setex(key, ttl, serialized)
            return True

        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a value from the cache"""
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys by pattern"""
        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                return await self.redis.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Cache invalidate error for pattern {pattern}: {e}")
            return 0



def cache_result(
        ttl: int = 300,
        key_prefix: str = "",
        key_func: Optional[callable] = None
):
    """Decorator for caching function results"""

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

            # Trying to get from the cache
            cache_manager = get_cache_manager()
            if cache_manager:
                cached = await cache_manager.get(cache_key)
                if cached is not None:
                    logger.debug(f"Cache hit for {cache_key}")
                    return cached

            # Call the original function
            result = await func(*args, **kwargs)

            # Save to cache
            if cache_manager and result is not None:
                await cache_manager.set(cache_key, result, ttl)
                logger.debug(f"Cache set for {cache_key}")

            return result

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
