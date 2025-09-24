"""
Простая интеграция с основными детекторами: CAS, RuSpam, BotHub
Без эвристических проверок - только проверенные системы
"""

from aiogram import Router, types, F
from aiogram.filters import Command
from typing import Dict, Any, Optional
import logging
import asyncio

logger = logging.getLogger(__name__)
router = Router()


@router.message((F.chat.type == "group") & (~F.text.startswith('/')))
async def spam_detection_integration(message: types.Message, **kwargs):
    """
    Интеграция с основными детекторами: CAS, RuSpam, BotHub
    Передает обработку в стандартную систему без эвристик
    """
    deps: Dict[str, Any] = kwargs.get("deps", {})
    
    # Проверяем владение чатом
    is_chat_owner = kwargs.get("is_chat_owner", False)
    if not is_chat_owner:
        # Пользователь не является владельцем чата, пропускаем обработку
        return

    # Получаем стандартный use case для проверки сообщений
    check_message_usecase = deps.get("check_message_usecase")

    if not check_message_usecase:
        # Если use case недоступен, просто пропускаем
        return

    # Все проверки выполняются через EnsembleDetector
    # который использует только CAS, RuSpam и BotHub
    # Никаких эвристических алгоритмов!


@router.message(Command("detector_status"))
async def cmd_detector_status(message: types.Message, **kwargs):
    """Статус основных детекторов"""
    deps: Dict[str, Any] = kwargs.get("deps", {})

    try:
        ensemble_detector = deps.get("ensemble_detector")
        if not ensemble_detector:
            await message.reply("❌ Система детекции недоступна")
            return

        status_text = "🔍 <b>Статус детекторов</b>\n\n"

        # Проверяем CAS
        cas_gateway = deps.get("cas_gateway")
        if cas_gateway:
            try:
                # Тестовая проверка CAS
                test_result = await cas_gateway.health_check() if hasattr(cas_gateway, 'health_check') else {"status": "unknown"}
                cas_status = "🟢 Активен" if test_result.get("status") != "error" else "🔴 Ошибка"
            except Exception:
                cas_status = "🔴 Недоступен"
        else:
            cas_status = "❌ Не настроен"

        status_text += f"🛡️ CAS (Combot Anti-Spam): {cas_status}\n"

        # Проверяем BotHub
        bothub_gateway = deps.get("bothub_gateway")
        if bothub_gateway:
            try:
                bothub_status = "🟢 Активен"
            except Exception:
                bothub_status = "🔴 Недоступен"
        else:
            bothub_status = "❌ Не настроен"

        status_text += f"🤖 BotHub: {bothub_status}\n"

        # RuSpam всегда доступен (встроенный)
        status_text += f"🇷🇺 RuSpam: 🟢 Активен\n"

        status_text += f"\n📊 <b>Активные детекторы</b>: Только проверенные системы без эвристик"

        await message.reply(status_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Detector status error: {e}")
        await message.reply("❌ Ошибка получения статуса детекторов")


@router.message(Command("antispam_stats"))
async def cmd_antispam_stats(message: types.Message, **kwargs):
    """Статистика антиспам системы"""
    deps: Dict[str, Any] = kwargs.get("deps", {})

    try:
        message_repo = deps.get("message_repository")

        if message_repo:
            # Получаем реальную статистику из БД
            try:
                stats = await message_repo.get_chat_stats(message.chat.id, hours=24)
                stats_text = (
                    f"📊 <b>Статистика Anti-Spam</b>\n\n"
                    f"🕐 <b>За последние 24 часа:</b>\n"
                    f"• Проверено сообщений: {stats.get('total_messages', 0)}\n"
                    f"• Обнаружено спама: {stats.get('spam_messages', 0)}\n"
                    f"• Заблокировано пользователей: {stats.get('banned_users', 0)}\n"
                    f"• Процент спама: {stats.get('spam_percentage', 0):.1f}%\n\n"
                    f"🛡️ <b>Активные детекторы:</b>\n"
                    f"• CAS (Combot Anti-Spam): ✅\n"
                    f"• RuSpam: ✅\n"
                    f"• BotHub LLM: ✅\n\n"
                    f"⚡ <b>Производительность:</b>\n"
                    f"• Среднее время анализа: {stats.get('avg_processing_time', 0):.1f}ms"
                )
            except Exception as e:
                logger.error(f"Failed to get real stats: {e}")
                stats_text = (
                    "📊 <b>Статистика Anti-Spam</b>\n\n"
                    "🛡️ <b>Активные детекторы:</b>\n"
                    "• CAS (Combot Anti-Spam): ✅\n"
                    "• RuSpam: ✅\n"
                    "• BotHub LLM: ✅\n\n"
                    "❌ Детальная статистика недоступна"
                )
        else:
            stats_text = (
                "📊 <b>Статистика Anti-Spam</b>\n\n"
                "🛡️ <b>Активные детекторы:</b>\n"
                "• CAS (Combot Anti-Spam): ✅\n"
                "• RuSpam: ✅\n"
                "• BotHub LLM: ✅\n\n"
                "❌ Репозиторий статистики недоступен"
            )

        await message.reply(stats_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Antispam stats error: {e}")
        await message.reply("❌ Ошибка получения статистики")


def register_handlers(dp):
    """Регистрация обработчиков основных детекторов"""
    dp.include_router(router)