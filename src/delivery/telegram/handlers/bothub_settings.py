"""
Telegram обработчики для управления настройками BotHub
"""

import logging
from typing import Dict, Any, Optional
from aiogram import types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters.callback_data import CallbackData

from ....domain.entity.user import User
from ....adapter.gateway.bothub_gateway import BotHubGateway
from ....domain.service.prompt_factory import PromptFactory

logger = logging.getLogger(__name__)


class BotHubCallback(CallbackData, prefix="bothub"):
    """Callback data для управления BotHub настройками"""
    action: str
    value: str = ""


class BotHubSettingsStates(StatesGroup):
    """Состояния для FSM управления настройками BotHub"""
    waiting_for_token = State()
    waiting_for_prompt = State()
    waiting_for_model = State()


class BotHubSettingsHandler:
    """Обработчик команд управления настройками BotHub"""
    
    def __init__(self):
        self.default_user_instructions = PromptFactory.get_default_user_instructions()

    def _clear_bothub_cache_for_user(self, user_id: int, deps: dict = None, action: str = "setting update") -> None:
        """Очищает кэш BotHub детекторов для пользователя"""
        if not deps:
            return

        ensemble_detector = deps.get("ensemble_detector")
        if ensemble_detector and hasattr(ensemble_detector, 'clear_bothub_cache_for_user'):
            ensemble_detector.clear_bothub_cache_for_user(user_id)
            logger.info(f"[CACHE] Cleared BotHub cache for user {user_id} after {action}")

    def _create_main_menu_keyboard(self, user: User) -> InlineKeyboardMarkup:
        """Создает главное меню BotHub настроек"""
        token_status = "✅ Настроен" if user.bothub_token else "❌ Не настроен"
        prompt_status = "✅ Настроен" if user.system_prompt else "📄 По умолчанию"
        model_status = user.bothub_model or "gpt-5-nano"

        buttons = [
            [
                InlineKeyboardButton(
                    text=f"🔑 Токен: {token_status}",
                    callback_data=BotHubCallback(action="token_menu").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🤖 Промпт: {prompt_status}",
                    callback_data=BotHubCallback(action="prompt_menu").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🎯 Модель: {model_status}",
                    callback_data=BotHubCallback(action="model_menu").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статус и статистика",
                    callback_data=BotHubCallback(action="status").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="🆘 Справка",
                    callback_data=BotHubCallback(action="help").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Сбросить всё",
                    callback_data=BotHubCallback(action="reset_confirm").pack()
                )
            ]
        ]

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def _create_token_menu_keyboard(self, has_token: bool) -> InlineKeyboardMarkup:
        """Создает меню управления токеном"""
        if has_token:
            buttons = [
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить токен",
                        callback_data=BotHubCallback(action="update_token").pack()
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Удалить токен",
                        callback_data=BotHubCallback(action="delete_token").pack()
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="◀️ Назад в меню",
                        callback_data=BotHubCallback(action="main_menu").pack()
                    )
                ]
            ]
        else:
            buttons = [
                [
                    InlineKeyboardButton(
                        text="➕ Добавить токен",
                        callback_data=BotHubCallback(action="add_token").pack()
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="◀️ Назад в меню",
                        callback_data=BotHubCallback(action="main_menu").pack()
                    )
                ]
            ]

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def _create_prompt_menu_keyboard(self, has_prompt: bool) -> InlineKeyboardMarkup:
        """Создает меню управления промптом"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="👁️ Показать текущий",
                    callback_data=BotHubCallback(action="show_prompt").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=BotHubCallback(action="edit_prompt").pack()
                )
            ]
        ]

        if has_prompt:
            buttons.append([
                InlineKeyboardButton(
                    text="🔄 Сбросить к умолчанию",
                    callback_data=BotHubCallback(action="reset_prompt").pack()
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="◀️ Назад в меню",
                callback_data=BotHubCallback(action="main_menu").pack()
            )
        ])

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def _create_model_menu_keyboard(self) -> InlineKeyboardMarkup:
        """Создает меню управления моделью"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="📋 Показать доступные модели",
                    callback_data=BotHubCallback(action="list_models").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Ввести название модели",
                    callback_data=BotHubCallback(action="enter_model").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад в меню",
                    callback_data=BotHubCallback(action="main_menu").pack()
                )
            ]
        ]

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def cmd_bothub(self, message: types.Message, **kwargs) -> None:
        """Команда /bothub - главное меню настроек BotHub"""
        user = kwargs.get("user")
        if not user:
            await message.reply("❌ Пользователь не найден")
            return

        is_group_owner = kwargs.get("is_group_owner", False)
        if not is_group_owner:
            await message.reply("❌ Доступ запрещен. Только для владельцев групп.")
            return

        try:
            keyboard = self._create_main_menu_keyboard(user)

            status_emoji = "✅" if user.bothub_configured else "❌"
            text = f"{status_emoji} <b>BotHub - Управление настройками</b>\n\n"

            if user.bothub_configured:
                text += "🟢 BotHub настроен и готов к работе!\n\n"
            else:
                text += "🔴 BotHub не настроен. Настройте токен для начала работы.\n\n"

            text += "📋 <b>Текущие настройки:</b>\n"
            text += f"🔑 Токен: {'✅ Настроен' if user.bothub_token else '❌ Не настроен'}\n"
            text += f"🤖 Промпт: {'✅ Настроен' if user.system_prompt else '📄 По умолчанию'}\n"
            text += f"🎯 Модель: {user.bothub_model or 'gpt-5-nano (по умолчанию)'}\n\n"
            text += "Выберите раздел для настройки:"

            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in cmd_bothub: {e}")
            await message.reply("❌ Ошибка отображения меню BotHub")

    
    async def handle_token_input(
        self,
        message: types.Message,
        user: User = None,
        state: FSMContext = None,
        deps: dict = None,
        **kwargs
    ) -> None:
        """
        Обработка ввода токена

        Args:
            message: Telegram сообщение
            user: Пользователь
            state: FSM контекст
            deps: Зависимости
        """
        try:
            if not user or not state:
                await message.reply("❌ Ошибка: данные пользователя не найдены")
                return

            user_repository = deps.get("user_repository") if deps else None
            if not user_repository:
                await message.reply("❌ Ошибка: репозиторий недоступен")
                return

            token = message.text.strip()
            
            if not token:
                await message.reply("❌ Токен не может быть пустым")
                return
            
            try:
                test_gateway = BotHubGateway(token, self.default_user_instructions)
                health = await test_gateway.health_check()
                
                if health.get("status") != "healthy":
                    await message.reply(
                        f"❌ <b>Неверный токен BotHub</b>\n\n"
                        f"Ошибка: {health.get('error', 'Неизвестная ошибка')}\n\n"
                        f"Проверьте токен и попробуйте снова.",
                        parse_mode="HTML"
                    )
                    return
                
            except Exception as e:
                await message.reply(
                    f"❌ <b>Ошибка проверки токена</b>\n\n"
                    f"Ошибка: {str(e)}\n\n"
                    f"Проверьте токен и попробуйте снова.",
                    parse_mode="HTML"
                )
                return
            
            user.bothub_token = token
            user.bothub_configured = True

            if not user.system_prompt:
                user.system_prompt = self.default_user_instructions

            await user_repository.update_user(user)

            self._clear_bothub_cache_for_user(user.telegram_id, deps, "token update")

            await state.clear()
            
            keyboard = self._create_main_menu_keyboard(user)

            text = "✅ <b>Токен BotHub успешно сохранен!</b>\n\n"
            text += f"🔗 Статус API: {health.get('status', 'unknown')}\n"
            text += f"🤖 Модель: {health.get('model', 'unknown')}\n"
            text += f"⏱️ Время ответа: {health.get('response_time_ms', 0):.0f}ms\n\n"
            text += "🟢 BotHub настроен и готов к работе!\n\n"
            text += "📋 <b>Текущие настройки:</b>\n"
            text += f"🔑 Токен: ✅ Настроен\n"
            text += f"🤖 Промпт: {'✅ Настроен' if user.system_prompt else '📄 По умолчанию'}\n"
            text += f"🎯 Модель: {user.bothub_model or 'gpt-5-nano (по умолчанию)'}\n\n"
            text += "Выберите раздел для настройки:"

            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Error handling token input: {e}")
            await message.reply("❌ Ошибка сохранения токена")
            await state.clear()
    
    
    
    
    async def handle_prompt_input(
        self,
        message: types.Message,
        user: User,
        state: FSMContext,
        deps: Dict[str, Any],
        **kwargs
    ) -> None:
        """
        Обработка ввода системного промпта
        
        Args:
            message: Telegram сообщение
            user: Пользователь
            state: FSM контекст
            user_repository: Репозиторий пользователей
        """
        try:
            user_repository = deps.get("user_repository")
            if not user_repository:
                await message.reply("❌ Ошибка системы: репозиторий недоступен")
                await state.clear()
                return

            prompt = message.text.strip()

            if not prompt:
                await message.reply("❌ Промпт не может быть пустым")
                return
            
            if len(prompt) < 50:
                await message.reply("❌ Промпт слишком короткий (минимум 50 символов)")
                return
            
            if len(prompt) > 4000:
                await message.reply("❌ Промпт слишком длинный (максимум 4000 символов)")
                return
            
            user.system_prompt = prompt
            await user_repository.update_user(user)

            self._clear_bothub_cache_for_user(user.telegram_id, deps, "prompt update")

            await state.clear()
            
            keyboard = self._create_prompt_menu_keyboard(True)

            text = "✅ <b>Системный промпт обновлен!</b>\n\n"
            text += f"✅ Настроен пользовательский промпт\n"
            text += f"📏 Длина: {len(prompt)} символов\n\n"
            text += "Промпт определяет поведение ИИ при анализе сообщений на спам.\n\n"
            text += "Выберите действие:"

            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Error handling prompt input: {e}")
            await message.reply("❌ Ошибка сохранения промпта")
            await state.clear()
    

    async def handle_model_input(
        self,
        message: types.Message,
        user: User,
        state: FSMContext,
        deps: Dict[str, Any],
        **kwargs
    ) -> None:
        try:
            user_repository = deps.get("user_repository")
            if not user_repository:
                await message.reply("❌ Ошибка системы: репозиторий недоступен")
                await state.clear()
                return

            model_name = message.text.strip()

            if not model_name:
                await message.reply("❌ Название модели не может быть пустым")
                return

            models = await BotHubGateway.get_available_models(user.bothub_token)

            model_found = None
            for model in models:
                if model['id'] == model_name or model['label'] == model_name:
                    model_found = model
                    break

            if not model_found:
                await message.reply(
                    f"❌ <b>Модель '{model_name}' не найдена</b>\n\n"
                    f"Используйте /bothub_model для просмотра доступных моделей",
                    parse_mode="HTML"
                )
                return

            user.bothub_model = model_found['id']
            await user_repository.update_user(user)

            self._clear_bothub_cache_for_user(user.telegram_id, deps, "model update")

            await state.clear()

            keyboard = self._create_model_menu_keyboard()

            text = f"✅ <b>Модель обновлена!</b>\n\n"
            text += f"📋 Текущая модель: <code>{model_found['id']}</code>\n"
            text += f"📊 Статус: ✅ Настроена\n"
            text += f"🏷️ Название: {model_found['label']}\n"
            text += f"🏢 Провайдер: {model_found.get('owned_by', 'unknown')}\n"
            text += f"📏 Контекст: {model_found.get('context_length', 'N/A')}\n\n"
            text += "Модель определяет качество и скорость анализа спама.\n\n"
            text += "Выберите действие:"

            await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error handling model input: {e}")
            await message.reply("❌ Ошибка установки модели")
            await state.clear()

    
    async def handle_callback_query(
        self,
        callback_query: types.CallbackQuery,
        callback_data: BotHubCallback,
        **kwargs
    ) -> None:
        """Обработка callback запросов для управления BotHub"""
        user = kwargs.get("user")
        state = kwargs.get("state")
        deps = kwargs.get("deps", {})

        if not user:
            await callback_query.answer("❌ Пользователь не найден", show_alert=True)
            return

        user_repository = deps.get("user_repository")
        if not user_repository:
            await callback_query.answer("❌ Ошибка: репозиторий недоступен", show_alert=True)
            return

        try:
            action = callback_data.action

            if action == "main_menu":
                await self._show_main_menu(callback_query, user)

            elif action == "token_menu":
                await self._show_token_menu(callback_query, user)
            elif action == "add_token" or action == "update_token":
                await self._start_token_input(callback_query, state)
            elif action == "delete_token":
                await self._delete_token(callback_query, user, user_repository, deps)

            elif action == "prompt_menu":
                await self._show_prompt_menu(callback_query, user)
            elif action == "show_prompt":
                await self._show_current_prompt(callback_query, user)
            elif action == "edit_prompt":
                await self._start_prompt_input(callback_query, state)
            elif action == "reset_prompt":
                await self._reset_prompt(callback_query, user, user_repository)

            elif action == "model_menu":
                await self._show_model_menu(callback_query, user)
            elif action == "list_models":
                await self._show_models_list(callback_query, user)
            elif action == "enter_model":
                await self._start_model_input(callback_query, state)

            elif action == "status":
                await self._show_status(callback_query, user)
            elif action == "help":
                await self._show_help(callback_query)

            elif action == "reset_confirm":
                await self._confirm_reset(callback_query)
            elif action == "reset_all":
                await self._reset_all_settings(callback_query, user, user_repository, deps)
            elif action == "cancel_reset":
                await self._cancel_reset(callback_query, user)

            else:
                await callback_query.answer("❌ Неизвестная команда", show_alert=True)

        except Exception as e:
            logger.error(f"Error handling callback query: {e}")
            await callback_query.answer("❌ Ошибка обработки запроса", show_alert=True)


    async def _show_main_menu(self, callback_query: types.CallbackQuery, user: User):
        """Показать главное меню"""
        keyboard = self._create_main_menu_keyboard(user)

        status_emoji = "✅" if user.bothub_configured else "❌"
        text = f"{status_emoji} <b>BotHub - Управление настройками</b>\n\n"

        if user.bothub_configured:
            text += "🟢 BotHub настроен и готов к работе!\n\n"
        else:
            text += "🔴 BotHub не настроен. Настройте токен для начала работы.\n\n"

        text += "📋 <b>Текущие настройки:</b>\n"
        text += f"🔑 Токен: {'✅ Настроен' if user.bothub_token else '❌ Не настроен'}\n"
        text += f"🤖 Промпт: {'✅ Настроен' if user.system_prompt else '📄 По умолчанию'}\n"
        text += f"🎯 Модель: {user.bothub_model or 'gpt-5-nano (по умолчанию)'}\n\n"
        text += "Выберите раздел для настройки:"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _show_token_menu(self, callback_query: types.CallbackQuery, user: User):
        """Показать меню управления токеном"""
        keyboard = self._create_token_menu_keyboard(bool(user.bothub_token))

        text = "🔑 <b>Управление токеном BotHub</b>\n\n"

        if user.bothub_token:
            text += "✅ Токен настроен и сохранен\n\n"
            text += "Токен обеспечивает доступ к API BotHub для детекции спама.\n\n"
            text += "Выберите действие:"
        else:
            text += "❌ Токен не настроен\n\n"
            text += "Для работы бота необходим токен доступа к BotHub API.\n"
            text += "Получить токен можно на: https://bothub.chat\n\n"
            text += "Выберите действие:"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _start_token_input(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Запустить ввод токена"""
        await state.set_state(BotHubSettingsStates.waiting_for_token)

        text = "🔑 <b>Ввод токена BotHub</b>\n\n"
        text += "Отправьте ваш токен доступа к BotHub API.\n\n"
        text += "📍 Получить токен: https://bothub.chat\n"
        text += "⚠️ Токен будет проверен и сохранен в базе данных"

        await callback_query.message.edit_text(text, parse_mode="HTML")
        await callback_query.answer()

    async def _delete_token(self, callback_query: types.CallbackQuery, user: User, user_repository, deps: dict = None):
        """Удалить токен"""
        user.bothub_token = None
        user.bothub_configured = False
        await user_repository.update_user(user)

        self._clear_bothub_cache_for_user(user.telegram_id, deps, "token deletion")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="◀️ Назад в меню",
                callback_data=BotHubCallback(action="main_menu").pack()
            )
        ]])

        text = "✅ <b>Токен BotHub удален</b>\n\n"
        text += "Бот больше не сможет использовать BotHub для детекции спама.\n"
        text += "Используйте главное меню для настройки нового токена."

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer("Токен удален", show_alert=True)

    async def _show_prompt_menu(self, callback_query: types.CallbackQuery, user: User):
        """Показать меню управления промптом"""
        keyboard = self._create_prompt_menu_keyboard(bool(user.system_prompt))

        text = "🤖 <b>Управление системным промптом</b>\n\n"

        if user.system_prompt:
            text += f"✅ Настроен пользовательский промпт\n"
            text += f"📏 Длина: {len(user.system_prompt)} символов\n\n"
        else:
            text += f"📄 Используется промпт по умолчанию\n"
            text += f"📏 Длина: {len(self.default_user_instructions)} символов\n\n"

        text += "Промпт определяет поведение ИИ при анализе сообщений на спам.\n\n"
        text += "Выберите действие:"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _show_current_prompt(self, callback_query: types.CallbackQuery, user: User):
        """Показать текущий промпт"""
        current_instructions = user.system_prompt or self.default_user_instructions
        prompt_type = "Пользовательский" if user.system_prompt else "По умолчанию"

        display_instructions = current_instructions
        if len(display_instructions) > 3000:
            display_instructions = display_instructions[:3000] + "...\n\n[Текст обрезан для отображения]"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="◀️ Назад к промпту",
                callback_data=BotHubCallback(action="prompt_menu").pack()
            )
        ]])

        text = f"👁️ <b>Текущий системный промпт</b>\n\n"
        text += f"📋 Тип: {prompt_type}\n"
        text += f"📏 Длина: {len(current_instructions)} символов\n\n"
        text += f"<code>{display_instructions}</code>"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _start_prompt_input(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Запустить ввод промпта"""
        await state.set_state(BotHubSettingsStates.waiting_for_prompt)

        text = "✏️ <b>Редактирование системного промпта</b>\n\n"
        text += "Отправьте новый системный промпт для детекции спама.\n\n"
        text += "📋 <b>Требования:</b>\n"
        text += "• Минимум 50 символов\n"
        text += "• Максимум 4000 символов\n"
        text += "• Должен содержать четкие инструкции для ИИ\n\n"
        text += "⚠️ Промпт будет использоваться для всех запросов к BotHub"

        await callback_query.message.edit_text(text, parse_mode="HTML")
        await callback_query.answer()

    async def _reset_prompt(self, callback_query: types.CallbackQuery, user: User, user_repository):
        """Сбросить промпт к умолчанию"""
        user.system_prompt = None
        await user_repository.update_user(user)

        deps = getattr(callback_query.message, 'deps', None)
        self._clear_bothub_cache_for_user(user.telegram_id, deps, "prompt reset")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="◀️ Назад к промпту",
                callback_data=BotHubCallback(action="prompt_menu").pack()
            )
        ]])

        text = f"✅ <b>Системный промпт сброшен</b>\n\n"
        text += f"Теперь используется промпт по умолчанию.\n"
        text += f"Длина: {len(self.default_user_instructions)} символов"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer("Промпт сброшен", show_alert=True)

    async def _show_model_menu(self, callback_query: types.CallbackQuery, user: User):
        """Показать меню управления моделью"""
        keyboard = self._create_model_menu_keyboard()

        current_model = user.bothub_model or "gpt-5-nano"
        model_status = "✅ Настроена" if user.bothub_model else "📄 По умолчанию"

        text = "🎯 <b>Управление моделью BotHub</b>\n\n"
        text += f"📋 Текущая модель: <code>{current_model}</code>\n"
        text += f"📊 Статус: {model_status}\n\n"
        text += "Модель определяет качество и скорость анализа спама.\n\n"
        text += "Выберите действие:"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _show_models_list(self, callback_query: types.CallbackQuery, user: User):
        """Показать список доступных моделей"""
        if not user.bothub_token:
            await callback_query.answer("❌ Сначала настройте токен", show_alert=True)
            return

        try:
            models = await BotHubGateway.get_available_models(user.bothub_token)

            if not models:
                text = "❌ <b>Не удалось загрузить список моделей</b>\n\n"
                text += "Проверьте токен и попробуйте снова."
            else:
                text = "📋 <b>Доступные модели:</b>\n\n"
                for i, model in enumerate(models[:15]):
                    text += f"{i+1}. <code>{model['id']}</code>\n"
                    text += f"   {model.get('label', 'N/A')}\n\n"

                if len(models) > 15:
                    text += f"<i>...и ещё {len(models) - 15} моделей</i>\n\n"

                text += "💡 Используйте кнопку ниже для ввода названия модели"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Ввести название модели",
                        callback_data=BotHubCallback(action="enter_model").pack()
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="◀️ Назад к модели",
                        callback_data=BotHubCallback(action="model_menu").pack()
                    )
                ]
            ])

            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback_query.answer()

        except Exception as e:
            await callback_query.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

    async def _start_model_input(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Запустить ввод модели"""
        await state.set_state(BotHubSettingsStates.waiting_for_model)

        text = "✏️ <b>Ввод названия модели</b>\n\n"
        text += "Отправьте название модели (ID или точное название).\n\n"
        text += "📝 Пример: <code>gpt-5-nano</code>\n"
        text += "💡 Используйте список выше для выбора доступной модели"

        await callback_query.message.edit_text(text, parse_mode="HTML")
        await callback_query.answer()

    async def _show_status(self, callback_query: types.CallbackQuery, user: User):
        """Показать статус и статистику"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data=BotHubCallback(action="status").pack()
            ),
            InlineKeyboardButton(
                text="◀️ Назад в меню",
                callback_data=BotHubCallback(action="main_menu").pack()
            )
        ]])

        if not user.bothub_token:
            text = "❌ <b>BotHub не настроен</b>\n\n"
            text += "Для получения статуса необходимо настроить токен."
        else:
            try:
                gateway = BotHubGateway(user.bothub_token, user.system_prompt or self.default_user_instructions, user.bothub_model)
                health = await gateway.health_check()

                status_emoji = "✅" if health.get("status") == "healthy" else "❌"

                text = f"{status_emoji} <b>Статус BotHub</b>\n\n"
                text += f"🔗 API: {health.get('status', 'unknown')}\n"
                text += f"🤖 Модель: {health.get('model', user.bothub_model or 'gpt-5-nano')}\n"
                text += f"⏱️ Время ответа: {health.get('response_time_ms', 0):.0f}ms\n\n"

                text += f"📊 <b>Статистика:</b>\n"
                text += f"• Запросов: {user.bothub_total_requests}\n"

                avg_time = 0
                if user.bothub_total_requests > 0:
                    avg_time = (user.bothub_total_time / user.bothub_total_requests) * 1000

                text += f"• Среднее время: {avg_time:.0f}ms\n"

                if user.bothub_last_request:
                    from datetime import datetime, timezone
                    last_request_local = user.bothub_last_request.strftime("%d.%m.%Y %H:%M")
                    text += f"• Последний запрос: {last_request_local}\n"
                text += "\n"

                prompt_info = "Настроен" if user.system_prompt else "По умолчанию"
                prompt_length = len(user.system_prompt or self.default_user_instructions)
                text += f"🤖 <b>Промпт:</b> {prompt_info} ({prompt_length} символов)"

            except Exception as e:
                text = f"❌ <b>Ошибка проверки статуса</b>\n\n"
                text += f"Ошибка: {str(e)}\n\n"
                text += "Проверьте токен и попробуйте снова."

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _show_help(self, callback_query: types.CallbackQuery):
        """Показать справку"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="◀️ Назад в меню",
                callback_data=BotHubCallback(action="main_menu").pack()
            )
        ]])

        text = "🆘 <b>Справка по BotHub</b>\n\n"

        text += "🔑 <b>Токен:</b>\n"
        text += "• Получите на https://bothub.chat\n"
        text += "• Обеспечивает доступ к API\n"
        text += "• Проверяется автоматически\n\n"

        text += "🤖 <b>Системный промпт:</b>\n"
        text += "• Инструкции для ИИ модели\n"
        text += "• Влияет на качество детекции\n"
        text += "• Можно настроить под свои нужды\n\n"

        text += "🎯 <b>Модель:</b>\n"
        text += "• Определяет качество анализа\n"
        text += "• Различные скорости и точность\n"
        text += "• По умолчанию: gpt-5-nano\n\n"

        text += "📊 <b>Статус:</b>\n"
        text += "• Проверка работоспособности\n"
        text += "• Статистика использования\n"
        text += "• Время отклика API"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _confirm_reset(self, callback_query: types.CallbackQuery):
        """Подтвердить сброс всех настроек"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, сбросить всё",
                    callback_data=BotHubCallback(action="reset_all").pack()
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=BotHubCallback(action="cancel_reset").pack()
                )
            ]
        ])

        text = "⚠️ <b>Подтверждение сброса</b>\n\n"
        text += "Это действие удалит все настройки BotHub:\n\n"
        text += "🔑 • Токен доступа\n"
        text += "🤖 • Пользовательский системный промпт\n"
        text += "🎯 • Настройки модели\n\n"
        text += "❗ Бот перестанет работать без токена!\n\n"
        text += "Продолжить?"

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()

    async def _reset_all_settings(self, callback_query: types.CallbackQuery, user: User, user_repository, deps: dict = None):
        """Сбросить все настройки"""
        user.bothub_token = None
        user.bothub_configured = False
        user.system_prompt = None
        user.bothub_model = None
        await user_repository.update_user(user)

        self._clear_bothub_cache_for_user(user.telegram_id, deps, "settings reset")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🏠 Главное меню",
                callback_data=BotHubCallback(action="main_menu").pack()
            )
        ]])

        text = "✅ <b>Настройки BotHub сброшены</b>\n\n"
        text += "Удалены все настройки:\n"
        text += "• Токен BotHub\n"
        text += "• Пользовательский системный промпт\n"
        text += "• Настройки модели\n\n"
        text += "🔴 Бот перестал работать! Настройте токен для возобновления работы."

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer("Все настройки сброшены", show_alert=True)

    async def _cancel_reset(self, callback_query: types.CallbackQuery, user: User):
        """Отменить сброс"""
        await self._show_main_menu(callback_query, user)
        await callback_query.answer("Сброс отменен")


def register_bothub_settings_handlers(router):
    """Регистрирует обработчики команд BotHub"""

    handler = BotHubSettingsHandler()

    router.message.register(handler.cmd_bothub, Command("bothub"))

    router.message.register(handler.handle_token_input, BotHubSettingsStates.waiting_for_token)
    router.message.register(handler.handle_prompt_input, BotHubSettingsStates.waiting_for_prompt)
    router.message.register(handler.handle_model_input, BotHubSettingsStates.waiting_for_model)

    router.callback_query.register(
        handler.handle_callback_query,
        BotHubCallback.filter()
    )

    logger.info("🤖 BotHub settings handlers registered")
