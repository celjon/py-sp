from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class ChatType(Enum):
    """Тип чата"""

    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


@dataclass
class Chat:
    """Доменная сущность чата с поддержкой владения"""

    telegram_id: int
    owner_user_id: int  # ID пользователя-владельца
    title: Optional[str] = None
    type: ChatType = ChatType.GROUP
    description: Optional[str] = None
    username: Optional[str] = None

    # Настройки антиспама
    is_monitored: bool = True
    spam_threshold: float = 0.6
    is_active: bool = True

    # BotHub настройки для группы
    system_prompt: Optional[str] = None

    # Дополнительные настройки
    settings: Dict[str, Any] = None

    # Системные поля
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.settings is None:
            self.settings = {}

    @property
    def is_group(self) -> bool:
        """Проверяет, является ли чат группой или супергруппой"""
        return self.type in (ChatType.GROUP, ChatType.SUPERGROUP)

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

    def is_owned_by(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь владельцем чата"""
        return self.owner_user_id == user_id

    def activate(self):
        """Активирует чат"""
        self.is_active = True

    def deactivate(self):
        """Деактивирует чат"""
        self.is_active = False

    def update_setting(self, key: str, value: Any):
        """Обновляет настройку чата"""
        self.settings[key] = value

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Получает настройку чата"""
        return self.settings.get(key, default)

    def remove_setting(self, key: str):
        """Удаляет настройку чата"""
        self.settings.pop(key, None)
