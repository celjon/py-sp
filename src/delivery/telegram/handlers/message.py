import time
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Dict, Any

logger = logging.getLogger(__name__)

router = Router()


class UnbanCallback(CallbackData, prefix="owner_unban"):
    """Callback data для разбана пользователей"""
    user_id: int
    chat_id: int
    add_to_whitelist: bool = False


@router.chat_member()
async def handle_chat_member_update(chat_member: types.ChatMemberUpdated, **kwargs):
    """Обработчик chat_member updates (присоединение по ссылке)"""
    pass


@router.message(F.new_chat_members)
async def handle_new_members_with_cas(message: types.Message, **kwargs):
    """Обработчик новых участников с проверкой CAS"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repo = deps.get("user_repository")
    ensemble_detector = deps.get("ensemble_detector")

    if not message.new_chat_members:
        return

    for new_member in message.new_chat_members:
        try:
            user_id = new_member.id
            username = new_member.full_name

            if ensemble_detector and hasattr(ensemble_detector, 'cas_detector') and ensemble_detector.cas_detector:
                try:
                    from ....domain.entity.message import Message as DomainMessage

                    dummy_message = DomainMessage(
                        user_id=user_id,
                        chat_id=message.chat.id,
                        text="",
                        username=new_member.username,
                        first_name=new_member.first_name,
                        last_name=new_member.last_name
                    )

                    cas_result = await ensemble_detector._check_cas(dummy_message, {"user_id": user_id})

                    if cas_result and cas_result.is_spam:
                        logger.info(f"🚫 CAS: User {user_id} ({username}) banned - found in CAS database")
                        await message.bot.ban_chat_member(
                            chat_id=message.chat.id,
                            user_id=user_id,
                            revoke_messages=True
                        )
                        continue
                except Exception as e:
                    pass

            if user_repo:
                is_banned = await user_repo.is_user_banned(user_id, message.chat.id)
                if is_banned:
                    await message.bot.ban_chat_member(
                        chat_id=message.chat.id, user_id=user_id, revoke_messages=True
                    )
                    continue

                existing_user = await user_repo.get_user(user_id)
                if not existing_user:
                    await user_repo.create_user(
                        telegram_id=user_id,
                        username=new_member.username,
                        first_name=new_member.first_name,
                        last_name=new_member.last_name
                    )

        except Exception as e:
            pass

    try:
        await message.delete()
    except Exception as e:
        pass


@router.message(
    F.chat.type.in_({"group", "supergroup"}) & (
        F.left_chat_member |
        F.new_chat_title |
        F.new_chat_photo |
        F.delete_chat_photo |
        F.group_chat_created |
        F.supergroup_chat_created |
        F.pinned_message |
        F.message_auto_delete_timer_changed |
        F.forum_topic_created |
        F.forum_topic_edited |
        F.forum_topic_closed |
        F.forum_topic_reopened |
        F.video_chat_scheduled |
        F.video_chat_started |
        F.video_chat_ended
    )
)
async def delete_all_service_messages(message: types.Message, **kwargs):
    """Универсальный обработчик для удаления служебных сообщений"""
    try:
        await message.delete()
        service_type = "неизвестное"
        if message.left_chat_member:
            service_type = f"выход пользователя {message.left_chat_member.full_name}"
        elif message.new_chat_title:
            service_type = "изменение названия"
        elif message.pinned_message:
            service_type = "закрепление сообщения"

        pass
    except Exception as e:
        pass


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.reply(
        "👋 Привет! Я антиспам бот.\n\n"
        "Я автоматически отслеживаю сообщения в группе и удаляю спам.\n"
        "Используйте /help для получения списка команд."
    )


@router.message(Command("help"), F.chat.type == "private")
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
🤖 <b>Антиспам бот - команды:</b>

<b>💫 Интерактивное управление (в личном чате):</b>
/manage - 🏠 Управление группами с интерактивным меню:
   • Включение/выключение антиспам защиты
   • Настройка порога спама (0.0 - 1.0)
   • Просмотр статистики группы
   • Просмотр забаненных пользователей с разбаном
   • Управление уведомлениями о банах
   • Настройка системного промпта для ИИ

/bothub - 🤖 Настройки BotHub ИИ (клавиатура)

<b>📊 Основные команды (в личном чате):</b>
/start - Запустить бота
/help - Показать это сообщение

<b>🛡️ Админ команды (в группах):</b>
/ban - Забанить пользователя (ответ на сообщение)

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

<b>📝 Примеры использования:</b>
В группе: ответь на сообщение с /ban
В личке: /manage - интерактивное управление всеми группами
В личке: /bothub - настройка ИИ для детекции

🔒 Все админские команды требуют прав администратора
⚠️ Без токена BotHub бот работать не будет!
    """
    await message.reply(help_text, parse_mode="HTML")







@router.message(F.chat.type.in_({"group", "supergroup", "channel"}) & ~F.text.startswith('/'))
async def handle_group_message(message: types.Message, **kwargs):
    """Основной обработчик сообщений в группах (исключая команды)"""

    logger.info(f"[HANDLER] Processing message from user {message.from_user.id} in chat {message.chat.id}: '{message.text or ''}'")

    deps: Dict[str, Any] = kwargs.get("deps", {})

    check_message_usecase = deps.get("check_message_usecase")
    ban_user_usecase = deps.get("ban_user_usecase")
    chat_repository = deps.get("chat_repository")

    logger.info(f"[HANDLER] Dependencies - check_message_usecase: {bool(check_message_usecase)}, chat_repository: {bool(chat_repository)}")

    if not check_message_usecase:
        logger.warning(f"[HANDLER] Missing check_message_usecase, skipping message processing")
        return

    chat = None
    if chat_repository:
        try:
            chat = await chat_repository.get_chat_by_telegram_id(message.chat.id)
            logger.info(f"[HANDLER] Chat found: {bool(chat)}, monitored: {chat.is_monitored if chat else 'N/A'}")
        except Exception as e:
            logger.warning(f"[HANDLER] Error getting chat: {e}")

    if chat and not chat.is_monitored:
        logger.info(f"[HANDLER] Chat {message.chat.id} is not monitored, skipping")
        return

    from ....domain.entity.message import Message as DomainMessage

    domain_message = DomainMessage(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        text=message.text or "",
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        has_links="http" in (message.text or "").lower(),
        has_mentions="@" in (message.text or ""),
        has_images=bool(message.photo or message.sticker),
        is_forward=bool(message.forward_from or message.forward_from_chat),
        emoji_count=len([c for c in (message.text or "") if ord(c) > 0x1F600]),
        telegram_message_id=message.message_id,
    )

    try:
        start_time = time.time()

        detection_result = await check_message_usecase.execute(domain_message, chat=chat)

        processing_time = (time.time() - start_time) * 1000

        if detection_result.is_spam:
            logger.info(
                f"🚨 Spam detected - User: {message.from_user.id} | Chat: {message.chat.id} | "
                f"Confidence: {detection_result.overall_confidence:.3f} | Detector: {detection_result.primary_reason.value}"
            )

            current_message_deleted = False
            if detection_result.should_delete:
                try:
                    await message.delete()
                    current_message_deleted = True
                except Exception as e:
                    pass

            if detection_result.should_ban or detection_result.should_restrict:
                ban_type = "permanent" if detection_result.should_ban else "restrict"

                ban_result = await ban_user_usecase.execute(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    detection_result=detection_result,
                    ban_type=ban_type,
                )

                if ban_result["banned"]:
                    total_deleted = ban_result['messages_deleted']
                    if current_message_deleted:
                        total_deleted += 1

                    if chat and chat.owner_user_id and chat.ban_notifications_enabled:
                        try:
                            banned_text = (message.text or "")[:200]
                            if len(message.text or "") > 200:
                                banned_text += "..."

                            owner_message = (
                                f"🚨 <b>Пользователь забанен за спам</b>\n\n"
                                f"💬 <b>Группа:</b> {chat.display_name}\n"
                                f"👤 <b>Пользователь:</b> {message.from_user.full_name}\n"
                                f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
                                f"📝 <b>Причина:</b> {detection_result.primary_reason.value}\n"
                                f"📊 <b>Уверенность:</b> {detection_result.overall_confidence:.2f}\n"
                                f"🗑️ <b>Удалено сообщений:</b> {total_deleted}\n\n"
                                f"📄 <b>Забаненное сообщение:</b>\n"
                                f"<code>{banned_text}</code>\n\n"
                                f"⏰ {time.strftime('%H:%M:%S %d.%m.%Y')}"
                            )

                            unban_simple = UnbanCallback(
                                user_id=message.from_user.id,
                                chat_id=message.chat.id,
                                add_to_whitelist=False
                            )
                            unban_whitelist = UnbanCallback(
                                user_id=message.from_user.id,
                                chat_id=message.chat.id,
                                add_to_whitelist=True
                            )

                            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(
                                    text="🔓 Разбанить",
                                    callback_data=unban_simple.pack()
                                )],
                                [InlineKeyboardButton(
                                    text="⭐ Разбанить + Белый список",
                                    callback_data=unban_whitelist.pack()
                                )]
                            ])

                            await message.bot.send_message(
                                chat_id=chat.owner_user_id,
                                text=owner_message,
                                parse_mode="HTML",
                                reply_markup=keyboard
                            )

                        except Exception as e:
                            pass

                    admin_chat_id = deps.get("admin_chat_id")
                    if admin_chat_id:
                        try:
                            admin_message = (
                                f"🚨 <b>Спам заблокирован</b>\n\n"
                                f"👤 Пользователь: {message.from_user.full_name}\n"
                                f"🆔 ID: {message.from_user.id}\n"
                                f"💬 Группа: {chat.display_name if chat else 'Unknown'}\n"
                                f"📝 Причина: {detection_result.primary_reason.value}\n"
                                f"📊 Уверенность: {detection_result.overall_confidence:.2f}\n"
                                f"⚡ Время обработки: {processing_time:.1f}ms\n"
                                f"🗑 Удалено сообщений: {total_deleted}"
                            )
                            await message.bot.send_message(admin_chat_id, admin_message, parse_mode="HTML")
                        except Exception as e:
                            pass
        else:
            pass

    except Exception as e:
        pass


@router.callback_query(UnbanCallback.filter())
async def handle_unban_callback(callback_query: types.CallbackQuery, callback_data: UnbanCallback, **kwargs):
    """Обработчик разбана пользователя через кнопку"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repository = deps.get("user_repository")
    chat_repository = deps.get("chat_repository")

    if not user_repository or not chat_repository:
        await callback_query.answer("❌ Сервис недоступен", show_alert=True)
        return

    try:
        chat = await chat_repository.get_chat_by_telegram_id_and_owner(
            callback_data.chat_id, callback_query.from_user.id
        )
        if not chat:
            await callback_query.answer("❌ Только владелец группы может разбанивать пользователей", show_alert=True)
            return

        user_info = await user_repository.get_user_info(callback_data.user_id)
        username = user_info.get("username", f"ID {callback_data.user_id}") if user_info else f"ID {callback_data.user_id}"

        try:
            await callback_query.bot.unban_chat_member(
                chat_id=callback_data.chat_id,
                user_id=callback_data.user_id
            )
            telegram_unban = "✅ Разбанен в Telegram"
            logger.info(f"[UNBAN] Successfully unbanned user {callback_data.user_id} from chat {callback_data.chat_id}")
        except Exception as e:
            # Игнорируем ошибки если пользователь уже не забанен или не был в чате
            if "user not found" in str(e).lower() or "not restricted" in str(e).lower() or "bad request" in str(e).lower():
                telegram_unban = "✅ Пользователь не был забанен"
                logger.info(f"[UNBAN] User {callback_data.user_id} was not banned in chat {callback_data.chat_id}")
            else:
                telegram_unban = f"⚠️ Ошибка разбана в Telegram: {e}"
                logger.warning(f"[UNBAN] Failed to unban user {callback_data.user_id} from chat {callback_data.chat_id}: {e}")

        try:
            await user_repository.unban_user(callback_data.user_id, callback_data.chat_id)
            logger.info(f"[UNBAN] Successfully unbanned user {callback_data.user_id} from chat {callback_data.chat_id} in database")
        except Exception as e:
            logger.error(f"[UNBAN] Failed to unban user {callback_data.user_id} from chat {callback_data.chat_id} in database: {e}")

        action_text = ""
        if callback_data.add_to_whitelist:
            try:
                await user_repository.add_to_approved(callback_data.user_id, callback_data.chat_id)
                action_text = " и добавлен в белый список"
                logger.info(f"[UNBAN] Successfully added user {callback_data.user_id} to whitelist for chat {callback_data.chat_id}")
            except Exception as e:
                logger.error(f"[UNBAN] Failed to add user {callback_data.user_id} to whitelist for chat {callback_data.chat_id}: {e}")
                action_text = " (ошибка добавления в белый список)"

        updated_text = callback_query.message.text + f"\n\n✅ <b>РАЗБАНЕН</b> владельцем группы{action_text}\n🕐 {time.strftime('%H:%M:%S')}"

        await callback_query.message.edit_text(
            updated_text,
            parse_mode="HTML"
        )

        await callback_query.answer(f"✅ Пользователь {username} разбанен")

    except Exception as e:
        logger.error(f"[UNBAN] General error in unban handler: {e}", exc_info=True)
        await callback_query.answer("❌ Ошибка при разбане", show_alert=True)


def register_handlers(dp):
    """Регистрация обработчиков сообщений"""
    dp.include_router(router)
