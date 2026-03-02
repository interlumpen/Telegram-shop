import asyncio
import logging
from typing import Coroutine, Any

logger = logging.getLogger(__name__)

# Reference to the main event loop, set at bot startup
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Store a reference to the main event loop for use from worker threads."""
    global _main_loop
    _main_loop = loop


def safe_create_task(coro: Coroutine[Any, Any, None]) -> None:
    """
    Safely create an async task for cache invalidation.
    Works in three contexts:
    1. Main async context (event loop running in current thread)
    2. Worker thread (run_in_executor) — schedules on the main loop
    3. Sync context without any loop (tests) — runs synchronously
    """
    try:
        # We're in a thread with a running event loop (main async context)
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        # No running loop in this thread — probably in a worker thread
        if _main_loop is not None and _main_loop.is_running():
            _main_loop.call_soon_threadsafe(_main_loop.create_task, coro)
        else:
            # No event loop at all (probably in tests)
            try:
                asyncio.run(coro)
            except RuntimeError:
                logger.debug("Cache invalidation fallback failed (no event loop)")
