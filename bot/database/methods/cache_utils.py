import asyncio
from typing import Coroutine, Any


def safe_create_task(coro: Coroutine[Any, Any, None]) -> None:
    """
    Safely create an async task for cache invalidation.
    Works both in async context (with event loop) and sync context (tests).
    """
    try:
        # Try to get the running event loop
        loop = asyncio.get_running_loop()
        # If we have a loop, create task as usual
        loop.create_task(coro)
    except RuntimeError:
        # No event loop running (probably in tests)
        # Run the coroutine in a new event loop
        try:
            asyncio.run(coro)
        except RuntimeError:
            # If asyncio.run() also fails (nested event loop), just ignore
            # This is fire-and-forget for cache invalidation anyway
            pass
