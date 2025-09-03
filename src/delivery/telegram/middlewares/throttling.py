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
        data: Dict[str, Any]
    ) -> Any:
        """Основной метод middleware"""
        
        # Получаем user_id в зависимости от типа события
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
        
        # Если не удалось получить user_id, пропускаем throttling
        if user_id is None:
            return await handler(event, data)
        
        # Проверяем throttling
        current_time = time.time()
        last_call = self.user_last_call.get(user_id, 0)
        
        if current_time - last_call < self.rate_limit:
            # Пользователь слишком часто отправляет запросы
            if isinstance(event, Message):
                await event.answer("⏱ Слишком много запросов. Подождите немного.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⏱ Слишком много запросов", show_alert=True)
            return
        
        # Обновляем время последнего вызова
        self.user_last_call[user_id] = current_time
        
        # Очищаем старые записи (старше 1 часа)
        if len(self.user_last_call) > 1000:
            cutoff_time = current_time - 3600
            self.user_last_call = {
                uid: last_time 
                for uid, last_time in self.user_last_call.items() 
                if last_time > cutoff_time
            }
        
        # Продолжаем обработку
        return await handler(event, data)

