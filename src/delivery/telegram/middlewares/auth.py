from typing import Dict, Any, Callable, Awaitable, List
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery


class AuthMiddleware(BaseMiddleware):
    """
    Middleware для авторизации и проверки прав доступа
    Проверяет права на выполнение админских команд
    """

    def __init__(self, admin_user_ids: List[int] = None):
        """
        Args:
            admin_user_ids: Список ID администраторов
        """
        self.admin_user_ids = set(admin_user_ids or [])

        # Команды, требующие админских прав
        self.admin_commands = {
            "/ban",
            "/unban",
            "/approve",
            "/spam",
            "/ham",
            "/stats",
            "/chatstats",
            "/kick",
            "/mute",
            "/unmute",
        }

        # Callback запросы, требующие админских прав
        self.admin_callbacks = {"ban_confirm", "ban_cancel", "unban", "spam_details"}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Основной метод middleware"""

        # Проверяем права для сообщений с командами
        if isinstance(event, Message):
            if not await self._check_message_permissions(event):
                return  # Блокируем выполнение

        # Проверяем права для callback запросов
        elif isinstance(event, CallbackQuery):
            if not await self._check_callback_permissions(event):
                return  # Блокируем выполнение

        # Добавляем информацию об авторизации в данные
        user_id = self._get_user_id(event)
        data["is_admin"] = user_id in self.admin_user_ids
        data["user_id"] = user_id

        # Продолжаем обработку
        return await handler(event, data)

    async def _check_message_permissions(self, message: Message) -> bool:
        """Проверяет права для команд в сообщениях"""
        if not message.text or not message.text.startswith("/"):
            return True  # Не команда - пропускаем

        command = message.text.split()[0].lower()

        # Если это админская команда
        if command in self.admin_commands:
            user_id = message.from_user.id if message.from_user else None

            # Проверяем, является ли пользователь администратором
            if user_id not in self.admin_user_ids:
                # Дополнительно проверяем права в чате
                if message.chat.type in ["group", "supergroup"]:
                    try:
                        chat_member = await message.bot.get_chat_member(
                            chat_id=message.chat.id, user_id=user_id
                        )
                        if chat_member.status in ["administrator", "creator"]:
                            return True
                    except Exception:
                        pass

                await message.reply(
                    "❌ У вас нет прав для выполнения этой команды.\n"
                    "Только администраторы могут использовать эту команду."
                )
                return False

        return True

    async def _check_callback_permissions(self, callback: CallbackQuery) -> bool:
        """Проверяет права для callback запросов"""
        if not callback.data:
            return True

        # Извлекаем тип callback из данных
        callback_type = callback.data.split(":")[0]

        # Если это админский callback
        if callback_type in self.admin_callbacks:
            user_id = callback.from_user.id if callback.from_user else None

            if user_id not in self.admin_user_ids:
                # Дополнительно проверяем права в чате
                if callback.message and callback.message.chat.type in ["group", "supergroup"]:
                    try:
                        chat_member = await callback.bot.get_chat_member(
                            chat_id=callback.message.chat.id, user_id=user_id
                        )
                        if chat_member.status in ["administrator", "creator"]:
                            return True
                    except Exception:
                        pass

                await callback.answer("❌ У вас нет прав для этого действия", show_alert=True)
                return False

        return True

    def _get_user_id(self, event: TelegramObject) -> int:
        """Извлекает user_id из события"""
        if isinstance(event, (Message, CallbackQuery)):
            return event.from_user.id if event.from_user else None
        return None

    def add_admin(self, user_id: int):
        """Добавляет администратора"""
        self.admin_user_ids.add(user_id)

    def remove_admin(self, user_id: int):
        """Удаляет администратора"""
        self.admin_user_ids.discard(user_id)

    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        return user_id in self.admin_user_ids
