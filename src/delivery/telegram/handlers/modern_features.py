"""
Современные возможности Telegram Bot API для антиспам бота
Интеграция с последними фичами от Telegram
"""

from aiogram import Router, types, F
from aiogram.filters import Command, ChatMemberUpdatedFilter
from typing import Dict, Any, Optional
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)
router = Router()


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=True))
async def handle_chat_member_updated(event: types.ChatMemberUpdated, **kwargs):
    """
    Обработчик изменений статуса участников чата
    Использует современный ChatMemberUpdated API
    """
    deps: Dict[str, Any] = kwargs.get("deps", {})

    try:
        old_member = event.old_chat_member
        new_member = event.new_chat_member

        if old_member.status == "left" and new_member.status == "member":
            await _handle_new_member_join(event, deps)

        elif old_member.status == "member" and new_member.status == "kicked":
            await _handle_member_banned(event, deps)

        elif (old_member.status in ["member", "restricted"] and
              new_member.status == "administrator"):
            await _handle_admin_promotion(event, deps)

    except Exception as e:
        logger.error(f"Chat member update handler error: {e}")


async def _handle_new_member_join(event: types.ChatMemberUpdated, deps: Dict[str, Any]):
    """Обработка нового участника"""
    user = event.new_chat_member.user
    chat = event.chat

    logger.info(f"New member joined: {user.full_name} ({user.id}) to {chat.title}")

    cas_gateway = deps.get("cas_gateway")
    if cas_gateway:
        try:
            is_banned = await cas_gateway.check_user(user.id, {})
            if is_banned.get("is_banned"):
                logger.warning(f"CAS banned user detected: {user.id}")

                await event.bot.ban_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    revoke_messages=True
                )

                admin_chat_id = deps.get("admin_chat_id")
                if admin_chat_id:
                    notification = (
                        f"🚨 <b>CAS Auto-Ban</b>\n\n"
                        f"👤 User: {user.full_name}\n"
                        f"🆔 ID: {user.id}\n"
                        f"💬 Chat: {chat.title}\n"
                        f"🔍 Reason: CAS database match"
                    )
                    await event.bot.send_message(admin_chat_id, notification)

        except Exception as e:
            logger.error(f"CAS check failed for new member: {e}")


async def _handle_member_banned(event: types.ChatMemberUpdated, deps: Dict[str, Any]):
    """Обработка бана участника"""
    user = event.new_chat_member.user
    chat = event.chat

    user_repo = deps.get("user_repository")
    if user_repo:
        try:
            await user_repo.save_ban_info(
                user_id=user.id,
                chat_id=chat.id,
                banned_by_admin_id=event.from_user.id if event.from_user else None,
                ban_reason="admin_action",
                banned_message="",
                username=user.full_name
            )
        except Exception as e:
            logger.error(f"Failed to save ban info: {e}")


async def _handle_admin_promotion(event: types.ChatMemberUpdated, deps: Dict[str, Any]):
    """Обработка выдачи админских прав"""
    user = event.new_chat_member.user
    chat = event.chat

    logger.info(f"User {user.full_name} ({user.id}) promoted to admin in {chat.title}")

    admin_chat_id = deps.get("admin_chat_id")
    if admin_chat_id:
        notification = (
            f"👑 <b>New Administrator</b>\n\n"
            f"👤 User: {user.full_name}\n"
            f"🆔 ID: {user.id}\n"
            f"💬 Chat: {chat.title}\n"
            f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            await event.bot.send_message(admin_chat_id, notification)
        except Exception as e:
            logger.error(f"Failed to send admin promotion notification: {e}")


@router.message(Command("chat_info"))
async def cmd_chat_info(message: types.Message, **kwargs):
    """
    Получение расширенной информации о чате
    Использует современные поля Telegram API
    """
    try:
        chat = await message.bot.get_chat(message.chat.id)

        info_text = f"📊 <b>Информация о чате</b>\n\n"
        info_text += f"📝 Название: {chat.title}\n"
        info_text += f"🆔 ID: <code>{chat.id}</code>\n"
        info_text += f"👥 Тип: {chat.type}\n"

        try:
            member_count = await message.bot.get_chat_member_count(message.chat.id)
            info_text += f"👤 Участников: {member_count}\n"
        except Exception:
            pass

        if hasattr(chat, 'has_aggressive_anti_spam_enabled'):
            antispam_status = "✅ Включена" if chat.has_aggressive_anti_spam_enabled else "❌ Отключена"
            info_text += f"🛡️ Агрессивная антиспам защита: {antispam_status}\n"

        if hasattr(chat, 'has_hidden_members'):
            hidden_status = "✅ Да" if chat.has_hidden_members else "❌ Нет"
            info_text += f"👻 Скрытые участники: {hidden_status}\n"

        if hasattr(chat, 'has_protected_content'):
            protected_status = "✅ Да" if chat.has_protected_content else "❌ Нет"
            info_text += f"🔒 Защищенный контент: {protected_status}\n"

        if chat.description:
            info_text += f"\n📄 Описание:\n{chat.description[:200]}{'...' if len(chat.description) > 200 else ''}\n"

        await message.reply(info_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Chat info error: {e}")
        await message.reply("❌ Ошибка получения информации о чате")


@router.message(Command("user_info"))
async def cmd_user_info(message: types.Message, **kwargs):
    """
    Получение информации о пользователе
    Включает проверки через все доступные системы
    """
    deps: Dict[str, Any] = kwargs.get("deps", {})

    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        args = message.text.split()[1:] if message.text else []
        if args:
            try:
                user_id = int(args[0])
                target_user = types.User(id=user_id, is_bot=False, first_name="Unknown")
            except ValueError:
                await message.reply("❌ Неверный формат ID пользователя")
                return
        else:
            target_user = message.from_user

    if not target_user:
        await message.reply("❌ Пользователь не найден")
        return

    try:
        info_text = f"👤 <b>Информация о пользователе</b>\n\n"
        info_text += f"🆔 ID: <code>{target_user.id}</code>\n"
        info_text += f"📝 Имя: {target_user.full_name}\n"

        if target_user.username:
            info_text += f"🔗 Username: @{target_user.username}\n"

        info_text += f"🤖 Бот: {'Да' if target_user.is_bot else 'Нет'}\n"

        cas_gateway = deps.get("cas_gateway")
        if cas_gateway:
            try:
                cas_result = await cas_gateway.check_user(target_user.id, {})
                cas_status = "🔴 Забанен" if cas_result.get("is_banned") else "🟢 Чист"
                info_text += f"🛡️ CAS: {cas_status}\n"
            except Exception as e:
                info_text += f"🛡️ CAS: ❌ Ошибка проверки\n"

        user_repo = deps.get("user_repository")
        if user_repo:
            try:
                is_banned = await user_repo.is_user_banned(target_user.id, message.chat.id)
                local_status = "🔴 Забанен" if is_banned else "🟢 Активен"
                info_text += f"📋 Локальная БД: {local_status}\n"

                is_approved = await user_repo.is_user_approved(target_user.id, message.chat.id)
                approved_status = "⭐ В белом списке" if is_approved else "➖ Обычный"
                info_text += f"📋 Статус: {approved_status}\n"

            except Exception as e:
                info_text += f"📋 Локальная БД: ❌ Ошибка проверки\n"

        try:
            chat_member = await message.bot.get_chat_member(message.chat.id, target_user.id)
            status_map = {
                "creator": "👑 Создатель",
                "administrator": "🛡️ Администратор",
                "member": "👤 Участник",
                "restricted": "🔒 Ограничен",
                "left": "👋 Покинул",
                "kicked": "🚫 Забанен"
            }
            chat_status = status_map.get(chat_member.status, chat_member.status)
            info_text += f"🏠 Статус в чате: {chat_status}\n"
        except Exception:
            info_text += f"🏠 Статус в чате: ❌ Неизвестен\n"

        await message.reply(info_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"User info error: {e}")
        await message.reply("❌ Ошибка получения информации о пользователе")


@router.message(Command("cas_check"))
async def cmd_cas_check(message: types.Message, **kwargs):
    """
    Проверка пользователя через CAS (Combot Anti-Spam)
    """
    deps: Dict[str, Any] = kwargs.get("deps", {})

    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        args = message.text.split()[1:] if message.text else []
        if args:
            try:
                user_id = int(args[0])
                target_user = types.User(id=user_id, is_bot=False, first_name="Unknown")
            except ValueError:
                await message.reply("❌ Неверный формат ID пользователя")
                return
        else:
            target_user = message.from_user

    if not target_user:
        await message.reply("❌ Пользователь не найден")
        return

    cas_gateway = deps.get("cas_gateway")
    if not cas_gateway:
        await message.reply("❌ CAS gateway не настроен")
        return

    try:
        cas_result = await cas_gateway.check_user(target_user.id, {})

        result_text = f"🛡️ <b>CAS проверка</b>\n\n"
        result_text += f"👤 Пользователь: {target_user.full_name}\n"
        result_text += f"🆔 ID: <code>{target_user.id}</code>\n\n"

        if cas_result.get("is_banned"):
            result_text += f"🔴 <b>Статус: ЗАБАНЕН</b>\n"
            if cas_result.get("reason"):
                result_text += f"📝 Причина: {cas_result['reason']}\n"
        else:
            result_text += f"🟢 <b>Статус: ЧИСТ</b>\n"

        await message.reply(result_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"CAS check error: {e}")
        await message.reply("❌ Ошибка при проверке через CAS")


def register_handlers(dp):
    """Регистрация современных обработчиков"""
    dp.include_router(router)