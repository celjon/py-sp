# src/delivery/telegram/handlers/chat_management.py
"""
Обработчики для управления группами с изоляцией пользователей
"""

import logging
from typing import Dict, Any, Optional
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from ....domain.entity.user import User
from ....domain.entity.chat import Chat, ChatType
from ....adapter.repository.user_repository import UserRepository
from ....adapter.repository.chat_repository import ChatRepository

logger = logging.getLogger(__name__)
router = Router()


class ChatManagementState(StatesGroup):
    waiting_for_chat_title = State()
    waiting_for_spam_threshold = State()


class ChatManagementHandler:
    """Обработчик команд для управления группами"""

    def __init__(self, user_repository: UserRepository, chat_repository: ChatRepository):
        self.user_repository = user_repository
        self.chat_repository = chat_repository
        logger.info("🏠 Chat Management Handler инициализирован")

    async def cmd_my_chats(
        self,
        message: types.Message,
        user: User,
        **kwargs
    ) -> None:
        """
        Команда /my_chats - показывает все группы пользователя
        """
        try:
            chats = await self.chat_repository.get_user_chats(user.telegram_id, active_only=True)
            
            if not chats:
                await message.reply(
                    "📭 У вас пока нет добавленных групп.\n\n"
                    "🤖 <b>Автоматическое добавление:</b>\n"
                    "1. Добавьте бота в вашу группу\n"
                    "2. Дайте боту права администратора\n"
                    "3. Бот автоматически определит вас как владельца!\n\n"
                    "💡 <b>Совет:</b> Убедитесь, что вы являетесь создателем (owner) группы.",
                    parse_mode="HTML"
                )
                return

            text = "🏠 <b>Ваши группы:</b>\n\n"
            
            for i, chat in enumerate(chats, 1):
                status_emoji = "🟢" if chat.is_active else "🔴"
                monitor_emoji = "👁️" if chat.is_monitored else "🚫"
                
                text += f"{i}. {status_emoji} {monitor_emoji} <b>{chat.display_name}</b>\n"
                text += f"   ID: <code>{chat.telegram_id}</code>\n"
                text += f"   Тип: {chat.type.value}\n"
                text += f"   Порог спама: {chat.spam_threshold}\n"
                
                if chat.username:
                    text += f"   @{chat.username}\n"
                
                text += "\n"

            text += f"📊 Всего групп: {len(chats)}"
            
            await message.reply(text, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Error in cmd_my_chats: {e}")
            await message.reply("❌ Ошибка при получении списка групп.")

    async def cmd_auto_setup_info(
        self,
        message: types.Message,
        user: User,
        **kwargs
    ) -> None:
        """
        Команда /auto_setup - информация об автоматической настройке
        """
        await message.reply(
            "🤖 <b>Автоматическая настройка бота</b>\n\n"
            "✅ <b>Как это работает:</b>\n"
            "1. Добавьте бота в вашу группу\n"
            "2. Дайте боту права администратора\n"
            "3. Бот автоматически определит вас как владельца!\n\n"
            "🔍 <b>Требования:</b>\n"
            "• Вы должны быть создателем (owner) группы\n"
            "• Бот должен иметь права администратора\n"
            "• Группа должна быть активной\n\n"
            "💡 <b>После добавления:</b>\n"
            "• Бот отправит приветственное сообщение\n"
            "• Группа будет добавлена в ваш список\n"
            "• Настройте токен BotHub командой /bothub_token\n\n"
            "❓ <b>Проблемы?</b>\n"
            "• Убедитесь, что вы - создатель группы\n"
            "• Проверьте права бота в группе\n"
            "• Используйте /my_chats для проверки",
            parse_mode="HTML"
        )

    async def cmd_remove_chat(
        self,
        message: types.Message,
        user: User,
        **kwargs
    ) -> None:
        """
        Команда /remove_chat - удаляет группу из управления пользователя
        """
        if message.chat.type == "private":
            await message.reply(
                "❌ Эта команда работает только в группах.\n\n"
                "Используйте /my_chats для просмотра ваших групп."
            )
            return

        try:
            # Проверяем владение группой
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                message.chat.id, user.telegram_id
            )
            
            if not chat:
                await message.reply(
                    "❌ Эта группа не принадлежит вам или не найдена.\n\n"
                    "Используйте /my_chats для просмотра ваших групп."
                )
                return

            # Удаляем группу
            success = await self.chat_repository.delete_chat(message.chat.id, user.telegram_id)
            
            if success:
                await message.reply(
                    f"✅ Группа <b>{chat.display_name}</b> удалена из вашего списка.\n\n"
                    "Бот больше не будет мониторить эту группу.",
                    parse_mode="HTML"
                )
                logger.info(f"Chat {message.chat.id} removed by user {user.telegram_id}")
            else:
                await message.reply("❌ Ошибка при удалении группы.")
                
        except Exception as e:
            logger.error(f"Error in cmd_remove_chat: {e}")
            await message.reply("❌ Ошибка при удалении группы.")

    async def cmd_chat_settings(
        self,
        message: types.Message,
        user: User,
        **kwargs
    ) -> None:
        """
        Команда /chat_settings - настройки текущей группы
        """
        if message.chat.type == "private":
            await message.reply(
                "❌ Эта команда работает только в группах.\n\n"
                "Используйте /my_chats для просмотра ваших групп."
            )
            return

        try:
            # Проверяем владение группой
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                message.chat.id, user.telegram_id
            )
            
            if not chat:
                await message.reply(
                    "❌ Эта группа не принадлежит вам.\n\n"
                    "Используйте /add_chat для добавления группы."
                )
                return

            status_emoji = "🟢" if chat.is_active else "🔴"
            monitor_emoji = "👁️" if chat.is_monitored else "🚫"
            
            text = f"⚙️ <b>Настройки группы:</b> {chat.display_name}\n\n"
            text += f"📊 Статус: {status_emoji} {'Активна' if chat.is_active else 'Неактивна'}\n"
            text += f"👁️ Мониторинг: {monitor_emoji} {'Включен' if chat.is_monitored else 'Выключен'}\n"
            text += f"🎯 Порог спама: {chat.spam_threshold}\n"
            text += f"📅 Добавлена: {chat.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            
            text += "🔧 <b>Доступные команды:</b>\n"
            text += "• /toggle_monitoring - включить/выключить мониторинг\n"
            text += "• /set_spam_threshold - изменить порог спама\n"
            text += "• /chat_stats - статистика группы\n"
            
            await message.reply(text, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Error in cmd_chat_settings: {e}")
            await message.reply("❌ Ошибка при получении настроек группы.")

    async def cmd_toggle_monitoring(
        self,
        message: types.Message,
        user: User,
        **kwargs
    ) -> None:
        """
        Команда /toggle_monitoring - переключает мониторинг группы
        """
        if message.chat.type == "private":
            await message.reply("❌ Эта команда работает только в группах.")
            return

        try:
            # Проверяем владение группой
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                message.chat.id, user.telegram_id
            )
            
            if not chat:
                await message.reply("❌ Эта группа не принадлежит вам.")
                return

            # Переключаем мониторинг
            chat.is_monitored = not chat.is_monitored
            await self.chat_repository.update_chat(chat)
            
            status = "включен" if chat.is_monitored else "выключен"
            emoji = "👁️" if chat.is_monitored else "🚫"
            
            await message.reply(
                f"{emoji} Мониторинг группы <b>{chat.display_name}</b> {status}.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Error in cmd_toggle_monitoring: {e}")
            await message.reply("❌ Ошибка при изменении настроек мониторинга.")

    async def cmd_set_spam_threshold(
        self,
        message: types.Message,
        user: User,
        state: FSMContext,
        **kwargs
    ) -> None:
        """
        Команда /set_spam_threshold - устанавливает порог спама
        """
        if message.chat.type == "private":
            await message.reply("❌ Эта команда работает только в группах.")
            return

        try:
            # Проверяем владение группой
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                message.chat.id, user.telegram_id
            )
            
            if not chat:
                await message.reply("❌ Эта группа не принадлежит вам.")
                return

            # Парсим аргументы команды
            args = message.text.split()[1:] if len(message.text.split()) > 1 else []
            
            if args:
                try:
                    threshold = float(args[0])
                    if 0.0 <= threshold <= 1.0:
                        chat.spam_threshold = threshold
                        await self.chat_repository.update_chat(chat)
                        
                        await message.reply(
                            f"✅ Порог спама для группы <b>{chat.display_name}</b> установлен: {threshold}",
                            parse_mode="HTML"
                        )
                    else:
                        await message.reply("❌ Порог спама должен быть от 0.0 до 1.0")
                except ValueError:
                    await message.reply("❌ Неверный формат числа. Используйте: /set_spam_threshold 0.7")
            else:
                await message.reply(
                    f"📊 Текущий порог спама: {chat.spam_threshold}\n\n"
                    "Используйте: /set_spam_threshold 0.7"
                )
                
        except Exception as e:
            logger.error(f"Error in cmd_set_spam_threshold: {e}")
            await message.reply("❌ Ошибка при изменении порога спама.")

    async def cmd_chat_stats(
        self,
        message: types.Message,
        user: User,
        **kwargs
    ) -> None:
        """
        Команда /chat_stats - статистика группы
        """
        if message.chat.type == "private":
            await message.reply("❌ Эта команда работает только в группах.")
            return

        try:
            # Проверяем владение группой
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                message.chat.id, user.telegram_id
            )
            
            if not chat:
                await message.reply("❌ Эта группа не принадлежит вам.")
                return

            # Получаем статистику (здесь можно добавить реальную статистику)
            stats = await self.chat_repository.get_chat_stats(user.telegram_id)
            
            text = f"📊 <b>Статистика группы:</b> {chat.display_name}\n\n"
            text += f"📅 Добавлена: {chat.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            text += f"👁️ Мониторинг: {'Включен' if chat.is_monitored else 'Выключен'}\n"
            text += f"🎯 Порог спама: {chat.spam_threshold}\n\n"
            
            text += f"📈 <b>Общая статистика:</b>\n"
            text += f"• Всего групп: {stats.get('total_chats', 0)}\n"
            text += f"• Активных: {stats.get('active_chats', 0)}\n"
            text += f"• С мониторингом: {stats.get('monitored_chats', 0)}\n"
            
            await message.reply(text, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Error in cmd_chat_stats: {e}")
            await message.reply("❌ Ошибка при получении статистики группы.")


def register_chat_management_handlers(
    dp: Router, 
    user_repository: UserRepository, 
    chat_repository: ChatRepository
):
    """Регистрирует обработчики команд управления группами"""
    handler = ChatManagementHandler(user_repository, chat_repository)

    dp.message.register(handler.cmd_my_chats, Command("my_chats"))
    dp.message.register(handler.cmd_auto_setup_info, Command("auto_setup"))
    dp.message.register(handler.cmd_remove_chat, Command("remove_chat"))
    dp.message.register(handler.cmd_chat_settings, Command("chat_settings"))
    dp.message.register(handler.cmd_toggle_monitoring, Command("toggle_monitoring"))
    dp.message.register(handler.cmd_set_spam_threshold, Command("set_spam_threshold"))
    dp.message.register(handler.cmd_chat_stats, Command("chat_stats"))

    logger.info("🏠 Chat management handlers registered")
