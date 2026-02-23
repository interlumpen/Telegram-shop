import asyncio
from typing import List, Optional, Callable, Awaitable, Union
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

from bot.logger_mesh import logger


@dataclass
class BroadcastStats:
    """Broadcast statistics"""
    total: int = 0
    sent: int = 0
    failed: int = 0
    blocked: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0
        return (self.sent / self.total) * 100

    @property
    def duration(self) -> Optional[float]:
        if not self.start_time or not self.end_time:
            return None
        return (self.end_time - self.start_time).total_seconds()


class BroadcastManager:
    """Manager for mass mailing with optimization"""

    def __init__(
            self,
            bot: Bot,
            batch_size: int = 30,
            batch_delay: float = 1.0,
            retry_count: int = 3
    ):
        """
        Args:
            bot: Bot instance
            batch_size: Number of messages in a batch
            batch_delay: Delay between batches (sec)
            retry_count: Number of retries on error
        """
        self.bot = bot
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.retry_count = retry_count
        self._cancelled = False

    async def _send_message_safe(
            self,
            user_id: int,
            text: str,
            reply_markup: Optional[InlineKeyboardMarkup] = None,
            parse_mode: str = "HTML"
    ) -> bool:
        """
        Securely sending a message with error handling

        Returns:
            True if sent successfully, False if failed
        """
        for attempt in range(self.retry_count):
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_notification=True # Don't spam notifications
                )
                return True

            except TelegramRetryAfter as e:
                # Telegram asks to wait
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(e.retry_after)
                    continue
                return False

            except TelegramForbiddenError:
                # Bot blocked by user
                logger.debug(f"Bot blocked by user {user_id}")
                return False

            except TelegramBadRequest as e:
                # Invalid message parameters
                logger.error(f"Bad request for user {user_id}: {e}")
                return False

            except Exception as e:
                # Unknown error
                logger.error(f"Unknown error sending to {user_id}: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(1)
                    continue
                return False

        return False

    async def broadcast(
            self,
            user_ids: List[int],
            text: str,
            reply_markup: Optional[InlineKeyboardMarkup] = None,
            parse_mode: str = "HTML",
            progress_callback: Optional[Union[
                Callable[[BroadcastStats], None],
                Callable[[BroadcastStats], Awaitable[None]]
            ]] = None
    ) -> BroadcastStats:
        """
        Perform broadcast to a list of users

        Args:
            user_ids: List of user IDs
            text: Message text
            reply_markup: Keyboard
            parse_mode: Parsing mode
            progress_callback: Callback for tracking progress (can be async or sync)

        Returns:
            Broadcast statistics
        """
        stats = BroadcastStats(
            total=len(user_ids),
            start_time=datetime.now()
        )

        self._cancelled = False

        # Split into batches
        for i in range(0, len(user_ids), self.batch_size):
            if self._cancelled:
                logger.info("Broadcast cancelled")
                break

            batch = user_ids[i:i + self.batch_size]

            # Create tasks for the batch
            tasks = [
                self._send_message_safe(user_id, text, reply_markup, parse_mode)
                for user_id in batch
            ]

            # Execute the patch in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Update the statistics
            for result in results:
                if isinstance(result, Exception):
                    stats.failed += 1
                elif result:
                    stats.sent += 1
                else:
                    stats.failed += 1

            # Calling a progress collback
            if progress_callback:
                try:
                    # Check if the callback is asynchronous
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(stats)
                    else:
                        progress_callback(stats)
                except Exception as e:
                    logger.error(f"Progress callback error: {e}")

            # Delay between batches
            if i + self.batch_size < len(user_ids):
                await asyncio.sleep(self.batch_delay)

        stats.end_time = datetime.now()
        stats.blocked = stats.failed  # Estimate

        return stats

    def cancel(self):
        """Cancel the current mailing"""
        self._cancelled = True
