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
        max_messages: int = 5,
        time_window: int = 5,  # секунд
        mute_duration: int = 30,  # секунд мута
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

        # Хранилище: user_id -> список timestamp'ов сообщений
        self.user_messages: Dict[int, List[float]] = {}

        # Мутированные пользователи: user_id -> timestamp окончания мута
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

        # Только для групп/супергрупп (не для приватных чатов)
        if event.chat.type not in ['group', 'supergroup']:
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else None
        if user_id is None:
            return await handler(event, data)

        current_time = time.time()

        # Очищаем истекшие муты
        self._cleanup_expired_mutes(current_time)

        # Проверяем активный мут
        if self._is_user_muted(user_id, current_time):
            logger.debug(f"[FLOOD] Пользователь {user_id} в муте, сообщение игнорируется")
            # Удаляем сообщение от мутированного пользователя
            try:
                await event.delete()
            except Exception:
                pass
            return  # Не передаем дальше

        # Обновляем историю сообщений пользователя
        self._update_user_messages(user_id, current_time)

        # Проверяем флуд
        if self._check_flood(user_id, current_time):
            await self._handle_flood(event, user_id, current_time, data)
            return  # Не передаем дальше

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

        # Добавляем текущее сообщение
        self.user_messages[user_id].append(current_time)

        # Удаляем старые сообщения (вне окна времени)
        cutoff_time = current_time - self.time_window
        self.user_messages[user_id] = [
            msg_time for msg_time in self.user_messages[user_id]
            if msg_time > cutoff_time
        ]

        # Очищаем память от неактивных пользователей
        if len(self.user_messages) > 1000:
            self._cleanup_old_users(current_time)

    def _cleanup_old_users(self, current_time: float) -> None:
        """Очищает данные неактивных пользователей"""
        cutoff_time = current_time - 3600  # 1 час
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

        # Мутим пользователя
        mute_end_time = current_time + self.mute_duration
        self.muted_users[user_id] = mute_end_time

        # Пытаемся наложить мут через Telegram API
        telegram_gateway = data.get('telegram_gateway')
        if telegram_gateway:
            mute_until = datetime.now() + timedelta(seconds=self.mute_duration)
            success = await telegram_gateway.restrict_user(
                chat_id=message.chat.id,
                user_id=user_id,
                until_date=mute_until
            )

            if success:
                logger.info(f"✅ [FLOOD] Пользователь {user_id} замучен на {self.mute_duration}сек через Telegram API")
            else:
                logger.warning(f"⚠️ [FLOOD] Не удалось замутить {user_id} через API (недостаточно прав)")

        # Удаляем текущее сообщение
        try:
            await message.delete()
            logger.debug(f"🗑️ [FLOOD] Удалено флуд-сообщение от {user_id}")
        except Exception as e:
            logger.warning(f"⚠️ [FLOOD] Не удалось удалить сообщение: {e}")

        # Удаляем последние сообщения пользователя (ретроактивная очистка)
        await self._delete_recent_flood_messages(message, user_id, data)

    async def _delete_recent_flood_messages(self, current_message: Message, user_id: int, data: Dict[str, Any]) -> None:
        """Удаляет последние сообщения флудера"""
        try:
            # Пытаемся удалить несколько последних сообщений
            # (это приблизительно, так как мы не храним message_id)
            chat_id = current_message.chat.id
            current_msg_id = current_message.message_id

            # Пытаемся удалить 3-5 последних сообщений
            deleted_count = 0
            for offset in range(1, 6):  # от -1 до -5 сообщений назад
                try:
                    await current_message.bot.delete_message(
                        chat_id=chat_id,
                        message_id=current_msg_id - offset
                    )
                    deleted_count += 1
                except Exception:
                    break  # Если не можем удалить, останавливаемся

            if deleted_count > 0:
                logger.info(f"🧹 [FLOOD] Удалено {deleted_count} последних сообщений от флудера {user_id}")

        except Exception as e:
            logger.debug(f"[FLOOD] Ретроактивная очистка не удалась: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику flood control"""
        current_time = time.time()
        active_users = len([
            user_id for user_id, messages in self.user_messages.items()
            if messages and max(messages) > current_time - 60  # активны за последнюю минуту
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