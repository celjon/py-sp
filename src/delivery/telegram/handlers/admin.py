from aiogram import Router, types, F
from aiogram.filters import Command
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

router = Router()


# DEBUG HANDLER УДАЛЕН - он блокировал выполнение команд
# @router.message(F.chat.type.in_({"group", "supergroup"}))
# async def debug_group_messages(message: types.Message, **kwargs):
#     """Отладочный хендлер - ловит ВСЕ сообщения в группах"""
#     if message.text and message.text.startswith('/'):
#         print(f"[GROUP DEBUG] 🔍 Команда в группе: {message.text} от {message.from_user.id}")
#         print(f"[GROUP DEBUG] 🔍 Chat: {message.chat.id} ({message.chat.title})")
#     # Не блокируем дальнейшую обработку - просто логируем


@router.message(Command("ban"), F.chat.type.in_({"group", "channel"}))
async def cmd_ban(message: types.Message, **kwargs):
    """Команда для принудительного бана пользователя"""
    logger.info(f"[DEBUG] ✅ ADMIN HANDLER ВЫЗВАН! /ban от {message.from_user.id} в {message.chat.type}")
    logger.info(f"[DEBUG] reply_to_message: {message.reply_to_message is not None}")
    print(f"[ADMIN PRINT] Handler вызван! /ban от {message.from_user.id} в {message.chat.type}")
    print(f"[GROUP TEST] 🔥 СООБЩЕНИЕ ИЗ ГРУППЫ ДОШЛО ДО ХЕНДЛЕРА! Chat ID: {message.chat.id}")
    logger.info(f"[ADMIN] ========= ПОЛУЧЕНА КОМАНДА /BAN =========")
    logger.info(f"[ADMIN] Отправитель команды: {message.from_user.id} (@{message.from_user.username})")
    logger.info(f"[ADMIN] Чат: {message.chat.id} ({message.chat.type})")
    logger.info(f"[ADMIN] kwargs: {list(kwargs.keys())}")

    # Проверяем reply_to_message
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

    # Создаем фиктивный результат детекции для принудительного бана
    try:
        from ....domain.entity.detection_result import DetectionResult, DetectionReason

        detection_result = DetectionResult(
            message_id=message.reply_to_message.message_id,
            user_id=target_user_id,  # ИСПРАВЛЕНО: используем target_user_id
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
            user_id=target_user_id,  # ИСПРАВЛЕНО: используем target_user_id
            detection_result=detection_result,
            ban_type="permanent",
            require_user_in_db=False,  # Для админских команд не требуем существования в БД
        )

        logger.info(f"[ADMIN] ban_user_usecase.execute завершен: {ban_result}")
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка при создании detection_result или вызове usecase: {e}")
        await message.reply(f"❌ Ошибка выполнения бана: {e}")
        return

    if ban_result["banned"]:
        # Сохраняем информацию о бане в БД для последующего просмотра
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
                print(f"Failed to save ban info: {e}")

        await message.reply(
            f"✅ Пользователь {message.reply_to_message.from_user.full_name} забанен\n"
            f"🗑 Удалено сообщений: {ban_result['messages_deleted']}\n"
            f"📋 Информация сохранена. Для просмотра забаненных: /banned {message.chat.id}"
        )
    else:
        error = ban_result.get("error", "Неизвестная ошибка")
        await message.reply(f"❌ Не удалось забанить пользователя: {error}")

    # Удаляем команду админа чтобы не засорять чат
    try:
        await message.delete()
    except Exception:
        pass  # Игнорируем ошибки удаления


@router.message(Command("approve"), F.chat.type.in_({"group", "channel"}))
async def cmd_approve(message: types.Message, **kwargs):
    """Команда для одобрения АКТИВНОГО пользователя (добавление в белый список)"""
    if not message.reply_to_message:
        await message.reply("Используйте эту команду в ответ на сообщение пользователя")
        return

    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repo = deps.get("user_repository")

    if not user_repo:
        await message.reply("❌ Ошибка: сервис недоступен")
        return

    try:
        user_id = message.reply_to_message.from_user.id
        username = message.reply_to_message.from_user.full_name

        # Проверяем, не забанен ли пользователь
        is_banned = await user_repo.is_user_banned(user_id, message.chat.id)

        if is_banned:
            await message.reply(
                f"⚠️ Пользователь {username} сейчас забанен.\n"
                f"Для разбана используйте команду в личном чате с ботом:\n"
                f"/unban {user_id} {message.chat.id}"
            )

            # Удаляем команду
            try:
                await message.delete()
            except Exception:
                pass
            return

        # Добавляем в белый список (только для НЕ забаненных)
        await user_repo.add_to_approved(user_id)

        response_text = (
            f"✅ Пользователь {username} добавлен в белый список\n"
            f"🛡️ Его сообщения больше не будут проверяться на спам\n"
            f"ℹ️ Для разбана забаненных используйте /unban в личном чате с ботом"
        )

        await message.reply(response_text)

        # Удаляем команду админа
        try:
            await message.delete()
        except Exception:
            pass

    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")

        # Удаляем команду даже при ошибке
        try:
            await message.delete()
        except Exception:
            pass


@router.message(Command("spam"), F.chat.type.in_({"group", "channel"}))
async def cmd_mark_spam(message: types.Message, **kwargs):
    """Команда для добавления сообщения в образцы спама"""
    if not message.reply_to_message or not message.reply_to_message.text:
        await message.reply("Используйте эту команду в ответ на текстовое сообщение")
        return

    deps: Dict[str, Any] = kwargs.get("deps", {})
    spam_samples_repo = deps.get("spam_samples_repository")

    if not spam_samples_repo:
        await message.reply("❌ Ошибка: сервис недоступен")
        return

    try:
        # Сохраняем как образец спама
        from ....domain.entity.spam_sample import SpamSample, SampleType, SampleSource

        sample = SpamSample(
            text=message.reply_to_message.text,
            type=SampleType.SPAM,
            source=SampleSource.ADMIN_REPORT,
            chat_id=message.chat.id,
            user_id=message.reply_to_message.from_user.id,
        )

        await spam_samples_repo.save_sample(sample)

        await message.reply("✅ Сообщение добавлено в базу спам-образцов для обучения")

        # Удаляем команду админа и исходное сообщение-спам
        try:
            await message.delete()  # Удаляем команду /spam
            await message.reply_to_message.delete()  # Удаляем само спам-сообщение
        except Exception:
            pass  # Игнорируем ошибки удаления

    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")

        # Удаляем команду даже при ошибке
        try:
            await message.delete()
        except Exception:
            pass


@router.message(Command("spamstats"), F.chat.type == "private")
async def cmd_spamstats(message: types.Message, **kwargs):
    """Показать статистику спама пользователя (только в приватном чате)"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repo = deps.get("user_repository")

    if not user_repo:
        await message.reply("❌ Статистика недоступна")
        return

    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []

    if not args:
        await message.reply(
            "📊 <b>Статистика спама пользователя</b>\n\n"
            "Использование:\n"
            "/spamstats &lt;user_id&gt;\n\n"
            "Пример:\n"
            "/spamstats 123456789\n\n"
            "Показывает количество спам-сообщений пользователя за сегодня.",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(args[0])

        # Получаем информацию о пользователе
        user_info = await user_repo.get_user_info(user_id)
        daily_spam_count = await user_repo.get_daily_spam_count(user_id)

        username = user_info.get("username", f"ID {user_id}") if user_info else f"ID {user_id}"

        stats_text = f"""
📊 <b>Статистика спама пользователя</b>

👤 Пользователь: {username}
🆔 ID: <code>{user_id}</code>

🚨 <b>Спам за сегодня:</b> {daily_spam_count}
⚠️ <b>Лимит:</b> 3 сообщения в день

{"🔴 ПРЕВЫШЕН ЛИМИТ!" if daily_spam_count >= 3 else "🟢 В пределах нормы"}
        """

        await message.reply(stats_text, parse_mode="HTML")

    except ValueError:
        await message.reply("❌ Неправильный формат user_id")
    except Exception as e:
        await message.reply(f"❌ Ошибка получения статистики: {str(e)}")


@router.message(Command("resetspam"), F.chat.type == "private")
async def cmd_reset_spam(message: types.Message, **kwargs):
    """Сбросить счетчик спама пользователя (только в приватном чате)"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repo = deps.get("user_repository")

    if not user_repo:
        await message.reply("❌ Сервис недоступен")
        return

    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []

    if not args:
        await message.reply(
            "🔄 <b>Сброс счетчика спама</b>\n\n"
            "Использование:\n"
            "/resetspam &lt;user_id&gt;\n\n"
            "Пример:\n"
            "/resetspam 123456789\n\n"
            "Сбрасывает счетчик спам-сообщений пользователя за сегодня.",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(args[0])

        # Получаем информацию о пользователе
        user_info = await user_repo.get_user_info(user_id)
        username = user_info.get("username", f"ID {user_id}") if user_info else f"ID {user_id}"

        # Сбрасываем счетчик спама
        await user_repo.reset_daily_spam_count(user_id)

        response_text = (
            f"🔄 <b>Счетчик спама сброшен</b>\n\n"
            f"👤 Пользователь: {username}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"✅ Счетчик спама за сегодня сброшен"
        )

        await message.reply(response_text, parse_mode="HTML")

    except ValueError:
        await message.reply("❌ Неправильный формат user_id")
    except Exception as e:
        await message.reply(f"❌ Ошибка сброса счетчика: {str(e)}")


@router.message(Command("stats"), F.chat.type == "private")
async def cmd_stats(message: types.Message, **kwargs):
    """Показать статистику чата (только в приватном чате)"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    message_repo = deps.get("message_repository")

    if not message_repo:
        await message.reply("❌ Статистика недоступна")
        return

    # Парсим аргументы команды
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

        if hours > 168:  # Максимум неделя
            hours = 168
            await message.reply("⚠️ Максимальный период: 168 часов (неделя)")

        # Получаем статистику за указанный период
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
