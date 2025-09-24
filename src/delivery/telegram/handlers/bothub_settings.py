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

logger = logging.getLogger(__name__)


class BotHubSettingsStates(StatesGroup):
    """Состояния для FSM управления настройками BotHub"""
    waiting_for_token = State()
    waiting_for_prompt = State()


class BotHubSettingsHandler:
    """Обработчик команд управления настройками BotHub"""
    
    def __init__(self):
        self.default_system_prompt = """Ты эксперт по определению спама в сообщениях чатов. Анализируй быстро и точно.

ЗАДАЧА: Определи, является ли сообщение спамом.

СПАМ это:
- Реклама товаров/услуг без разрешения
- Призывы писать в личные сообщения для "заработка"
- Финансовые схемы и "быстрые деньги"
- Массовые рассылки и копипаста
- Навязчивые ссылки на внешние ресурсы
- Предложения инвестиций, криптовалют, форекса

НЕ СПАМ это:
- Обычное общение и вопросы
- Обмен опытом по теме чата
- Мемы, шутки, реакции
- Конструктивная критика
- Информативные ссылки по теме

ФОРМАТ ОТВЕТА (только JSON):
{
  "is_spam": boolean,
  "confidence": float (0.0-1.0),
  "reason": "краткое объяснение на русском"
}

Будь консервативным - при сомнениях классифицируй как НЕ спам."""
    
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
        user: User,
        state: FSMContext,
        user_repository,
        **kwargs
    ) -> None:
        """
        Обработка ввода токена
        
        Args:
            message: Telegram сообщение
            user: Пользователь
            state: FSM контекст
            user_repository: Репозиторий пользователей
        """
        try:
            token = message.text.strip()
            
            if not token:
                await message.reply("❌ Токен не может быть пустым")
                return
            
            # Проверяем токен, создавая временный gateway
            try:
                test_gateway = BotHubGateway(token, self.default_system_prompt)
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
            
            # Если системный промпт не настроен, устанавливаем по умолчанию
            if not user.system_prompt:
                user.system_prompt = self.default_system_prompt
            
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
            
            current_prompt = user.system_prompt or self.default_system_prompt
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Редактировать", callback_data="bothub_edit_prompt")],
                [InlineKeyboardButton(text="🔄 Сбросить к умолчанию", callback_data="bothub_reset_prompt")],
                [InlineKeyboardButton(text="👁️ Показать текущий", callback_data="bothub_show_prompt")]
            ])
            
            await message.reply(
                "🤖 <b>Управление системным промптом</b>\n\n"
                f"Текущий промпт: {'Настроен' if user.system_prompt else 'По умолчанию'}\n"
                f"Длина: {len(current_prompt)} символов\n\n"
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
                gateway = BotHubGateway(user.bothub_token, user.system_prompt or self.default_system_prompt)
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
                    text += f"🤖 Промпт: По умолчанию ({len(self.default_system_prompt)} символов)\n"
                
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


def register_bothub_settings_handlers(router):
    """Регистрирует обработчики команд BotHub"""
    
    handler = BotHubSettingsHandler()
    
    # Регистрируем команды
    router.message.register(handler.cmd_bothub_token, Command("bothub_token"))
    router.message.register(handler.cmd_system_prompt, Command("system_prompt"))
    router.message.register(handler.cmd_bothub_status, Command("bothub_status"))
    router.message.register(handler.cmd_reset_bothub, Command("reset_bothub"))
    router.message.register(handler.cmd_bothub_help, Command("bothub_help"))
    
    logger.info("🤖 BotHub settings handlers registered")
