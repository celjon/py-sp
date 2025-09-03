from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class UserStatus(Enum):
    """Статус пользователя в системе"""
    ACTIVE = "active"
    BANNED = "banned"
    RESTRICTED = "restricted"
    PENDING = "pending"


@dataclass
class User:
    """Доменная сущность пользователя"""
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: UserStatus = UserStatus.ACTIVE
    
    # Статистика
    message_count: int = 0
    spam_score: float = 0.0
    
    # Временные метки
    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    # Флаги
    is_admin: bool = False
    
    # Системные поля
    id: Optional[int] = None
    
    @property
    def display_name(self) -> str:
        """Возвращает отображаемое имя пользователя"""
        if self.username:
            return f"@{self.username}"
        elif self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        else:
            return f"User {self.telegram_id}"
    
    @property
    def is_new_user(self) -> bool:
        """Проверяет, является ли пользователь новым (мало сообщений)"""
        return self.message_count <= 5
    
    @property
    def is_suspicious(self) -> bool:
        """Проверяет, подозрителен ли пользователь"""
        return (
            self.spam_score > 0.5 or 
            (self.is_new_user and self.spam_score > 0.3)
        )
    
    @property
    def is_banned(self) -> bool:
        """Проверяет, забанен ли пользователь"""
        return self.status == UserStatus.BANNED
    
    @property
    def is_restricted(self) -> bool:
        """Проверяет, ограничен ли пользователь"""
        return self.status == UserStatus.RESTRICTED
    
    def ban(self):
        """Банит пользователя"""
        self.status = UserStatus.BANNED
    
    def restrict(self):
        """Ограничивает пользователя"""
        self.status = UserStatus.RESTRICTED
    
    def activate(self):
        """Активирует пользователя"""
        self.status = UserStatus.ACTIVE
    
    def update_spam_score(self, score: float):
        """Обновляет спам-скор пользователя"""
        # Используем экспоненциальное сглаживание
        alpha = 0.3
        self.spam_score = alpha * score + (1 - alpha) * self.spam_score
    
    def increment_message_count(self):
        """Увеличивает счетчик сообщений"""
        self.message_count += 1
        self.last_message_at = datetime.now()
        
        if self.first_message_at is None:
            self.first_message_at = datetime.now()

