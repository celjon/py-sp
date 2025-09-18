from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ChatType(Enum):
    """Тип чата"""

    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


@dataclass
class Chat:
    """Доменная сущность чата"""

    telegram_id: int
    title: Optional[str] = None
    type: ChatType = ChatType.GROUP
    description: Optional[str] = None

    # Настройки антиспама
    is_monitored: bool = True
    spam_threshold: float = 0.6

    # Системные поля
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    @property
    def is_group(self) -> bool:
        """Проверяет, является ли чат группой"""
        return self.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    @property
    def is_private(self) -> bool:
        """Проверяет, является ли чат приватным"""
        return self.type == ChatType.PRIVATE

    @property
    def display_name(self) -> str:
        """Возвращает отображаемое имя чата"""
        if self.title:
            return self.title
        else:
            return f"Chat {self.telegram_id}"

    def enable_monitoring(self):
        """Включает мониторинг чата"""
        self.is_monitored = True

    def disable_monitoring(self):
        """Выключает мониторинг чата"""
        self.is_monitored = False

    def update_spam_threshold(self, threshold: float):
        """Обновляет порог детекции спама"""
        if 0.0 <= threshold <= 1.0:
            self.spam_threshold = threshold
        else:
            raise ValueError("Spam threshold must be between 0.0 and 1.0")
