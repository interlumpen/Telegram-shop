import asyncio
import logging
from typing import Coroutine, Any

logger = logging.getLogger(__name__)

# Strong references to in-flight fire-and-forget tasks. Without this the event loop only keeps a weak reference and may cancel/GC a task mid-run.
_background_tasks: "set[asyncio.Task]" = set()


def _on_task_done(task: "asyncio.Task") -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background cache task failed: %r", exc)


def safe_create_task(coro: Coroutine[Any, Any, Any]) -> None:
    """
    Safely create an async task for cache invalidation.
    Works in two contexts:
    1. Async context (event loop running in current thread) — scheduled as a
       tracked task whose exceptions are logged rather than swallowed.
    2. Sync context without any loop (tests) — runs synchronously.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (probably in tests)
        try:
            asyncio.run(coro)
        except RuntimeError:
            logger.debug("Cache invalidation fallback failed (no event loop)")
        return

    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)


async def drain_background_tasks(timeout: float = 5.0) -> None:
    """Wait for in-flight fire-and-forget tasks to finish.

    Called during shutdown so a committed write's cache invalidation is not lost,
    and — more importantly — so nothing is still holding a session when the
    engine is disposed.
    """
    pending = list(_background_tasks)
    if not pending:
        return
    _done, still_running = await asyncio.wait(pending, timeout=timeout)
    if still_running:
        logger.warning(
            "%d background task(s) did not finish within %.0fs of shutdown",
            len(still_running), timeout,
        )
