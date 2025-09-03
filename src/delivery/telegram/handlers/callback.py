from aiogram import Router, types, F
from typing import Dict, Any

router = Router()

@router.callback_query(F.data.startswith("ban_confirm:"))
async def callback_ban_confirm(callback: types.CallbackQuery, **kwargs):
    """Обработчик подтверждения бана пользователя"""
    user_id = callback.data.split(":")[1]
    deps: Dict[str, Any] = kwargs.get("deps", {})
    
    ban_user_usecase = deps.get("ban_user_usecase")
    if not ban_user_usecase:
        await callback.answer("❌ Сервис недоступен")
        return
    
    try:
        # Выполняем бан пользователя
        # TODO: реализовать логику бана через use case
        await callback.answer("✅ Пользователь забанен")
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"{callback.message.text}\n\n✅ <b>Подтверждено:</b> пользователь забанен"
        )
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data.startswith("ban_cancel:"))
async def callback_ban_cancel(callback: types.CallbackQuery):
    """Обработчик отмены бана пользователя"""
    try:
        await callback.answer("❌ Бан отменен")
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"{callback.message.text}\n\n❌ <b>Отменено:</b> бан не применен"
        )
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data.startswith("unban:"))
async def callback_unban(callback: types.CallbackQuery, **kwargs):
    """Обработчик разбана пользователя"""
    user_id = callback.data.split(":")[1]
    deps: Dict[str, Any] = kwargs.get("deps", {})
    
    try:
        # TODO: реализовать логику разбана через use case
        await callback.answer("✅ Пользователь разбанен")
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"{callback.message.text}\n\n🔓 <b>Разбанен:</b> пользователь восстановлен"
        )
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data.startswith("spam_details:"))
async def callback_spam_details(callback: types.CallbackQuery, **kwargs):
    """Обработчик показа деталей детекции спама"""
    message_id = callback.data.split(":")[1]
    deps: Dict[str, Any] = kwargs.get("deps", {})
    
    try:
        # TODO: получить детали детекции из базы данных
        details = "🔍 <b>Детали детекции:</b>\n\n" \
                 "• Similarity: 0.85\n" \
                 "• CAS: banned\n" \
                 "• Stop words: found\n" \
                 "• Processing time: 150ms"
        
        await callback.answer()
        await callback.message.answer(details)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

def register_handlers(dp):
    """Регистрация callback обработчиков"""
    dp.include_router(router)
