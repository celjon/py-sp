import time
from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery


class ThrottlingMiddleware(BaseMiddleware):
    """
    Middleware для ограничения частоты запросов (rate limiting)
    Предотвращает спам команд и callback запросов
    """

    def __init__(self, rate_limit: float = 1.0):
        """
        Args:
            rate_limit: Минимальный интервал между запросами в секундах
        """
        self.rate_limit = rate_limit
        self.user_last_call: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Основной метод middleware"""

        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        if user_id is None:
            return await handler(event, data)

        current_time = time.time()
        last_call = self.user_last_call.get(user_id, 0)

        if current_time - last_call < self.rate_limit:
            if isinstance(event, Message):
                pass
            elif isinstance(event, CallbackQuery):
                pass
            return

        self.user_last_call[user_id] = current_time

        if len(self.user_last_call) > 1000:
            cutoff_time = current_time - 3600
            self.user_last_call = {
                uid: last_time
                for uid, last_time in self.user_last_call.items()
                if last_time > cutoff_time
            }

        return await handler(event, data)
