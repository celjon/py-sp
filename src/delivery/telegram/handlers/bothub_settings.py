# src/delivery/telegram/handlers/bothub_settings.py
"""
Telegram обработчики для управления настройками BotHub
"""

import logging
from typing import Dict, Any, Optional
from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from ....domain.entity.user import User
from ....adapter.gateway.bothub_gateway import BotHubGateway
from ....domain.service.prompt_factory import PromptFactory

logger = logging.getLogger(__name__)


class BotHubSettingsStates(StatesGroup):
    """Состояния для FSM управления настройками BotHub"""
    waiting_for_token = State()
    waiting_for_prompt = State()
    waiting_for_model = State()


class BotHubSettingsHandler:
    """Обработчик команд управления настройками BotHub"""
    
    def __init__(self):
        self.default_user_instructions = PromptFactory.get_default_user_instructions()
    
    async def cmd_bothub_token(
        self,
        message: types.Message,
        user: User = None,
        state: FSMContext = None,
        is_group_owner: bool = False,
        **kwargs
    ) -> None:
        """
        Команда /bothub_token - настройка токена BotHub

        Args:
            message: Telegram сообщение
            user: Пользователь
            state: FSM контекст
            is_group_owner: Является ли владельцем группы
        """
        try:
            # Проверяем права: только владельцы групп
            if not user:
                await message.reply("❌ Пользователь не найден в системе.")
                return

            if not is_group_owner:
                await message.reply("❌ Доступ запрещен. Только для владельцев групп.")
                return
            
            # Проверяем, есть ли уже токен
            if user.bothub_token:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Обновить токен", callback_data="bothub_update_token")],
                    [InlineKeyboardButton(text="❌ Удалить токен", callback_data="bothub_delete_token")],
                    [InlineKeyboardButton(text="📊 Статус", callback_data="bothub_status")]
                ])
                
                await message.reply(
                    "🔑 <b>Токен BotHub уже настроен</b>\n\n"
                    "Выберите действие:",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            else:
                await state.set_state(BotHubSettingsStates.waiting_for_token)
                await message.reply(
                    "🔑 <b>Настройка токена BotHub</b>\n\n"
                    "Отправьте ваш токен доступа к BotHub API.\n\n"
                    "Токен можно получить на: https://bothub.chat\n\n"
                    "⚠️ <i>Токен будет сохранен в базе данных</i>",
                    parse_mode="HTML"
                )
            
        except Exception as e:
            logger.error(f"Error in bothub_token command: {e}")
            await message.reply("❌ Ошибка настройки токена")
    
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
            
            # Проверяем токен, создавая временный gateway
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
            
            # Сохраняем токен
            user.bothub_token = token
            user.bothub_configured = True
            
            # Если пользовательские инструкции не настроены, устанавливаем по умолчанию
            if not user.system_prompt:
                user.system_prompt = self.default_user_instructions
            
            await user_repository.update_user(user)
            await state.clear()
            
            await message.reply(
                "✅ <b>Токен BotHub успешно сохранен!</b>\n\n"
                f"🔗 Статус API: {health.get('status', 'unknown')}\n"
                f"🤖 Модель: {health.get('model', 'unknown')}\n"
                f"⏱️ Время ответа: {health.get('response_time_ms', 0):.0f}ms\n\n"
                "Теперь бот может использовать BotHub для детекции спама.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Error handling token input: {e}")
            await message.reply("❌ Ошибка сохранения токена")
            await state.clear()
    
    async def cmd_system_prompt(
        self,
        message: types.Message,
        user: User = None,
        is_group_owner: bool = False,
        **kwargs
    ) -> None:
        """
        Команда /system_prompt - управление системным промптом

        Args:
            message: Telegram сообщение
            user: Пользователь
            is_group_owner: Является ли владельцем группы
        """
        try:
            if not user:
                await message.reply("❌ Пользователь не найден в системе.")
                return

            if not is_group_owner:
                await message.reply("❌ Доступ запрещен. Только для владельцев групп.")
                return

            current_prompt = user.system_prompt or self.default_user_instructions
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Редактировать", callback_data="bothub_edit_prompt")],
                [InlineKeyboardButton(text="🔄 Сбросить к умолчанию", callback_data="bothub_reset_prompt")],
                [InlineKeyboardButton(text="👁️ Показать текущий", callback_data="bothub_show_prompt")]
            ])
            
            user_instructions_length = len(user.system_prompt) if user.system_prompt else len(self.default_user_instructions)

            await message.reply(
                "🤖 <b>Управление системным промптом</b>\n\n"
                f"Текущий промпт: {'Настроен' if user.system_prompt else 'По умолчанию'}\n"
                f"Длина: {user_instructions_length} символов\n\n"
                "Выберите действие:",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error in system_prompt command: {e}")
            await message.reply("❌ Ошибка управления промптом")
    
    async def cmd_bothub_status(
        self,
        message: types.Message,
        user: User = None,
        is_group_owner: bool = False,
        **kwargs
    ) -> None:
        """
        Команда /bothub_status - статус подключения BotHub

        Args:
            message: Telegram сообщение
            user: Пользователь
            is_group_owner: Является ли владельцем группы
        """
        try:
            # Проверяем права: только владельцы групп
            if not user:
                await message.reply("❌ Пользователь не найден в системе.")
                return

            if not is_group_owner:
                await message.reply("❌ Доступ запрещен. Только для владельцев групп.")
                return
            
            if not user.bothub_token:
                await message.reply(
                    "❌ <b>BotHub не настроен</b>\n\n"
                    "Используйте /bothub_token для настройки токена.",
                    parse_mode="HTML"
                )
                return
            
            # Проверяем статус API
            try:
                gateway = BotHubGateway(user.bothub_token, user.system_prompt or self.default_user_instructions, user.bothub_model)
                health = await gateway.health_check()
                stats = gateway.get_stats()

                status_emoji = "✅" if health.get("status") == "healthy" else "❌"

                text = f"{status_emoji} <b>Статус BotHub</b>\n\n"
                text += f"🔗 API: {health.get('status', 'unknown')}\n"
                text += f"🤖 Модель: {health.get('model', 'unknown')}\n"
                text += f"⏱️ Время ответа: {health.get('response_time_ms', 0):.0f}ms\n"
                text += f"📊 Запросов: {stats.get('total_requests', 0)}\n"
                text += f"⏰ Среднее время: {stats.get('avg_processing_time', 0):.0f}ms\n\n"

                if user.system_prompt:
                    text += f"🤖 Промпт: Настроен ({len(user.system_prompt)} символов)\n"
                else:
                    text += f"🤖 Промпт: По умолчанию ({len(self.default_user_instructions)} символов)\n"
                
                await message.reply(text, parse_mode="HTML")
                
            except Exception as e:
                await message.reply(
                    f"❌ <b>Ошибка проверки статуса</b>\n\n"
                    f"Ошибка: {str(e)}",
                    parse_mode="HTML"
                )
            
        except Exception as e:
            logger.error(f"Error in bothub_status command: {e}")
            await message.reply("❌ Ошибка получения статуса")
    
    async def cmd_reset_bothub(
        self,
        message: types.Message,
        user: User = None,
        is_group_owner: bool = False,
        user_repository = None,
        **kwargs
    ) -> None:
        """
        Команда /reset_bothub - сброс настроек BotHub

        Args:
            message: Telegram сообщение
            user: Пользователь
            is_group_owner: Является ли владельцем группы
            user_repository: Репозиторий пользователей
        """
        try:
            if not user:
                await message.reply("❌ Пользователь не найден в системе.")
                return

            if not is_group_owner:
                await message.reply("❌ Доступ запрещен. Только для владельцев групп.")
                return
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, сбросить", callback_data="bothub_confirm_reset")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="bothub_cancel_reset")]
            ])
            
            await message.reply(
                "⚠️ <b>Сброс настроек BotHub</b>\n\n"
                "Это действие удалит:\n"
                "• Токен BotHub\n"
                "• Настроенный системный промпт\n\n"
                "Бот перестанет работать без токена!\n\n"
                "Продолжить?",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error in reset_bothub command: {e}")
            await message.reply("❌ Ошибка сброса настроек")
    
    async def handle_prompt_input(
        self,
        message: types.Message,
        user: User,
        state: FSMContext,
        user_repository,
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
            
            # Сохраняем промпт
            user.system_prompt = prompt
            await user_repository.update_user(user)
            await state.clear()
            
            await message.reply(
                "✅ <b>Системный промпт обновлен!</b>\n\n"
                f"Длина: {len(prompt)} символов\n\n"
                "Новый промпт будет использоваться для детекции спама.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Error handling prompt input: {e}")
            await message.reply("❌ Ошибка сохранения промпта")
            await state.clear()
    
    async def cmd_bothub_model(
        self,
        message: types.Message,
        user: User = None,
        is_group_owner: bool = False,
        **kwargs
    ) -> None:
        if not user:
            await message.reply("❌ Пользователь не найден в системе.")
            return

        if not is_group_owner:
            await message.reply("❌ Доступ запрещен. Только для владельцев групп.")
            return

        if not user.bothub_token:
            await message.reply("❌ Сначала настройте токен BotHub командой /bothub_token")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Показать доступные модели", callback_data="bothub_list_models")],
            [InlineKeyboardButton(text="✏️ Ввести название модели", callback_data="bothub_enter_model")]
        ])

        current_model = user.bothub_model or "gpt-4o-mini (по умолчанию)"

        await message.reply(
            f"🤖 <b>Управление моделью BotHub</b>\n\n"
            f"Текущая модель: <code>{current_model}</code>\n\n"
            f"Выберите действие:",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    async def handle_model_input(
        self,
        message: types.Message,
        user: User,
        state: FSMContext,
        user_repository,
        **kwargs
    ) -> None:
        try:
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
            await state.clear()

            await message.reply(
                f"✅ <b>Модель обновлена!</b>\n\n"
                f"Выбрана модель: <code>{model_found['label']}</code>\n"
                f"Provider: {model_found.get('owned_by', 'unknown')}\n"
                f"Context length: {model_found.get('context_length', 'N/A')}\n\n"
                f"Новая модель будет использоваться для детекции спама.",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error handling model input: {e}")
            await message.reply("❌ Ошибка установки модели")
            await state.clear()

    async def cmd_bothub_help(
        self,
        message: types.Message,
        user: User = None,
        is_group_owner: bool = False,
        **kwargs
    ) -> None:
        """
        Команда /bothub_help - справка по BotHub

        Args:
            message: Telegram сообщение
            user: Пользователь
            is_group_owner: Является ли владельцем группы
        """
        try:
            if not user:
                await message.reply("❌ Пользователь не найден в системе.")
                return

            if not is_group_owner:
                await message.reply("❌ Доступ запрещен. Только для владельцев групп.")
                return

            text = "🤖 <b>Справка по BotHub</b>\n\n"
            text += "🔑 <b>Команды:</b>\n"
            text += "• /bothub_token - Настройка токена\n"
            text += "• /system_prompt - Управление промптом\n"
            text += "• /bothub_model - Выбор модели\n"
            text += "• /bothub_status - Статус подключения\n"
            text += "• /reset_bothub - Сброс настроек\n"
            text += "• /bothub_help - Эта справка\n\n"
            text += "📋 <b>Что такое BotHub:</b>\n"
            text += "BotHub - это API для работы с языковыми моделями.\n"
            text += "Бот использует его для детекции спама.\n\n"
            text += "🔗 <b>Получение токена:</b>\n"
            text += "1. Перейдите на https://bothub.chat\n"
            text += "2. Зарегистрируйтесь или войдите\n"
            text += "3. Получите токен доступа\n"
            text += "4. Используйте /bothub_token для настройки\n\n"
            text += "⚠️ <i>Без токена бот работать не будет!</i>"

            await message.reply(text, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in bothub_help command: {e}")
            await message.reply("❌ Ошибка отображения справки")
    
    async def handle_callback_query(
        self,
        callback_query: types.CallbackQuery,
        user: User = None,
        state: FSMContext = None,
        deps: dict = None,
        **kwargs
    ) -> None:
        """
        Обработка callback запросов для управления BotHub
        
        Args:
            callback_query: Telegram callback query
            user: Пользователь
            state: FSM контекст
            deps: Зависимости
        """
        try:
            if not user or not callback_query.data:
                await callback_query.answer("❌ Ошибка обработки запроса")
                return
            
            user_repository = deps.get("user_repository") if deps else None
            if not user_repository:
                await callback_query.answer("❌ Ошибка: репозиторий недоступен")
                return
            
            data = callback_query.data
            
            if data == "bothub_update_token":
                await state.set_state(BotHubSettingsStates.waiting_for_token)
                await callback_query.message.edit_text(
                    "🔑 <b>Обновление токена BotHub</b>\n\n"
                    "Отправьте новый токен доступа к BotHub API.\n\n"
                    "Токен можно получить на: https://bothub.chat\n\n"
                    "⚠️ <i>Токен будет сохранен в базе данных</i>",
                    parse_mode="HTML"
                )
                await callback_query.answer()
                
            elif data == "bothub_delete_token":
                user.bothub_token = None
                user.bothub_configured = False
                await user_repository.update_user(user)
                
                await callback_query.message.edit_text(
                    "✅ <b>Токен BotHub удален</b>\n\n"
                    "Бот больше не сможет использовать BotHub для детекции спама.\n"
                    "Используйте /bothub_token для настройки нового токена.",
                    parse_mode="HTML"
                )
                await callback_query.answer("Токен удален")
                
            elif data == "bothub_status":
                if not user.bothub_token:
                    await callback_query.message.edit_text(
                        "❌ <b>BotHub не настроен</b>\n\n"
                        "Используйте /bothub_token для настройки токена.",
                        parse_mode="HTML"
                    )
                    await callback_query.answer()
                    return
                
                # Проверяем статус API
                try:
                    gateway = BotHubGateway(user.bothub_token, user.system_prompt or self.default_user_instructions, user.bothub_model)
                    health = await gateway.health_check()
                    stats = gateway.get_stats()

                    status_emoji = "✅" if health.get("status") == "healthy" else "❌"

                    text = f"{status_emoji} <b>Статус BotHub</b>\n\n"
                    text += f"🔗 API: {health.get('status', 'unknown')}\n"
                    text += f"🤖 Модель: {health.get('model', 'unknown')}\n"
                    text += f"⏱️ Время ответа: {health.get('response_time_ms', 0):.0f}ms\n"
                    text += f"📊 Запросов: {stats.get('total_requests', 0)}\n"
                    text += f"⏰ Среднее время: {stats.get('avg_processing_time', 0):.0f}ms\n\n"

                    if user.system_prompt:
                        text += f"🤖 Промпт: Настроен ({len(user.system_prompt)} символов)\n"
                    else:
                        text += f"🤖 Промпт: По умолчанию ({len(self.default_user_instructions)} символов)\n"
                    
                    await callback_query.message.edit_text(text, parse_mode="HTML")
                    
                except Exception as e:
                    await callback_query.message.edit_text(
                        f"❌ <b>Ошибка проверки статуса</b>\n\n"
                        f"Ошибка: {str(e)}",
                        parse_mode="HTML"
                    )
                
                await callback_query.answer()
                
            elif data == "bothub_edit_prompt":
                await state.set_state(BotHubSettingsStates.waiting_for_prompt)
                await callback_query.message.edit_text(
                    "✏️ <b>Редактирование системного промпта</b>\n\n"
                    "Отправьте новый системный промпт для детекции спама.\n\n"
                    "Требования:\n"
                    "• Минимум 50 символов\n"
                    "• Максимум 4000 символов\n"
                    "• Должен содержать инструкции для ИИ\n\n"
                    "⚠️ <i>Промпт будет использоваться для всех запросов к BotHub</i>",
                    parse_mode="HTML"
                )
                await callback_query.answer()
                
            elif data == "bothub_reset_prompt":
                user.system_prompt = None
                await user_repository.update_user(user)
                
                await callback_query.message.edit_text(
                    f"✅ <b>Системный промпт сброшен</b>\n\n"
                    f"Теперь используется промпт по умолчанию.\n"
                    f"Длина: {len(self.default_user_instructions)} символов",
                    parse_mode="HTML"
                )
                await callback_query.answer("Промпт сброшен")
                
            elif data == "bothub_show_prompt":
                current_instructions = user.system_prompt or self.default_user_instructions

                # Обрезаем инструкции если слишком длинные для Telegram
                display_instructions = current_instructions
                if len(display_instructions) > 3000:
                    display_instructions = display_instructions[:3000] + "...\n\n[Инструкции обрезаны для отображения]"

                await callback_query.message.edit_text(
                    f"👁️ <b>Текущие инструкции для детекции</b>\n\n"
                    f"<code>{display_instructions}</code>\n\n"
                    f"Длина: {len(current_instructions)} символов",
                    parse_mode="HTML"
                )
                await callback_query.answer()
                
            elif data == "bothub_confirm_reset":
                user.bothub_token = None
                user.bothub_configured = False
                user.system_prompt = None
                await user_repository.update_user(user)
                
                await callback_query.message.edit_text(
                    "✅ <b>Настройки BotHub сброшены</b>\n\n"
                    "Удалено:\n"
                    "• Токен BotHub\n"
                    "• Настроенный системный промпт\n\n"
                    "Бот перестал работать! Используйте /bothub_token для настройки.",
                    parse_mode="HTML"
                )
                await callback_query.answer("Настройки сброшены")
                
            elif data == "bothub_cancel_reset":
                await callback_query.message.edit_text(
                    "❌ <b>Сброс отменен</b>\n\n"
                    "Настройки BotHub остались без изменений.",
                    parse_mode="HTML"
                )
                await callback_query.answer("Сброс отменен")

            elif data == "bothub_list_models":
                if not user.bothub_token:
                    await callback_query.answer("❌ Токен не настроен")
                    return

                models = await BotHubGateway.get_available_models(user.bothub_token)

                if not models:
                    await callback_query.message.edit_text(
                        "❌ <b>Не удалось загрузить список моделей</b>\n\n"
                        "Проверьте токен и попробуйте снова.",
                        parse_mode="HTML"
                    )
                    await callback_query.answer()
                    return

                text = "📋 <b>Доступные модели:</b>\n\n"
                for model in models[:10]:
                    text += f"• <code>{model['id']}</code> - {model['label']}\n"

                if len(models) > 10:
                    text += f"\n<i>...и ещё {len(models) - 10} моделей</i>\n"

                text += "\n💡 Используйте кнопку ниже для ввода названия модели"

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Ввести название модели", callback_data="bothub_enter_model")]
                ])

                await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
                await callback_query.answer()

            elif data == "bothub_enter_model":
                await state.set_state(BotHubSettingsStates.waiting_for_model)
                await callback_query.message.edit_text(
                    "✏️ <b>Ввод названия модели</b>\n\n"
                    "Отправьте название модели (ID или label).\n\n"
                    "Пример: <code>gpt-4o-mini</code>",
                    parse_mode="HTML"
                )
                await callback_query.answer()

            else:
                await callback_query.answer("❌ Неизвестная команда")
                
        except Exception as e:
            logger.error(f"Error handling callback query: {e}")
            await callback_query.answer("❌ Ошибка обработки запроса")


def register_bothub_settings_handlers(router):
    """Регистрирует обработчики команд BotHub"""

    handler = BotHubSettingsHandler()

    # Регистрируем команды
    router.message.register(handler.cmd_bothub_token, Command("bothub_token"))
    router.message.register(handler.cmd_system_prompt, Command("system_prompt"))
    router.message.register(handler.cmd_bothub_model, Command("bothub_model"))
    router.message.register(handler.cmd_bothub_status, Command("bothub_status"))
    router.message.register(handler.cmd_reset_bothub, Command("reset_bothub"))
    router.message.register(handler.cmd_bothub_help, Command("bothub_help"))

    # Регистрируем FSM обработчики
    router.message.register(handler.handle_token_input, BotHubSettingsStates.waiting_for_token)
    router.message.register(handler.handle_prompt_input, BotHubSettingsStates.waiting_for_prompt)
    router.message.register(handler.handle_model_input, BotHubSettingsStates.waiting_for_model)

    # Регистрируем callback обработчик
    router.callback_query.register(handler.handle_callback_query)

    logger.info("🤖 BotHub settings handlers registered")
