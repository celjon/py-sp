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

    message_count: int = 0
    spam_score: float = 0.0
    
    daily_spam_count: int = 0
    last_spam_reset_date: Optional[datetime] = None

    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    is_admin: bool = False

    bothub_token: Optional[str] = None
    system_prompt: Optional[str] = None
    bothub_configured: bool = False
    bothub_model: Optional[str] = None

    bothub_total_requests: int = 0
    bothub_total_time: float = 0.0
    bothub_last_request: Optional[datetime] = None

    ban_notifications_enabled: bool = True

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
        return self.spam_score > 0.5 or (self.is_new_user and self.spam_score > 0.3)

    @property
    def is_banned(self) -> bool:
        """Проверяет, забанен ли пользователь"""
        return self.status == UserStatus.BANNED

    @property
    def is_restricted(self) -> bool:
        """Проверяет, ограничен ли пользователь"""
        return self.status == UserStatus.RESTRICTED

    @property
    def is_admin_or_owner(self) -> bool:
        """Проверяет, является ли пользователь админом или владельцем"""
        return self.is_admin

    def ban(self) -> None:
        """Банит пользователя"""
        self.status = UserStatus.BANNED

    def restrict(self) -> None:
        """Ограничивает пользователя"""
        self.status = UserStatus.RESTRICTED

    def activate(self) -> None:
        """Активирует пользователя"""
        self.status = UserStatus.ACTIVE

    def update_spam_score(self, score: float) -> None:
        """Обновляет спам-скор пользователя"""
        alpha = 0.3
        self.spam_score = alpha * score + (1 - alpha) * self.spam_score

    def increment_message_count(self) -> None:
        """Увеличивает счетчик сообщений"""
        self.message_count += 1
        self.last_message_at = datetime.now()

        if self.first_message_at is None:
            self.first_message_at = datetime.now()

    def increment_spam_count(self) -> None:
        """Увеличивает счетчик спама за день"""
        self._check_and_reset_daily_counter()
        self.daily_spam_count += 1

    def reset_daily_spam_count(self) -> None:
        """Сбрасывает счетчик спама за день"""
        self.daily_spam_count = 0
        self.last_spam_reset_date = datetime.now()

    def _check_and_reset_daily_counter(self) -> None:
        """Проверяет и сбрасывает счетчик если прошел день"""
        now = datetime.now()
        if self.last_spam_reset_date is None:
            self.last_spam_reset_date = now
            return
        
        if (now - self.last_spam_reset_date).days >= 1:
            self.reset_daily_spam_count()

    def get_daily_spam_count(self) -> int:
        """Возвращает текущий счетчик спама за день"""
        self._check_and_reset_daily_counter()
        return self.daily_spam_count

    def should_be_banned_for_spam(self, max_daily_spam: int = 3) -> bool:
        """Проверяет, должен ли пользователь быть забанен за спам"""
        return self.get_daily_spam_count() >= max_daily_spam


@dataclass
class UserContext:
    """Контекст пользователя для детекции спама"""

    user_id: int
    is_new_user: bool = False
    is_admin_or_owner: bool = False
    chat_id: Optional[int] = None
    message_count: int = 0
    spam_score: float = 0.0
