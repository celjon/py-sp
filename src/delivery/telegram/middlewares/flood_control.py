import time
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Awaitable, List, Optional
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
import logging

logger = logging.getLogger(__name__)


class FloodControlMiddleware(BaseMiddleware):
    """
    Middleware для защиты от флуда (много сообщений подряд)

    Логика:
    - Отслеживает количество сообщений от каждого пользователя за период времени
    - При превышении лимита накладывает временный мут
    - Удаляет спам-сообщения
    """

    def __init__(
        self,
        max_messages: int = 3,
        time_window: int = 3,
        mute_duration: int = 30,
        enabled: bool = True
    ):
        """
        Args:
            max_messages: Максимум сообщений за time_window
            time_window: Окно времени для подсчета (секунды)
            mute_duration: Длительность мута (секунды)
            enabled: Включен ли flood control
        """
        self.max_messages = max_messages
        self.time_window = time_window
        self.mute_duration = mute_duration
        self.enabled = enabled
        self.user_messages: Dict[int, List[float]] = {}
        self.muted_users: Dict[int, float] = {}

        logger.info(f"🛡️ FloodControl: {max_messages} сообщений/{time_window}сек = мут {mute_duration}сек")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Основной метод middleware"""

        if not self.enabled or not isinstance(event, Message):
            return await handler(event, data)

        if event.chat.type not in ['group', 'supergroup']:
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else None
        if user_id is None:
            return await handler(event, data)

        current_time = time.time()

        self._cleanup_expired_mutes(current_time)

        if self._is_user_muted(user_id, current_time):
            logger.debug(f"[FLOOD] Пользователь {user_id} в муте, сообщение игнорируется")
            try:
                await event.delete()
            except Exception:
                pass
            return

        self._update_user_messages(user_id, current_time)

        if self._check_flood(user_id, current_time):
            await self._handle_flood(event, user_id, current_time, data)
            return

        return await handler(event, data)

    def _cleanup_expired_mutes(self, current_time: float) -> None:
        """Удаляет истекшие муты"""
        expired_users = [
            user_id for user_id, mute_end in self.muted_users.items()
            if current_time >= mute_end
        ]
        for user_id in expired_users:
            del self.muted_users[user_id]

    def _is_user_muted(self, user_id: int, current_time: float) -> bool:
        """Проверяет, в муте ли пользователь"""
        mute_end = self.muted_users.get(user_id)
        return mute_end is not None and current_time < mute_end

    def _update_user_messages(self, user_id: int, current_time: float) -> None:
        """Обновляет историю сообщений пользователя"""
        if user_id not in self.user_messages:
            self.user_messages[user_id] = []

        self.user_messages[user_id].append(current_time)

        cutoff_time = current_time - self.time_window
        self.user_messages[user_id] = [
            msg_time for msg_time in self.user_messages[user_id]
            if msg_time > cutoff_time
        ]

        if len(self.user_messages) > 1000:
            self._cleanup_old_users(current_time)

    def _cleanup_old_users(self, current_time: float) -> None:
        """Очищает данные неактивных пользователей"""
        cutoff_time = current_time - 3600
        users_to_remove = []

        for user_id, messages in self.user_messages.items():
            if not messages or max(messages) < cutoff_time:
                users_to_remove.append(user_id)

        for user_id in users_to_remove:
            del self.user_messages[user_id]

    def _check_flood(self, user_id: int, current_time: float) -> bool:
        """Проверяет, превысил ли пользователь лимит сообщений"""
        messages = self.user_messages.get(user_id, [])
        return len(messages) > self.max_messages

    async def _handle_flood(self, message: Message, user_id: int, current_time: float, data: Dict[str, Any]) -> None:
        """Обрабатывает обнаруженный флуд"""
        logger.warning(f"🚨 [FLOOD] Флуд от пользователя {user_id}: {len(self.user_messages[user_id])} сообщений за {self.time_window}сек")

        mute_end_time = current_time + self.mute_duration
        self.muted_users[user_id] = mute_end_time

        telegram_gateway = data.get('telegram_gateway')
        mute_success = False
        if telegram_gateway:
            mute_until = datetime.now() + timedelta(seconds=self.mute_duration)
            mute_success = await telegram_gateway.restrict_user(
                chat_id=message.chat.id,
                user_id=user_id,
                until_date=mute_until
            )

            if mute_success:
                logger.info(f"✅ [FLOOD] Пользователь {user_id} замучен на {self.mute_duration}сек через Telegram API")
            else:
                logger.warning(f"⚠️ [FLOOD] Не удалось замутить {user_id} через API (недостаточно прав)")

        deleted_count = 0
        try:
            await message.delete()
            deleted_count += 1
            logger.debug(f"🗑️ [FLOOD] Удалено флуд-сообщение от {user_id}")
        except Exception as e:
            logger.warning(f"⚠️ [FLOOD] Не удалось удалить сообщение: {e}")

        additional_deleted = await self._delete_recent_flood_messages(message, user_id, data)
        deleted_count += additional_deleted

        await self._send_flood_notification(message, user_id, deleted_count, mute_success, data)

    async def _delete_recent_flood_messages(self, current_message: Message, user_id: int, data: Dict[str, Any]) -> int:
        """Удаляет последние сообщения флудера, возвращает количество удаленных"""
        try:
            chat_id = current_message.chat.id
            current_msg_id = current_message.message_id

            flood_messages_count = len(self.user_messages.get(user_id, [])) - 1
            messages_to_delete = min(flood_messages_count, self.max_messages)

            deleted_count = 0
            for offset in range(1, messages_to_delete + 1):
                try:
                    await current_message.bot.delete_message(
                        chat_id=chat_id,
                        message_id=current_msg_id - offset
                    )
                    deleted_count += 1
                except Exception:
                    break

            if deleted_count > 0:
                logger.info(f"🧹 [FLOOD] Удалено {deleted_count} последних сообщений от флудера {user_id}")

            return deleted_count

        except Exception as e:
            logger.debug(f"[FLOOD] Ретроактивная очистка не удалась: {e}")
            return 0

    async def _send_flood_notification(self, message: Message, user_id: int, deleted_count: int, mute_success: bool, data: Dict[str, Any]) -> None:
        """Отправляет уведомление владельцу чата о флуде"""
        try:
            chat_repository = data.get('chat_repository')
            if not chat_repository:
                return

            chat = await chat_repository.get_chat_by_telegram_id(message.chat.id)
            if not chat or not chat.owner_user_id or not chat.ban_notifications_enabled:
                return

            user_name = message.from_user.full_name if message.from_user else f"ID {user_id}"
            username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else ""

            mute_status = "✅ Мут наложен" if mute_success else "❌ Мут не удался"

            notification_text = (
                f"🚨 <b>Пользователь замучен за флуд</b>\n\n"
                f"💬 <b>Группа:</b> {chat.display_name}\n"
                f"👤 <b>Пользователь:</b> {user_name} {username}\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"📊 <b>Флуд:</b> {len(self.user_messages[user_id])} сообщений за {self.time_window} сек\n"
                f"🔇 <b>Мут:</b> {mute_status} на {self.mute_duration} сек\n"
                f"🗑️ <b>Удалено сообщений:</b> {deleted_count}\n\n"
                f"⏰ {time.strftime('%H:%M:%S %d.%m.%Y')}"
            )

            await message.bot.send_message(
                chat_id=chat.owner_user_id,
                text=notification_text,
                parse_mode="HTML"
            )

            logger.info(f"📬 [FLOOD] Уведомление о флуде отправлено владельцу {chat.owner_user_id}")

        except Exception as e:
            logger.error(f"❌ [FLOOD] Ошибка отправки уведомления: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику flood control"""
        current_time = time.time()
        active_users = len([
            user_id for user_id, messages in self.user_messages.items()
            if messages and max(messages) > current_time - 60
        ])

        active_mutes = len([
            user_id for user_id, mute_end in self.muted_users.items()
            if current_time < mute_end
        ])

        return {
            "enabled": self.enabled,
            "max_messages": self.max_messages,
            "time_window": self.time_window,
            "mute_duration": self.mute_duration,
            "active_users": active_users,
            "active_mutes": active_mutes,
            "total_tracked_users": len(self.user_messages)
        }