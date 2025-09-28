from aiogram import Router, types, F
from aiogram.filters import Command
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

router = Router()




@router.message(Command("ban"), F.chat.type.in_({"group", "supergroup", "channel"}))
async def cmd_ban(message: types.Message, **kwargs):
    """Команда для принудительного бана пользователя"""
    logger.info(f"[DEBUG] ✅ ADMIN HANDLER ВЫЗВАН! /ban от {message.from_user.id} в {message.chat.type}")
    logger.info(f"[DEBUG] reply_to_message: {message.reply_to_message is not None}")
    logger.info(f"[ADMIN] ========= ПОЛУЧЕНА КОМАНДА /BAN =========")
    logger.info(f"[ADMIN] Отправитель команды: {message.from_user.id} (@{message.from_user.username})")
    logger.info(f"[ADMIN] Чат: {message.chat.id} ({message.chat.type})")
    logger.info(f"[ADMIN] kwargs: {list(kwargs.keys())}")

    try:
        chat_member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if chat_member.status not in ["creator", "administrator"]:
            logger.warning(f"[ADMIN] ❌ Пользователь {message.from_user.id} не имеет прав администратора")
            await message.reply("❌ Эта команда доступна только администраторам группы")
            return
        logger.info(f"[ADMIN] ✅ Пользователь {message.from_user.id} имеет права: {chat_member.status}")
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка проверки прав: {e}")
        await message.reply("❌ Ошибка проверки прав доступа")
        return

    if not message.reply_to_message:
        logger.warning(f"[ADMIN] ❌ Команда /ban без ответа на сообщение")
        await message.reply("Используйте эту команду в ответ на сообщение пользователя")
        return

    target_user_id = message.reply_to_message.from_user.id
    target_username = message.reply_to_message.from_user.username or "без username"
    target_message = message.reply_to_message.text or "медиа сообщение"

    logger.info(f"[ADMIN] Цель бана: {target_user_id} (@{target_username})")
    logger.info(f"[ADMIN] Сообщение цели: '{target_message[:100]}{'...' if len(target_message) > 100 else ''}'")

    deps: Dict[str, Any] = kwargs.get("deps", {})
    logger.info(f"[ADMIN] Доступные deps: {list(deps.keys()) if deps else 'НЕТ DEPS!'}")
    logger.info(f"[ADMIN] kwargs keys: {list(kwargs.keys())}")

    ban_user_usecase = deps.get("ban_user_usecase")

    if not ban_user_usecase:
        logger.error(f"[ADMIN] ❌ ban_user_usecase не найден в deps!")
        logger.error(f"[ADMIN] ❌ deps содержимое: {deps}")
        await message.reply("❌ Ошибка: сервис недоступен")
        return

    logger.info(f"[ADMIN] ban_user_usecase найден: {type(ban_user_usecase)}")

    try:
        from ....domain.entity.detection_result import DetectionResult, DetectionReason

        detection_result = DetectionResult(
            message_id=message.reply_to_message.message_id,
            user_id=target_user_id,
            is_spam=True,
            overall_confidence=1.0,
            primary_reason=DetectionReason.ADMIN_REPORTED,
            detector_results=[],
            should_ban=True,
            should_delete=True,
        )

        logger.info(f"[ADMIN] Вызываем ban_user_usecase.execute для пользователя {target_user_id}")

        ban_result = await ban_user_usecase.execute(
            chat_id=message.chat.id,
            user_id=target_user_id,
            detection_result=detection_result,
            ban_type="permanent",
            require_user_in_db=False,
            aggressive_cleanup=True,
        )

        logger.info(f"[ADMIN] ban_user_usecase.execute завершен: {ban_result}")
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка при создании detection_result или вызове usecase: {e}")
        await message.reply(f"❌ Ошибка выполнения бана: {e}")
        return

    try:
        await message.delete()
    except Exception:
        pass

    if ban_result["banned"]:
        user_repo = deps.get("user_repository")
        if user_repo:
            try:
                await user_repo.save_ban_info(
                    user_id=message.reply_to_message.from_user.id,
                    chat_id=message.chat.id,
                    banned_by_admin_id=message.from_user.id,
                    ban_reason="admin_reported",
                    banned_message=message.reply_to_message.text or "",
                    username=message.reply_to_message.from_user.full_name,
                )
            except Exception as e:
                pass

        chat_repository = deps.get("chat_repository")
        if chat_repository:
            try:
                chat = await chat_repository.get_chat_by_telegram_id(message.chat.id)
                if chat:
                    notification_text = f"""
🚫 <b>Пользователь забанен администратором</b>

👤 <b>Пользователь:</b> {message.reply_to_message.from_user.full_name}
🆔 <b>ID:</b> <code>{target_user_id}</code>
📝 <b>Сообщение:</b> <code>{target_message[:100]}{'...' if len(target_message) > 100 else ''}</code>

👨‍💼 <b>Забанен админом:</b> {message.from_user.full_name} (@{message.from_user.username or 'без username'})
📋 <b>Группа:</b> {message.chat.title or 'Без названия'}
🗑 <b>Удалено сообщений:</b> {ban_result['messages_deleted']}

📋 Список забаненных доступен в /manage
                    """

                    await message.bot.send_message(
                        chat.owner_user_id,
                        notification_text,
                        parse_mode="HTML"
                    )
                    logger.info(f"[ADMIN] Уведомление о бане отправлено владельцу {chat.owner_user_id}")
            except Exception as e:
                logger.error(f"[ADMIN] Ошибка отправки уведомления владельцу: {e}")
    else:
        error = ban_result.get("error", "Неизвестная ошибка")
        try:
            await message.bot.send_message(
                message.from_user.id,
                f"❌ Не удалось забанить пользователя: {error}"
            )
        except Exception:
            pass






@router.message(Command("stats"), F.chat.type == "private")
async def cmd_stats(message: types.Message, **kwargs):
    """Показать статистику чата (только в приватном чате)"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    message_repo = deps.get("message_repository")

    if not message_repo:
        await message.reply("❌ Статистика недоступна")
        return

    args = message.text.split()[1:] if message.text else []

    if not args:
        await message.reply(
            "📊 <b>Команда статистики</b>\n\n"
            "Использование:\n"
            "/stats &lt;chat_id&gt; [hours]\n\n"
            "Примеры:\n"
            "/stats -1001234567890 24\n"
            "/stats -1001234567890\n\n"
            "По умолчанию показывается статистика за 24 часа.",
            parse_mode="HTML"
        )
        return

    try:
        chat_id = int(args[0])
        hours = int(args[1]) if len(args) > 1 else 24

        if hours > 168:
            hours = 168
            await message.reply("⚠️ Максимальный период: 168 часов (неделя)")

        stats = await message_repo.get_chat_stats(chat_id, hours=hours)

        stats_text = f"""
📊 <b>Статистика чата за {hours} часов:</b>
🆔 Chat ID: <code>{chat_id}</code>

📝 Всего сообщений: {stats.get('total_messages', 0)}
🚨 Обнаружено спама: {stats.get('spam_messages', 0)}
👥 Активных пользователей: {stats.get('active_users', 0)}
🔨 Заблокировано пользователей: {stats.get('banned_users', 0)}

📈 Процент спама: {stats.get('spam_percentage', 0):.1f}%
⚡ Среднее время обработки: {stats.get('avg_processing_time', 0):.1f}ms
        """

        await message.reply(stats_text)

    except ValueError:
        await message.reply("❌ Неправильный формат chat_id или hours")
    except Exception as e:
        await message.reply(f"❌ Ошибка получения статистики: {str(e)}")


def register_handlers(dp):
    """Регистрация админских обработчиков"""
    dp.include_router(router)
