import time
from aiogram import Router, types, F
from aiogram.filters import Command
from typing import Dict, Any

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.reply(
        "👋 Привет! Я антиспам бот.\n\n"
        "Я автоматически отслеживаю сообщения в группе и удаляю спам.\n"
        "Используйте /help для получения списка команд."
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
🤖 <b>Антиспам бот - команды:</b>

<b>Основные команды:</b>
/start - Запустить бота
/help - Показать это сообщение
/stats - Показать статистику

<b>Админ команды:</b>
/ban - Забанить пользователя (ответ на сообщение)
/unban - Разбанить пользователя
/approve - Одобрить пользователя (пропуск проверок)
/spam - Отметить сообщение как спам (для обучения)
/ham - Отметить сообщение как не спам

<b>Статистика:</b>
/mystats - Ваша личная статистика
/chatstats - Статистика чата
    """
    await message.reply(help_text)

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
    from ...domain.entity.message import Message as DomainMessage
    
    domain_message = DomainMessage(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        text=message.text or "",
        has_links="http" in (message.text or "").lower(),
        has_mentions="@" in (message.text or ""),
        has_images=bool(message.photo or message.sticker),
        is_forward=bool(message.forward_from or message.forward_from_chat),
        emoji_count=len([c for c in (message.text or "") if ord(c) > 0x1F600])
    )
    
    try:
        start_time = time.time()
        
        # Проверяем сообщение на спам
        detection_result = await check_message_usecase(domain_message)
        
        processing_time = (time.time() - start_time) * 1000
        
        # Если обнаружен спам - принимаем меры
        if detection_result.is_spam:
            print(f"🚨 Spam detected from user {message.from_user.id}: {detection_result.primary_reason.value}")
            
            # Удаляем сообщение
            if detection_result.should_delete:
                try:
                    await message.delete()
                except Exception as e:
                    print(f"Failed to delete spam message: {e}")
            
            # Баним/ограничиваем пользователя
            if detection_result.should_ban or detection_result.should_restrict:
                ban_type = "permanent" if detection_result.should_ban else "restrict"
                
                ban_result = await ban_user_usecase(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    detection_result=detection_result,
                    ban_type=ban_type
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
            print(f"✅ Clean message from user {message.from_user.id} (confidence: {detection_result.overall_confidence:.3f}, time: {processing_time:.1f}ms)")
            
    except Exception as e:
        print(f"Error processing message: {e}")
        # В случае ошибки не блокируем сообщение

def register_handlers(dp):
    """Регистрация обработчиков сообщений"""
    dp.include_router(router)



