from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class CallbackLockMiddleware(BaseMiddleware):
    """
    A middleware to prevent processing multiple callback queries from the same
    user simultaneously. This helps to avoid race conditions and unintended
    behavior from rapid button clicks.
    """

    def __init__(self):
        # Stores the IDs of users whose callbacks are currently being processed.
        self.locks = set()

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        """
        Handles the incoming callback query.

        If a callback from the same user is already being processed, this
        new callback is ignored. Otherwise, a lock is acquired for the user,
        the handler is executed, and the lock is released upon completion.

        Args:
            handler: The next handler in the chain.
            event: The callback query event.
            data: The data associated with the event.

        Returns:
            The result of the handler execution.
        """
        user_id = event.from_user.id

        # If the user already has a lock, ignore the new callback.
        if user_id in self.locks:
            return

        # Acquire the lock.
        self.locks.add(user_id)
        try:
            return await handler(event, data)
        finally:
            # Release the lock after the handler has finished.
            self.locks.discard(user_id)
