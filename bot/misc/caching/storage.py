import logging
from typing import Optional
from redis.asyncio import Redis
from aiogram.fsm.storage.redis import RedisStorage
from bot.misc import EnvKeys

# Expire FSM state/data after an hour of inactivity so abandoned conversations do not accumulate in Redis.
# RedisStorage applies these in the same SET that writes the value, so the TTL costs no extra round-trip.
FSM_TTL = 3600


async def get_redis_storage() -> Optional[RedisStorage]:
    """
    Create Redis storage with proper configuration.
    Returns None if Redis is disabled or not reachable.

    The connection is verified with a PING before the storage is handed back.
    """
    if EnvKeys.REDIS_ENABLED != "1":
        logging.info("Redis is disabled via REDIS_ENABLED=0")
        return None

    redis = None
    try:
        redis = Redis(
            host=EnvKeys.REDIS_HOST,
            port=EnvKeys.REDIS_PORT,
            db=EnvKeys.REDIS_DB,
            password=EnvKeys.REDIS_PASSWORD,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )

        await redis.ping()

        storage = RedisStorage(
            redis=redis,
            state_ttl=FSM_TTL,
            data_ttl=FSM_TTL,
        )

        logging.info(f"Redis storage configured: {EnvKeys.REDIS_HOST}:{EnvKeys.REDIS_PORT}")
        return storage

    except Exception as e:
        logging.error(
            "Redis at %s:%s is unreachable (%s) - falling back to in-memory storage",
            EnvKeys.REDIS_HOST, EnvKeys.REDIS_PORT, e,
        )
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:
                pass
        return None
