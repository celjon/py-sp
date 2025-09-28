from typing import Dict, Any, Callable, Awaitable, List
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
import logging

logger = logging.getLogger(__name__)


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

        self.admin_callbacks = {"ban_confirm", "ban_cancel", "unban", "spam_details"}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Основной метод middleware"""

        if isinstance(event, Message):
            text = event.text or "No text"
            user_id = event.from_user.id if event.from_user else "No user"
            chat_type = event.chat.type if event.chat else "No chat"
            logger.info(f"[AUTH] Получено сообщение: '{text[:50]}' от {user_id} в {chat_type}")

            if not await self._check_message_permissions(event):
                logger.warning(f"[AUTH] Сообщение заблокировано middleware")
                return

        elif isinstance(event, CallbackQuery):
            if not await self._check_callback_permissions(event):
                return

        user_id = self._get_user_id(event)
        data["is_admin"] = user_id in self.admin_user_ids
        data["user_id"] = user_id

        logger.debug(f"[AUTH] Передаем событие дальше в handlers")

        result = await handler(event, data)
        
        if result is None:
            logger.debug(f"[AUTH] Handler завершен без возврата значения")
        else:
            logger.debug(f"[AUTH] Handler завершен, возвращен результат: {type(result).__name__}")
        
        return result

    async def _check_message_permissions(self, message: Message) -> bool:
        """Проверяет права для команд в сообщениях"""
        if not message.text or not message.text.startswith("/"):
            return True

        command = message.text.split()[0].lower().split('@')[0]
        user_id = message.from_user.id if message.from_user else None
        chat_type = message.chat.type if message.chat else "unknown"
        chat_id = message.chat.id if message.chat else "unknown"

        logger.info(f"[AUTH] Команда: {command}, user_id: {user_id}, chat_type: {chat_type}, chat_id: {chat_id}")

        if chat_type in ["group", "supergroup", "channel"]:
            if command != "/ban":
                logger.info(f"[AUTH] Команда {command} запрещена в группах/каналах. Игнорируем.")
                return False

            logger.info(f"[AUTH] Команда /ban в группе/канале от {user_id}")

        if command in self.admin_commands:
            logger.info(f"[AUTH] Админская команда {command} от пользователя {user_id}")
            logger.info(f"[AUTH] Список админов: {list(self.admin_user_ids)}")

            if user_id in self.admin_user_ids:
                logger.info(f"[AUTH] Пользователь {user_id} - глобальный админ, разрешаем")
                return True

            if message.chat.type in ["group", "supergroup", "channel"]:
                try:
                    logger.info(f"[AUTH] Проверяем права пользователя {user_id} в чате {chat_id}")
                    chat_member = await message.bot.get_chat_member(
                        chat_id=message.chat.id, user_id=user_id
                    )
                    logger.info(f"[AUTH] Статус пользователя в чате: {chat_member.status}")

                    if chat_member.status in ["administrator", "creator"]:
                        logger.info(f"[AUTH] Пользователь {user_id} - админ чата, разрешаем")
                        return True
                except Exception as e:
                    logger.error(f"[AUTH] Ошибка проверки прав в чате: {e}")

            logger.warning(f"[AUTH] Доступ запрещен для пользователя {user_id}")
            await message.reply(
                "❌ У вас нет прав для выполнения этой команды.\n"
                "Только администраторы могут использовать эту команду."
            )
            return False

        logger.info(f"[AUTH] Команда {command} не требует админских прав")
        return True

    async def _check_callback_permissions(self, callback: CallbackQuery) -> bool:
        """Проверяет права для callback запросов"""
        if not callback.data:
            return True

        callback_type = callback.data.split(":")[0]

        if callback_type in self.admin_callbacks:
            user_id = callback.from_user.id if callback.from_user else None

            if user_id not in self.admin_user_ids:
                if callback.message and callback.message.chat.type == "group":
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
