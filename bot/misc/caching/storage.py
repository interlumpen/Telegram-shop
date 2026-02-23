import logging
from typing import Optional, Literal
from redis.asyncio import Redis
from aiogram.fsm.storage.redis import RedisStorage, StorageKey
from bot.misc import EnvKeys


class CustomRedisStorage(RedisStorage):
    """
    Custom Redis storage with TTL support for FSM states.
    States will expire after the specified TTL to prevent memory leaks.
    """

    def __init__(
            self,
            redis: Redis,
            state_ttl: Optional[int] = 3600,  # 1 hour by default
            data_ttl: Optional[int] = 3600,
    ):
        super().__init__(redis=redis)
        self.state_ttl = state_ttl
        self.data_ttl = data_ttl

    async def set_state(self, key: StorageKey, state: str = None) -> None:
        """Set state with TTL"""
        await super().set_state(key, state)
        if state and self.state_ttl:
            redis_key = self._build_key(key, "state")
            await self.redis.expire(redis_key, self.state_ttl)

    async def set_data(self, key: StorageKey, data: dict) -> None:
        """Set data with TTL"""
        await super().set_data(key, data)
        if data and self.data_ttl:
            redis_key = self._build_key(key, "data")
            await self.redis.expire(redis_key, self.data_ttl)

    def _build_key(self, key: StorageKey, part: Literal["data", "state", "lock"]) -> str:
        """Build Redis key"""
        assert self.key_builder is not None, "KeyBuilder should be initialized"
        return self.key_builder.build(key, part)


def get_redis_storage() -> Optional[RedisStorage]:
    """
    Create Redis storage with proper configuration.
    Returns None if Redis is not available.
    """
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

        # Use custom storage with TTL
        storage = CustomRedisStorage(
            redis=redis,
            state_ttl=3600,  # 1 hour
            data_ttl=3600,  # 1 hour
        )

        logging.info(f"Redis storage configured: {EnvKeys.REDIS_HOST}:{EnvKeys.REDIS_PORT}")
        return storage

    except Exception as e:
        logging.error(f"Failed to create Redis storage: {e}")
        return None
