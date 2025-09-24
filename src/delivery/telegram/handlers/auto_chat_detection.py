# src/delivery/telegram/handlers/auto_chat_detection.py
"""
Автоматическое определение владельца группы при добавлении бота
"""

import logging
from typing import Dict, Any, Optional
from aiogram import Router, types, F
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from aiogram.types import ChatMemberUpdated

from ....domain.entity.user import User
from ....domain.entity.chat import Chat, ChatType
from ....adapter.repository.user_repository import UserRepository
from ....adapter.repository.chat_repository import ChatRepository
from ....adapter.gateway.telegram_chat_gateway import TelegramChatGateway

logger = logging.getLogger(__name__)
router = Router()


class AutoChatDetectionHandler:
    """Обработчик автоматического определения владельца группы"""

    def __init__(
        self, 
        user_repository: UserRepository, 
        chat_repository: ChatRepository,
        telegram_chat_gateway: TelegramChatGateway
    ):
        self.user_repository = user_repository
        self.chat_repository = chat_repository
        self.telegram_chat_gateway = telegram_chat_gateway
        logger.info("🤖 Auto Chat Detection Handler инициализирован")

    async def handle_bot_added_to_group(
        self,
        event: ChatMemberUpdated,
        **kwargs
    ) -> None:
        """
        Обрабатывает добавление бота в группу
        Автоматически определяет владельца и создает запись в БД
        """
        try:
            # Проверяем, что бот был добавлен (статус изменился)
            if event.new_chat_member.status in ["member", "administrator"]:
                chat_id = event.chat.id
                
                logger.info(f"Bot added to group {chat_id}: {event.chat.title}")
                
                # Получаем информацию о чате
                chat_info = await self.telegram_chat_gateway.get_chat_info(chat_id)
                if not chat_info:
                    logger.error(f"Could not get chat info for {chat_id}")
                    return
                
                # Получаем владельца чата
                owner_info = await self.telegram_chat_gateway.get_chat_owner(chat_id)
                if not owner_info:
                    logger.warning(f"No owner found for chat {chat_id}")
                    await self._send_no_owner_message(chat_id)
                    return
                
                owner_user_id = owner_info["user_id"]
                logger.info(f"Chat {chat_id} owner: {owner_user_id}")
                
                # Проверяем, есть ли уже запись о чате
                existing_chat = await self.chat_repository.get_chat_by_telegram_id(chat_id)
                if existing_chat:
                    logger.info(f"Chat {chat_id} already exists, owner: {existing_chat.owner_user_id}")
                    if existing_chat.owner_user_id != owner_user_id:
                        await self._send_ownership_conflict_message(chat_id, existing_chat.owner_user_id, owner_user_id)
                    return
                
                # Получаем или создаем пользователя-владельца
                user = await self.user_repository.get_user(owner_user_id)
                if not user:
                    # Создаем нового пользователя
                    user = await self.user_repository.create_user(
                        telegram_id=owner_user_id,
                        username=owner_info.get("username"),
                        first_name=owner_info.get("first_name"),
                        last_name=owner_info.get("last_name")
                    )
                    logger.info(f"Created new user: {owner_user_id}")
                
                # Создаем запись о чате
                chat = Chat(
                    telegram_id=chat_id,
                    owner_user_id=owner_user_id,
                    title=chat_info.get("title"),
                    type=ChatType(chat_info.get("type", "group")),
                    description=chat_info.get("description"),
                    username=chat_info.get("username"),
                    is_monitored=True,
                    spam_threshold=0.6,
                    is_active=True,
                )
                
                await self.chat_repository.create_chat(chat)
                
                # Отправляем приветственное сообщение ВЛАДЕЛЬЦУ в личку
                await self._send_welcome_message_to_owner(chat_id, owner_user_id, chat_info.get("title"))
                
                logger.info(f"Chat {chat_id} automatically registered for user {owner_user_id}")
                
        except Exception as e:
            logger.error(f"Error in handle_bot_added_to_group: {e}")

    async def handle_bot_removed_from_group(
        self,
        event: ChatMemberUpdated,
        **kwargs
    ) -> None:
        """
        Обрабатывает удаление бота из группы
        """
        try:
            # Проверяем, что бот был удален
            if event.new_chat_member.status in ["left", "kicked"]:
                chat_id = event.chat.id
                
                logger.info(f"Bot removed from group {chat_id}: {event.chat.title}")
                
                # Деактивируем чат в БД
                chat = await self.chat_repository.get_chat_by_telegram_id(chat_id)
                if chat:
                    chat.deactivate()
                    await self.chat_repository.update_chat(chat)
                    logger.info(f"Chat {chat_id} deactivated")
                
        except Exception as e:
            logger.error(f"Error in handle_bot_removed_from_group: {e}")

    async def handle_new_member(
        self,
        message: types.Message,
        **kwargs
    ) -> None:
        """
        Обрабатывает добавление новых участников в группу
        Может использоваться для дополнительной логики
        """
        try:
            if message.new_chat_members:
                chat_id = message.chat.id
                
                # Проверяем, что чат зарегистрирован
                chat = await self.chat_repository.get_chat_by_telegram_id(chat_id)
                if not chat or not chat.is_active:
                    return
                
                # Логируем новых участников
                for member in message.new_chat_members:
                    if not member.is_bot:
                        logger.info(f"New member {member.id} joined chat {chat_id}")
                
        except Exception as e:
            logger.error(f"Error in handle_new_member: {e}")

    async def _send_welcome_message_to_owner(self, chat_id: int, owner_user_id: int, chat_title: str) -> None:
        """Отправляет приветственное сообщение владельцу в личку"""
        try:
            welcome_text = f"""
🎉 <b>Бот успешно добавлен в группу!</b>

📋 <b>Группа:</b> {chat_title}
👤 <b>Владелец:</b> Пользователь

✅ <b>Автоматическая настройка завершена!</b>

🔧 <b>Доступные команды:</b>
• /my_chats - ваши группы
• /chat_settings - настройки группы
• /bothub_token - настройка токена BotHub
• /bothub_status - статус BotHub

⚠️ <b>Важно:</b> Для работы антиспама необходимо настроить токен BotHub командой /bothub_token

🤖 Бот готов к работе!
            """

            # Отправляем сообщение ВЛАДЕЛЬЦУ в личку
            await self.telegram_chat_gateway.bot.send_message(owner_user_id, welcome_text, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error sending welcome message to owner: {e}")

    async def _send_no_owner_message(self, chat_id: int) -> None:
        """Отправляет сообщение об отсутствии владельца"""
        try:
            error_text = """
❌ <b>Ошибка настройки бота</b>

Не удалось определить владельца группы.
Убедитесь, что группа имеет владельца (creator).

Бот будет удален из группы.
            """

            await self.telegram_chat_gateway.bot.send_message(chat_id, error_text, parse_mode="HTML")
            
            # Покидаем группу
            await self.telegram_chat_gateway.leave_chat(chat_id)
            
        except Exception as e:
            logger.error(f"Error sending no owner message: {e}")

    async def _send_ownership_conflict_message(
        self,
        chat_id: int,
        existing_owner_id: int,
        new_owner_id: int
    ) -> None:
        """Отправляет сообщение о конфликте владения"""
        try:
            conflict_text = f"""
⚠️ <b>Конфликт владения группой</b>

Эта группа уже принадлежит другому пользователю.
Текущий владелец: <a href="tg://user?id={existing_owner_id}">Пользователь</a>

Каждая группа может принадлежать только одному пользователю.
            """

            await self.telegram_chat_gateway.bot.send_message(chat_id, conflict_text, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Error sending ownership conflict message: {e}")


def register_auto_chat_detection_handlers(
    dp: Router,
    user_repository: UserRepository,
    chat_repository: ChatRepository,
    telegram_chat_gateway: TelegramChatGateway
):
    """Регистрирует обработчики автоматического определения чатов"""
    handler = AutoChatDetectionHandler(user_repository, chat_repository, telegram_chat_gateway)

    # Обработчик добавления/удаления бота из группы (используем my_chat_member, а не message)
    dp.my_chat_member.register(
        handler.handle_bot_added_to_group,
        ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)
    )

    dp.my_chat_member.register(
        handler.handle_bot_removed_from_group,
        ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER)
    )

    # Обработчик новых участников (это остается на message)
    dp.message.register(
        handler.handle_new_member,
        F.new_chat_members
    )

    logger.info("🤖 Auto chat detection handlers registered")
