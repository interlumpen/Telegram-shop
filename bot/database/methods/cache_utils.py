import asyncio
import logging
from typing import Coroutine, Any

logger = logging.getLogger(__name__)


def safe_create_task(coro: Coroutine[Any, Any, None]) -> None:
    """
    Safely create an async task for cache invalidation.
    Works in two contexts:
    1. Async context (event loop running in current thread)
    2. Sync context without any loop (tests) — runs synchronously
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        # No running loop (probably in tests)
        try:
            asyncio.run(coro)
        except RuntimeError:
            logger.debug("Cache invalidation fallback failed (no event loop)")
