# src/delivery/telegram/middlewares/chat_isolation.py
"""
Middleware для изоляции чатов - проверяет владение группами
"""

import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from ....domain.entity.user import User
from ....adapter.repository.chat_repository import ChatRepository

logger = logging.getLogger(__name__)


class ChatIsolationMiddleware(BaseMiddleware):
    """
    Middleware для изоляции чатов
    Проверяет, что пользователь имеет права на работу с группой
    """

    def __init__(self, chat_repository: ChatRepository):
        self.chat_repository = chat_repository
        logger.info("🔒 Chat Isolation Middleware инициализирован")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Проверяет изоляцию чатов для сообщений и callback запросов
        """
        
        # Получаем пользователя из данных
        user: User = data.get("user")
        if not user:
            logger.warning("No user in data, skipping chat isolation check")
            return await handler(event, data)

        # Обрабатываем только сообщения и callback запросы
        if isinstance(event, (Message, CallbackQuery)):
            chat_id = None
            
            if isinstance(event, Message):
                chat_id = event.chat.id
            elif isinstance(event, CallbackQuery):
                chat_id = event.message.chat.id if event.message else None

            if chat_id is None:
                logger.warning("No chat_id found in event")
                return await handler(event, data)

            # Пропускаем приватные чаты
            if isinstance(event, Message) and event.chat.type == "private":
                return await handler(event, data)

            # Проверяем владение группой
            is_owner = await self.chat_repository.is_chat_owned_by_user(chat_id, user.telegram_id)
            
            if not is_owner:
                logger.warning(
                    f"User {user.telegram_id} attempted to access chat {chat_id} without ownership"
                )
                
                # Отправляем сообщение об ошибке
                if isinstance(event, Message):
                    await event.reply(
                        "❌ У вас нет прав для работы с этой группой.\n\n"
                        "Эта группа принадлежит другому пользователю.\n"
                        "Используйте /my_chats для просмотра ваших групп."
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer(
                        "❌ У вас нет прав для работы с этой группой.",
                        show_alert=True
                    )
                
                return  # Не передаем обработку дальше

            # Добавляем информацию о чате в данные
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(chat_id, user.telegram_id)
            if chat:
                data["chat"] = chat
                logger.debug(f"Chat {chat_id} ownership verified for user {user.telegram_id}")

        return await handler(event, data)


class ChatOwnershipMiddleware(BaseMiddleware):
    """
    Middleware для проверки владения чатом
    Более мягкая версия - только логирует, не блокирует
    """

    def __init__(self, chat_repository: ChatRepository):
        self.chat_repository = chat_repository
        logger.info("🔍 Chat Ownership Middleware инициализирован")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Проверяет владение чатом и добавляет информацию в данные
        """
        
        # Получаем пользователя из данных
        user: User = data.get("user")
        if not user:
            return await handler(event, data)

        # Обрабатываем только сообщения
        if isinstance(event, Message):
            chat_id = event.chat.id

            # Пропускаем приватные чаты
            if event.chat.type == "private":
                return await handler(event, data)

            # Проверяем владение группой
            is_owner = await self.chat_repository.is_chat_owned_by_user(chat_id, user.telegram_id)
            
            if is_owner:
                # Добавляем информацию о чате в данные
                chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(chat_id, user.telegram_id)
                if chat:
                    data["chat"] = chat
                    data["is_chat_owner"] = True
                    logger.debug(f"Chat {chat_id} ownership verified for user {user.telegram_id}")
            else:
                data["is_chat_owner"] = False
                logger.debug(f"User {user.telegram_id} is not owner of chat {chat_id}")

        return await handler(event, data)
