# src/delivery/telegram/handlers/chat_management.py
"""
Обработчики для управления группами через интерактивную клавиатуру
"""

import logging
from typing import List
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData

from ....domain.entity.user import User
from ....domain.entity.chat import Chat
from ....adapter.repository.user_repository import UserRepository
from ....adapter.repository.chat_repository import ChatRepository

logger = logging.getLogger(__name__)
router = Router()


class ChatCallback(CallbackData, prefix="chat"):
    """Callback data для управления группами"""
    action: str
    chat_id: int = 0
    value: str = ""


class ChatManagementState(StatesGroup):
    waiting_for_threshold_value = State()
    waiting_for_system_prompt = State()


class ChatManagementHandler:
    """Обработчик команд для управления группами"""

    def __init__(self, user_repository: UserRepository, chat_repository: ChatRepository):
        self.user_repository = user_repository
        self.chat_repository = chat_repository
        logger.info("🏠 Chat Management Handler инициализирован")

    def _create_chat_list_keyboard(self, chats: List[Chat]) -> InlineKeyboardMarkup:
        """Создает клавиатуру со списком групп"""
        buttons = []

        for chat in chats:
            status_emoji = "🟢" if chat.is_active else "🔴"
            monitor_emoji = "👁️" if chat.is_monitored else "🚫"

            button_text = f"{status_emoji}{monitor_emoji} {chat.display_name[:30]}"
            buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=ChatCallback(action="select", chat_id=chat.telegram_id).pack()
                )
            ])

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def _create_chat_menu_keyboard(self, chat: Chat) -> InlineKeyboardMarkup:
        """Создает клавиатуру управления конкретной группой"""
        monitor_text = "🚫 Выключить мониторинг" if chat.is_monitored else "👁️ Включить мониторинг"

        buttons = [
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data=ChatCallback(action="stats", chat_id=chat.telegram_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data=ChatCallback(action="settings", chat_id=chat.telegram_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text=monitor_text,
                    callback_data=ChatCallback(action="toggle_monitoring", chat_id=chat.telegram_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Изменить порог спама",
                    callback_data=ChatCallback(action="set_threshold", chat_id=chat.telegram_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Системный промпт",
                    callback_data=ChatCallback(action="system_prompt", chat_id=chat.telegram_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить группу",
                    callback_data=ChatCallback(action="delete_confirm", chat_id=chat.telegram_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад к списку",
                    callback_data=ChatCallback(action="back_to_list").pack()
                )
            ]
        ]

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def _create_delete_confirm_keyboard(self, chat_id: int) -> InlineKeyboardMarkup:
        """Создает клавиатуру подтверждения удаления"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=ChatCallback(action="delete", chat_id=chat_id).pack()
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=ChatCallback(action="select", chat_id=chat_id).pack()
                )
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def cmd_manage(self, message: types.Message, user: User, **kwargs) -> None:
        """Команда /manage - показывает список групп с клавиатурой"""
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

            text = "🏠 <b>Выберите группу для управления:</b>\n\n"
            text += f"📊 Всего групп: {len(chats)}"

            keyboard = self._create_chat_list_keyboard(chats)
            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in cmd_manage: {e}")
            await message.reply("❌ Ошибка при получении списка групп.")

    async def cmd_my_chats(self, message: types.Message, user: User, **kwargs) -> None:
        """Команда /my_chats - показывает список групп (алиас для /manage)"""
        await self.cmd_manage(message, user, **kwargs)

    async def callback_select_chat(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, **kwargs) -> None:
        """Обработка выбора группы из списка"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            status_emoji = "🟢" if chat.is_active else "🔴"
            monitor_emoji = "👁️" if chat.is_monitored else "🚫"

            text = f"⚙️ <b>Управление группой:</b> {chat.display_name}\n\n"
            text += f"💬 Chat ID: <code>{chat.telegram_id}</code>\n"
            text += f"📊 Статус: {status_emoji} {'Активна' if chat.is_active else 'Неактивна'}\n"
            text += f"👁️ Мониторинг: {monitor_emoji} {'Включен' if chat.is_monitored else 'Выключен'}\n"
            text += f"🎯 Порог спама: {chat.spam_threshold}\n"
            text += f"📅 Добавлена: {chat.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            text += "Выберите действие:"

            keyboard = self._create_chat_menu_keyboard(chat)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

        except Exception as e:
            logger.error(f"Error in callback_select_chat: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def callback_stats(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, **kwargs) -> None:
        """Показать статистику группы"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            stats = await self.chat_repository.get_chat_stats(user.telegram_id)

            text = f"📊 <b>Статистика группы:</b> {chat.display_name}\n\n"
            text += f"💬 Chat ID: <code>{chat.telegram_id}</code>\n"
            text += f"📅 Добавлена: {chat.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            text += f"👁️ Мониторинг: {'Включен' if chat.is_monitored else 'Выключен'}\n"
            text += f"🎯 Порог спама: {chat.spam_threshold}\n\n"
            text += f"📈 <b>Общая статистика:</b>\n"
            text += f"• Всего групп: {stats.get('total_chats', 0)}\n"
            text += f"• Активных: {stats.get('active_chats', 0)}\n"
            text += f"• С мониторингом: {stats.get('monitored_chats', 0)}"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=ChatCallback(action="select", chat_id=chat.telegram_id).pack()
                )
            ]])

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

        except Exception as e:
            logger.error(f"Error in callback_stats: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def callback_settings(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, **kwargs) -> None:
        """Показать настройки группы"""
        await self.callback_select_chat(callback, callback_data, user, **kwargs)

    async def callback_toggle_monitoring(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, **kwargs) -> None:
        """Переключить мониторинг"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            chat.is_monitored = not chat.is_monitored
            await self.chat_repository.update_chat(chat)

            status = "включен" if chat.is_monitored else "выключен"
            await callback.answer(f"✅ Мониторинг {status}", show_alert=True)

            # Обновляем меню
            await self.callback_select_chat(callback, callback_data, user, **kwargs)

        except Exception as e:
            logger.error(f"Error in callback_toggle_monitoring: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def callback_set_threshold(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, state: FSMContext, **kwargs) -> None:
        """Запросить новый порог спама"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            await state.update_data(chat_id=chat.telegram_id)
            await state.set_state(ChatManagementState.waiting_for_threshold_value)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=ChatCallback(action="select", chat_id=chat.telegram_id).pack()
                )
            ]])

            text = (
                f"🎯 <b>Установка порога спама для:</b> {chat.display_name}\n\n"
                f"Текущий порог: {chat.spam_threshold}\n\n"
                "Введите новое значение от 0.0 до 1.0:"
            )

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

        except Exception as e:
            logger.error(f"Error in callback_set_threshold: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def handle_threshold_input(self, message: types.Message, user: User, state: FSMContext, **kwargs) -> None:
        """Обработка ввода порога спама"""
        try:
            data = await state.get_data()
            chat_id = data.get("chat_id")

            if not chat_id:
                await message.reply("❌ Ошибка: группа не выбрана")
                await state.clear()
                return

            try:
                threshold = float(message.text)
                if not (0.0 <= threshold <= 1.0):
                    await message.reply("❌ Порог должен быть от 0.0 до 1.0")
                    return
            except ValueError:
                await message.reply("❌ Неверный формат числа")
                return

            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(chat_id, user.telegram_id)
            if not chat:
                await message.reply("❌ Группа не найдена")
                await state.clear()
                return

            chat.spam_threshold = threshold
            await self.chat_repository.update_chat(chat)

            text = f"✅ Порог спама для <b>{chat.display_name}</b> установлен: {threshold}\n\n"
            text += f"⚙️ <b>Управление группой:</b> {chat.display_name}\n\n"
            text += f"💬 Chat ID: <code>{chat.telegram_id}</code>\n"
            text += f"📊 Статус: {'🟢 Активна' if chat.is_active else '🔴 Неактивна'}\n"
            text += f"👁️ Мониторинг: {'🟢 Включен' if chat.is_monitored else '🚫 Выключен'}\n"
            text += f"🎯 Порог спама: {chat.spam_threshold}\n\n"
            text += "Выберите действие:"

            keyboard = self._create_chat_menu_keyboard(chat)
            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
            await state.clear()

        except Exception as e:
            logger.error(f"Error in handle_threshold_input: {e}")
            await message.reply("❌ Ошибка при установке порога")
            await state.clear()

    async def callback_system_prompt(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, state: FSMContext, **kwargs) -> None:
        """Показать/установить системный промпт для группы"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            await state.update_data(chat_id=chat.telegram_id)
            await state.set_state(ChatManagementState.waiting_for_system_prompt)

            from ....domain.service.prompt_factory import PromptFactory
            default_prompt = PromptFactory.get_default_user_instructions()

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑️ Очистить (использовать по умолчанию)",
                        callback_data=ChatCallback(action="clear_prompt", chat_id=chat.telegram_id).pack()
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=ChatCallback(action="select", chat_id=chat.telegram_id).pack()
                    )
                ]
            ])

            text = f"📝 <b>Системный промпт для:</b> {chat.display_name}\n\n"

            if chat.system_prompt:
                text += f"📝 <b>Текущий промпт:</b>\n{chat.system_prompt}\n\n"
            else:
                text += f"📄 <b>Используется промпт по умолчанию:</b>\n{default_prompt}\n\n"

            text += "⌨️ Введите новый системный промпт для этой группы или нажмите 'Очистить' для использования промпта по умолчанию."

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

        except Exception as e:
            logger.error(f"Error in callback_system_prompt: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def callback_delete_confirm(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, **kwargs) -> None:
        """Подтверждение удаления группы"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            text = f"⚠️ <b>Подтвердите удаление</b>\n\n"
            text += f"Группа: {chat.display_name}\n"
            text += f"Chat ID: <code>{chat.telegram_id}</code>\n\n"
            text += "Бот больше не будет мониторить эту группу."

            keyboard = self._create_delete_confirm_keyboard(chat.telegram_id)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

        except Exception as e:
            logger.error(f"Error in callback_delete_confirm: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def callback_delete(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, **kwargs) -> None:
        """Удаление группы"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            success = await self.chat_repository.delete_chat(callback_data.chat_id, user.telegram_id)

            if success:
                await callback.answer(f"✅ Группа {chat.display_name} удалена", show_alert=True)

                # Возвращаемся к списку групп
                chats = await self.chat_repository.get_user_chats(user.telegram_id, active_only=True)

                if not chats:
                    await callback.message.edit_text(
                        "📭 У вас больше нет активных групп.\n\n"
                        "Добавьте бота в группу для начала работы."
                    )
                else:
                    text = "🏠 <b>Выберите группу для управления:</b>\n\n"
                    text += f"📊 Всего групп: {len(chats)}"
                    keyboard = self._create_chat_list_keyboard(chats)
                    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await callback.answer("❌ Ошибка при удалении", show_alert=True)

        except Exception as e:
            logger.error(f"Error in callback_delete: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def handle_system_prompt_input(self, message: types.Message, user: User, state: FSMContext, **kwargs) -> None:
        """Обработка ввода системного промпта"""
        try:
            data = await state.get_data()
            chat_id = data.get("chat_id")

            if not chat_id:
                await message.reply("❌ Ошибка: группа не выбрана")
                await state.clear()
                return

            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(chat_id, user.telegram_id)
            if not chat:
                await message.reply("❌ Группа не найдена")
                await state.clear()
                return

            # Устанавливаем новый системный промпт
            chat.system_prompt = message.text.strip()
            await self.chat_repository.update_chat(chat)

            text = f"✅ Системный промпт для <b>{chat.display_name}</b> установлен!\n\n"
            text += f"⚙️ <b>Управление группой:</b> {chat.display_name}\n\n"
            text += f"💬 Chat ID: <code>{chat.telegram_id}</code>\n"
            text += f"📊 Статус: {'🟢 Активна' if chat.is_active else '🔴 Неактивна'}\n"
            text += f"👁️ Мониторинг: {'🟢 Включен' if chat.is_monitored else '🚫 Выключен'}\n"
            text += f"🎯 Порог спама: {chat.spam_threshold}\n\n"
            text += "Выберите действие:"

            keyboard = self._create_chat_menu_keyboard(chat)
            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
            await state.clear()

        except Exception as e:
            logger.error(f"Error in handle_system_prompt_input: {e}")
            await message.reply("❌ Ошибка при установке промпта")
            await state.clear()

    async def callback_clear_prompt(self, callback: types.CallbackQuery, callback_data: ChatCallback, user: User, state: FSMContext, **kwargs) -> None:
        """Очистить системный промпт (использовать по умолчанию)"""
        try:
            chat = await self.chat_repository.get_chat_by_telegram_id_and_owner(
                callback_data.chat_id, user.telegram_id
            )

            if not chat:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return

            chat.system_prompt = None
            await self.chat_repository.update_chat(chat)
            await state.clear()

            await callback.answer("✅ Системный промпт очищен. Используется промпт по умолчанию.", show_alert=True)

            # Обновляем меню
            await self.callback_select_chat(callback, callback_data, user, **kwargs)

        except Exception as e:
            logger.error(f"Error in callback_clear_prompt: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)

    async def callback_back_to_list(self, callback: types.CallbackQuery, user: User, **kwargs) -> None:
        """Вернуться к списку групп"""
        try:
            chats = await self.chat_repository.get_user_chats(user.telegram_id, active_only=True)

            if not chats:
                await callback.message.edit_text("📭 У вас нет активных групп.")
                await callback.answer()
                return

            text = "🏠 <b>Выберите группу для управления:</b>\n\n"
            text += f"📊 Всего групп: {len(chats)}"

            keyboard = self._create_chat_list_keyboard(chats)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

        except Exception as e:
            logger.error(f"Error in callback_back_to_list: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)


def register_chat_management_handlers(
    dp: Router,
    user_repository: UserRepository,
    chat_repository: ChatRepository
):
    """Регистрирует обработчики команд управления группами"""
    handler = ChatManagementHandler(user_repository, chat_repository)

    # Основная команда управления
    dp.message.register(handler.cmd_manage, Command("manage"))
    dp.message.register(handler.cmd_my_chats, Command("my_chats"))

    # Callback handlers
    dp.callback_query.register(
        handler.callback_select_chat,
        ChatCallback.filter(F.action == "select")
    )
    dp.callback_query.register(
        handler.callback_stats,
        ChatCallback.filter(F.action == "stats")
    )
    dp.callback_query.register(
        handler.callback_settings,
        ChatCallback.filter(F.action == "settings")
    )
    dp.callback_query.register(
        handler.callback_toggle_monitoring,
        ChatCallback.filter(F.action == "toggle_monitoring")
    )
    dp.callback_query.register(
        handler.callback_set_threshold,
        ChatCallback.filter(F.action == "set_threshold")
    )
    dp.callback_query.register(
        handler.callback_system_prompt,
        ChatCallback.filter(F.action == "system_prompt")
    )
    dp.callback_query.register(
        handler.callback_delete_confirm,
        ChatCallback.filter(F.action == "delete_confirm")
    )
    dp.callback_query.register(
        handler.callback_delete,
        ChatCallback.filter(F.action == "delete")
    )
    dp.callback_query.register(
        handler.callback_back_to_list,
        ChatCallback.filter(F.action == "back_to_list")
    )

    dp.callback_query.register(
        handler.callback_clear_prompt,
        ChatCallback.filter(F.action == "clear_prompt")
    )

    # FSM handlers
    dp.message.register(
        handler.handle_threshold_input,
        ChatManagementState.waiting_for_threshold_value
    )
    dp.message.register(
        handler.handle_system_prompt_input,
        ChatManagementState.waiting_for_system_prompt
    )

    logger.info("🏠 Chat management handlers registered")