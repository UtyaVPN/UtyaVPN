from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class CallbackLockMiddleware(BaseMiddleware):

    def __init__(self):
        # Храним id пользователей, у которых уже обрабатывается callback
        self.locks = set()

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user_id = event.from_user.id

        # Если у пользователя уже есть "замок" → игнорируем
        if user_id in self.locks:
            return

        # Ставим замок
        self.locks.add(user_id)
        try:
            return await handler(event, data)
        finally:
            # Снимаем замок после завершения обработки
            self.locks.discard(user_id)
