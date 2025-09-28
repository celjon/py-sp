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
            if event.new_chat_member.status in ["member", "administrator"]:
                chat_id = event.chat.id
                
                logger.info(f"Bot added to group {chat_id}: {event.chat.title}")
                
                chat_info = await self.telegram_chat_gateway.get_chat_info(chat_id)
                if not chat_info:
                    logger.error(f"Could not get chat info for {chat_id}")
                    return
                
                owner_info = await self.telegram_chat_gateway.get_chat_owner(chat_id)
                if not owner_info:
                    logger.warning(f"No owner found for chat {chat_id}")
                    await self._send_no_owner_message(chat_id)
                    return
                
                owner_user_id = owner_info["user_id"]
                logger.info(f"Chat {chat_id} owner: {owner_user_id}")
                
                existing_chat = await self.chat_repository.get_chat_by_telegram_id(chat_id)
                if existing_chat:
                    logger.info(f"Chat {chat_id} already exists, owner: {existing_chat.owner_user_id} - skipping creation")
                    if existing_chat.owner_user_id != owner_user_id:
                        await self._send_ownership_conflict_message(chat_id, existing_chat.owner_user_id, owner_user_id)
                    else:
                        if not existing_chat.is_active:
                            existing_chat.is_active = True
                            await self.chat_repository.update_chat(existing_chat)
                            logger.info(f"Chat {chat_id} reactivated")
                    return
                
                user = await self.user_repository.get_user(owner_user_id)
                if not user:
                    user = await self.user_repository.create_user(
                        telegram_id=owner_user_id,
                        username=owner_info.get("username"),
                        first_name=owner_info.get("first_name"),
                        last_name=owner_info.get("last_name")
                    )
                    logger.info(f"Created new user: {owner_user_id}")
                
                initial_system_prompt = None
                if user.bothub_configured and user.system_prompt:
                    initial_system_prompt = user.system_prompt

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
                    system_prompt=initial_system_prompt,
                )
                
                await self.chat_repository.create_chat(chat)
                
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
            if event.new_chat_member.status in ["left", "kicked"]:
                chat_id = event.chat.id
                
                logger.info(f"Bot removed from group {chat_id}: {event.chat.title}")
                
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

                chat = await self.chat_repository.get_chat_by_telegram_id(chat_id)
                if not chat or not chat.is_active:
                    return

                for member in message.new_chat_members:
                    if not member.is_bot:
                        logger.info(f"New member {member.id} joined chat {chat_id}")

            try:
                await message.delete()
                logger.info(f"🗑️ Удалено служебное сообщение о присоединении")
            except Exception as e:
                logger.debug(f"Could not delete service message: {e}")

        except Exception as e:
            logger.error(f"Error in handle_new_member: {e}")

    async def handle_group_to_supergroup_migration(
        self,
        message: types.Message,
        **kwargs
    ) -> None:
        """
        Обрабатывает миграцию группы в супергруппу
        Обновляет chat_id в базе данных
        """
        try:
            old_chat_id = message.chat.id
            new_chat_id = message.migrate_to_chat_id

            logger.info(f"Group migration detected: {old_chat_id} -> {new_chat_id}")

            old_chat = await self.chat_repository.get_chat_by_telegram_id(old_chat_id)
            if old_chat:
                old_chat.telegram_id = new_chat_id
                old_chat.type = ChatType.SUPERGROUP

                await self.chat_repository.update_chat(old_chat)
                logger.info(f"Chat {old_chat_id} migrated to supergroup {new_chat_id}")
            else:
                logger.warning(f"Chat {old_chat_id} not found in database during migration")

        except Exception as e:
            logger.error(f"Error handling group migration: {e}")

    async def _send_welcome_message_to_owner(self, chat_id: int, owner_user_id: int, chat_title: str) -> None:
        """Отправляет приветственное сообщение владельцу в личку"""
        try:
            welcome_text = f"""
🎉 <b>Бот успешно добавлен в группу!</b>

📋 <b>Группа:</b> {chat_title}
👤 <b>Владелец:</b> Пользователь

✅ <b>Автоматическая настройка завершена!</b>

⚠️ <b>ВАЖНО:</b> Для корректной работы антиспама необходимо:
1. 👑 <b>Назначить боту права администратора</b> в группе (для банов и удаления сообщений)
2. 🔑 <b>Настроить токен BotHub</b> командой /bothub (для ИИ детекции)

<b>💫 Интерактивное управление (в личном чате):</b>
/manage - 🏠 Управление группами с интерактивным меню:
   • Включение/выключение антиспам защиты
   • Настройка порога спама (0.0 - 1.0)
   • Просмотр статистики группы
   • Просмотр забаненных пользователей с разбаном
   • Управление уведомлениями о банах
   • Настройка системного промпта для ИИ

/bothub - 🤖 Настройки BotHub ИИ (клавиатура)

<b>🛡️ Антиспам система:</b>
• Автоматическая детекция спама через CAS + RUSpam + BotHub ИИ
• Настраиваемый порог срабатывания (по умолчанию 0.7)
• Уведомления владельцу группы о банах с кнопкой разбана
• Возможность отключения защиты для конкретной группы
• Все управление через интерактивные меню в личном чате

<b>🤖 Справка по BotHub:</b>
BotHub - это API для работы с языковыми моделями ИИ.
Бот использует его для детекции спама.

🔗 <b>Получение токена BotHub:</b>
1. Перейдите на https://bothub.chat
2. Зарегистрируйтесь или войдите в аккаунт
3. Получите токен доступа к API
4. Используйте /bothub для настройки

🤖 Бот готов к работе!
            """

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

    dp.my_chat_member.register(
        handler.handle_bot_added_to_group,
        ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)
    )

    dp.my_chat_member.register(
        handler.handle_bot_removed_from_group,
        ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER)
    )

    dp.message.register(
        handler.handle_new_member,
        F.new_chat_members
    )

    dp.message.register(
        handler.handle_group_to_supergroup_migration,
        F.migrate_to_chat_id
    )

    logger.info("🤖 Auto chat detection handlers registered")
