import time
from aiogram import Router, types, F
from aiogram.filters import Command
from typing import Dict, Any

router = Router()


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

<b>Основные команды (в личном чате):</b>
/start - Запустить бота
/help - Показать это сообщение

<b>Управление (в личном чате с ботом):</b>
/stats <chat_id> [hours] - Статистика чата
/banned <chat_id> - Список забаненных пользователей
/unban <user_id> <chat_id> - Разбанить пользователя

<b>Админ команды (в группах):</b>
/ban - Забанить пользователя (ответ на сообщение)
/approve - Одобрить активного пользователя (белый список)
/spam - Отметить сообщение как спам (для обучения)

<b>Примеры использования:</b>
В группе: ответь на сообщение с /ban или /approve
В личке: /banned -1001234567890
В личке: /unban 123456789 -1001234567890

🔒 Все админские команды требуют прав администратора
    """
    await message.reply(help_text)


@router.message(Command("banned"), F.chat.type == "private")
async def cmd_banned(message: types.Message, **kwargs):
    """Показать список забаненных пользователей (только в приватном чате)"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repo = deps.get("user_repository")

    if not user_repo:
        await message.reply("❌ Сервис недоступен")
        return

    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []

    if not args:
        await message.reply(
            "📋 <b>Просмотр забаненных пользователей</b>\n\n"
            "Использование:\n"
            "/banned <chat_id>\n\n"
            "Пример:\n"
            "/banned -1001234567890\n\n"
            "Показывает всех забаненных пользователей в указанном чате."
        )
        return

    try:
        chat_id = int(args[0])

        # Получаем список забаненных пользователей
        banned_users = await user_repo.get_banned_users(chat_id)

        if not banned_users:
            await message.reply(f"✅ В чате <code>{chat_id}</code> нет забаненных пользователей")
            return

        # Формируем список
        response_lines = [f"📋 <b>Забаненные пользователи в чате</b> <code>{chat_id}</code>:\n"]

        for i, user in enumerate(banned_users[:20], 1):  # Максимум 20 пользователей
            username = user.get("username", "Без имени")
            user_id = user.get("user_id")
            banned_at = user.get("banned_at", "Неизвестно")
            reason = user.get("ban_reason", "Не указано")
            last_message = user.get("last_message", "")

            # Обрезаем длинное сообщение
            if len(last_message) > 50:
                last_message = last_message[:50] + "..."

            response_lines.append(
                f"🚫 <b>{i}. {username}</b>\n"
                f"   ID: <code>{user_id}</code>\n"
                f"   Забанен: {banned_at}\n"
                f"   Причина: {reason}\n"
                f'   Сообщение: "{last_message}"\n'
                f"   👉 /unban {user_id} {chat_id}\n"
            )

        if len(banned_users) > 20:
            response_lines.append(f"\n... и еще {len(banned_users) - 20} пользователей")

        response_text = "\n".join(response_lines)

        await message.reply(response_text)

    except ValueError:
        await message.reply("❌ Неправильный формат chat_id")
    except Exception as e:
        await message.reply(f"❌ Ошибка получения списка: {str(e)}")


@router.message(Command("unban"), F.chat.type == "private")
async def cmd_unban(message: types.Message, **kwargs):
    """Разбанить пользователя (только в приватном чате)"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repo = deps.get("user_repository")

    if not user_repo:
        await message.reply("❌ Сервис недоступен")
        return

    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []

    if len(args) < 2:
        await message.reply(
            "🔓 <b>Разбан пользователя</b>\n\n"
            "Использование:\n"
            "/unban <user_id> <chat_id>\n\n"
            "Пример:\n"
            "/unban 123456789 -1001234567890\n\n"
            "Разбанивает пользователя в указанном чате и добавляет в белый список."
        )
        return

    try:
        user_id = int(args[0])
        chat_id = int(args[1])

        # Получаем информацию о пользователе
        user_info = await user_repo.get_user_info(user_id)
        username = user_info.get("username", f"ID {user_id}") if user_info else f"ID {user_id}"

        # Разбаниваем в Telegram
        try:
            await message.bot.unban_chat_member(
                chat_id=chat_id, user_id=user_id, only_if_banned=True
            )
            telegram_unban = "✅ Разбанен в Telegram"
        except Exception as e:
            telegram_unban = f"⚠️ Ошибка разбана в Telegram: {e}"

        # Удаляем из списка забаненных и добавляем в белый список
        await user_repo.unban_user(user_id, chat_id)
        await user_repo.add_to_approved(user_id)

        response_text = (
            f"🔓 <b>Пользователь {username} разбанен</b>\n\n"
            f"🆔 User ID: <code>{user_id}</code>\n"
            f"💬 Chat ID: <code>{chat_id}</code>\n"
            f"{telegram_unban}\n"
            f"✅ Удален из списка забаненных\n"
            f"🛡️ Добавлен в белый список"
        )

        await message.reply(response_text)

    except ValueError:
        await message.reply("❌ Неправильный формат user_id или chat_id")
    except Exception as e:
        await message.reply(f"❌ Ошибка разбана: {str(e)}")


@router.message(F.new_chat_members)
async def handle_new_members(message: types.Message, **kwargs):
    """Обработчик новых участников группы"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    user_repo = deps.get("user_repository")

    if not user_repo or not message.new_chat_members:
        return

    for new_member in message.new_chat_members:
        try:
            user_id = new_member.id
            username = new_member.full_name

            # Проверяем, не забанен ли пользователь в нашей системе
            is_banned = await user_repo.is_user_banned(user_id, message.chat.id)

            if is_banned:
                print(
                    f"🚫 Забаненный пользователь {username} ({user_id}) попытался зайти в чат {message.chat.id}"
                )

                # Уведомляем админов
                admin_chat_id = deps.get("config", {}).get("admin_chat_id")
                if admin_chat_id:
                    try:
                        notification_text = (
                            f"⚠️ <b>Попытка входа забаненного пользователя</b>\n\n"
                            f"👤 Пользователь: {username}\n"
                            f"🆔 ID: <code>{user_id}</code>\n"
                            f"💬 Чат: <code>{message.chat.id}</code>\n"
                            f"📱 Чат: {message.chat.title or 'Без названия'}\n\n"
                            f"⚡ Автоматически забанен повторно"
                        )

                        await message.bot.send_message(admin_chat_id, notification_text)
                    except Exception as e:
                        print(f"Failed to send admin notification: {e}")

                # Немедленно баним снова
                try:
                    await message.bot.ban_chat_member(
                        chat_id=message.chat.id, user_id=user_id, revoke_messages=True
                    )
                    print(f"✅ Забаненный пользователь {user_id} автоматически перебанен")
                except Exception as e:
                    print(f"❌ Не удалось перебанить пользователя {user_id}: {e}")

            else:
                # Пользователь не забанен - просто логируем
                print(
                    f"👋 Новый участник: {username} ({user_id}) присоединился к чату {message.chat.id}"
                )

                # Можно добавить дополнительные проверки для новых пользователей
                # Например, проверку через CAS или другие антиспам базы

        except Exception as e:
            print(f"Error processing new member {new_member.id}: {e}")


@router.message(F.left_chat_member)
async def handle_left_member(message: types.Message, **kwargs):
    """Обработчик покинувших участников"""
    if not message.left_chat_member:
        return

    left_member = message.left_chat_member
    username = left_member.full_name
    user_id = left_member.id

    print(f"👋 Участник покинул чат: {username} ({user_id}) из чата {message.chat.id}")

    # Можно добавить логику для очистки данных пользователя или статистики


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: types.Message, **kwargs):
    """Основной обработчик сообщений в группах"""
    deps: Dict[str, Any] = kwargs.get("deps", {})

    # Получаем use case для проверки сообщений
    check_message_usecase = deps.get("check_message_usecase")
    ban_user_usecase = deps.get("ban_user_usecase")

    if not check_message_usecase:
        return

    # Создаем доменную сущность Message
    from ....domain.entity.message import Message as DomainMessage

    domain_message = DomainMessage(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        text=message.text or "",
        has_links="http" in (message.text or "").lower(),
        has_mentions="@" in (message.text or ""),
        has_images=bool(message.photo or message.sticker),
        is_forward=bool(message.forward_from or message.forward_from_chat),
        emoji_count=len([c for c in (message.text or "") if ord(c) > 0x1F600]),
    )

    try:
        start_time = time.time()

        # Проверяем сообщение на спам
        detection_result = await check_message_usecase.execute(domain_message)

        processing_time = (time.time() - start_time) * 1000

        # Если обнаружен спам - принимаем меры
        if detection_result.is_spam:
            print(
                f"🚨 Spam detected from user {message.from_user.id}: {detection_result.primary_reason.value}"
            )

            # Удаляем сообщение
            if detection_result.should_delete:
                try:
                    await message.delete()
                except Exception as e:
                    print(f"Failed to delete spam message: {e}")

            # Баним/ограничиваем пользователя
            if detection_result.should_ban or detection_result.should_restrict:
                ban_type = "permanent" if detection_result.should_ban else "restrict"

                ban_result = await ban_user_usecase.execute(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    detection_result=detection_result,
                    ban_type=ban_type,
                )

                if ban_result["banned"]:
                    # Уведомляем админов (опционально)
                    admin_message = (
                        f"🚨 <b>Спам заблокирован</b>\n\n"
                        f"👤 Пользователь: {message.from_user.full_name}\n"
                        f"🆔 ID: {message.from_user.id}\n"
                        f"📝 Причина: {detection_result.primary_reason.value}\n"
                        f"📊 Уверенность: {detection_result.overall_confidence:.2f}\n"
                        f"⚡ Время обработки: {processing_time:.1f}ms\n"
                        f"🗑 Удалено сообщений: {ban_result['messages_deleted']}"
                    )

                    # Отправляем в админ чат (если настроен)
                    admin_chat_id = deps.get("admin_chat_id")
                    if admin_chat_id:
                        try:
                            await message.bot.send_message(admin_chat_id, admin_message)
                        except Exception as e:
                            print(f"Failed to send admin notification: {e}")
        else:
            # Сообщение чистое - логируем для статистики
            print(
                f"✅ Clean message from user {message.from_user.id} (confidence: {detection_result.overall_confidence:.3f}, time: {processing_time:.1f}ms)"
            )

    except Exception as e:
        print(f"Error processing message: {e}")
        # В случае ошибки не блокируем сообщение


def register_handlers(dp):
    """Регистрация обработчиков сообщений"""
    dp.include_router(router)
