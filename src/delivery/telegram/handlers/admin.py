from aiogram import Router, types, F
from aiogram.filters import Command
from typing import Dict, Any

router = Router()

@router.message(Command("ban"))
async def cmd_ban(message: types.Message, **kwargs):
    """Команда для принудительного бана пользователя"""
    if not message.reply_to_message:
        await message.reply("Используйте эту команду в ответ на сообщение пользователя")
        return
    
    deps: Dict[str, Any] = kwargs.get("deps", {})
    ban_user_usecase = deps.get("ban_user_usecase")
    
    if not ban_user_usecase:
        await message.reply("❌ Ошибка: сервис недоступен")
        return
    
    # Создаем фиктивный результат детекции для принудительного бана
    from ...domain.entity.detection_result import DetectionResult, DetectionReason
    
    detection_result = DetectionResult(
        message_id=message.reply_to_message.message_id,
        user_id=message.reply_to_message.from_user.id,
        is_spam=True,
        overall_confidence=1.0,
        primary_reason=DetectionReason.ADMIN_REPORTED,
        detector_results=[],
        should_ban=True,
        should_delete=True
    )
    
    ban_result = await ban_user_usecase(
        chat_id=message.chat.id,
        user_id=message.reply_to_message.from_user.id,
        detection_result=detection_result,
        ban_type="permanent"
    )
    
    if ban_result["banned"]:
        await message.reply(
            f"✅ Пользователь {message.reply_to_message.from_user.full_name} забанен\n"
            f"🗑 Удалено сообщений: {ban_result['messages_deleted']}"
        )
    else:
        error = ban_result.get("error", "Неизвестная ошибка")
        await message.reply(f"❌ Не удалось забанить пользователя: {error}")

@router.message(Command("approve"))
async def cmd_approve(message: types.Message, **kwargs):
    """Команда для одобрения пользователя"""
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
        await user_repo.add_to_approved(user_id)
        
        await message.reply(
            f"✅ Пользователь {message.reply_to_message.from_user.full_name} добавлен в белый список\n"
            "Теперь его сообщения не будут проверяться на спам"
        )
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")

@router.message(Command("spam"))
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
        from ...domain.entity.spam_sample import SpamSample, SampleType, SampleSource
        
        sample = SpamSample(
            text=message.reply_to_message.text,
            type=SampleType.SPAM,
            source=SampleSource.ADMIN_REPORT,
            chat_id=message.chat.id,
            user_id=message.reply_to_message.from_user.id
        )
        
        await spam_samples_repo.save_sample(sample)
        
        await message.reply("✅ Сообщение добавлено в базу спам-образцов для обучения")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")

@router.message(Command("stats"))
async def cmd_stats(message: types.Message, **kwargs):
    """Показать статистику чата"""
    deps: Dict[str, Any] = kwargs.get("deps", {})
    message_repo = deps.get("message_repository")
    
    if not message_repo:
        await message.reply("❌ Статистика недоступна")
        return
    
    try:
        # Получаем статистику за последние 24 часа
        stats = await message_repo.get_chat_stats(message.chat.id, hours=24)
        
        stats_text = f"""
📊 <b>Статистика чата за 24 часа:</b>

📝 Всего сообщений: {stats.get('total_messages', 0)}
🚨 Обнаружено спама: {stats.get('spam_messages', 0)}
👥 Активных пользователей: {stats.get('active_users', 0)}
🔨 Заблокировано пользователей: {stats.get('banned_users', 0)}

📈 Процент спама: {stats.get('spam_percentage', 0):.1f}%
        """
        
        await message.reply(stats_text)
    except Exception as e:
        await message.reply(f"❌ Ошибка получения статистики: {str(e)}")

def register_handlers(dp):
    """Регистрация админских обработчиков"""
    dp.include_router(router)




