import time
from aiogram import Router, types, F
from aiogram.filters import Command
from typing import Dict, Any

router = Router()


@router.chat_member()
async def handle_chat_member_update(chat_member: types.ChatMemberUpdated, **kwargs):
    """Обработчик chat_member updates (присоединение по ссылке)"""
    # Это событие возникает когда пользователь присоединяется по ссылке
    # Просто игнорируем, так как служебное сообщение будет обработано в new_chat_members
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

            # Проверяем через CAS систему
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
                        print(f"🚫 CAS: Пользователь {username} ({user_id}) забанен в CAS базе")
                        await message.bot.ban_chat_member(
                            chat_id=message.chat.id,
                            user_id=user_id,
                            revoke_messages=True
                        )
                        print(f"✅ Пользователь {user_id} автоматически забанен (CAS)")
                        continue
                except Exception as e:
                    print(f"Error checking CAS for new member {user_id}: {e}")

            # Проверяем, не забанен ли пользователь в нашей системе
            if user_repo:
                is_banned = await user_repo.is_user_banned(user_id, message.chat.id)
                if is_banned:
                    await message.bot.ban_chat_member(
                        chat_id=message.chat.id, user_id=user_id, revoke_messages=True
                    )
                    continue

                # Создаем пользователя в БД
                existing_user = await user_repo.get_user(user_id)
                if not existing_user:
                    await user_repo.create_user(
                        telegram_id=user_id,
                        username=new_member.username,
                        first_name=new_member.first_name,
                        last_name=new_member.last_name
                    )

        except Exception as e:
            print(f"Error processing new member {new_member.id}: {e}")

    # Удаляем служебное сообщение
    try:
        await message.delete()
        print(f"🗑️ Удалено служебное сообщение о присоединении")
    except Exception as e:
        print(f"Failed to delete new member message: {e}")


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

        print(f"🗑️ Удалено служебное сообщение: {service_type}")
    except Exception as e:
        print(f"Failed to delete service message: {e}")


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
/stats &lt;chat_id&gt; [hours] - Статистика чата
/banned &lt;chat_id&gt; - Список забаненных пользователей
/unban &lt;user_id&gt; &lt;chat_id&gt; - Разбанить пользователя
/spamstats &lt;user_id&gt; - Статистика спама пользователя
/resetspam &lt;user_id&gt; - Сбросить счетчик спама

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
    await message.reply(help_text, parse_mode="HTML")


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
            "/banned &lt;chat_id&gt;\n\n"
            "Пример:\n"
            "/banned -1001234567890\n\n"
            "Показывает всех забаненных пользователей в указанном чате.",
            parse_mode="HTML"
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
            "/unban &lt;user_id&gt; &lt;chat_id&gt;\n\n"
            "Пример:\n"
            "/unban 123456789 -1001234567890\n\n"
            "Разбанивает пользователя в указанном чате и добавляет в белый список.",
            parse_mode="HTML"
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




@router.message(F.chat.type.in_({"group", "supergroup", "channel"}) & ~F.text.startswith('/'))
async def handle_group_message(message: types.Message, **kwargs):
    """Основной обработчик сообщений в группах (исключая команды)"""

    deps: Dict[str, Any] = kwargs.get("deps", {})

    # Получаем use case для проверки сообщений
    check_message_usecase = deps.get("check_message_usecase")
    ban_user_usecase = deps.get("ban_user_usecase")
    chat_repository = deps.get("chat_repository")

    if not check_message_usecase:
        return

    # Получаем информацию о чате
    chat = None
    if chat_repository:
        try:
            chat = await chat_repository.get_chat_by_telegram_id(message.chat.id)
        except Exception as e:
            print(f"Error getting chat: {e}")

    # Создаем доменную сущность Message
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
    )

    try:
        start_time = time.time()

        # Проверяем сообщение на спам (передаем chat для использования system_prompt группы)
        detection_result = await check_message_usecase.execute(domain_message, chat=chat)

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
