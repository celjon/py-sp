from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class MessageRole(Enum):
    """Роль сообщения в чате"""

    USER = "user"
    ADMIN = "admin"
    BOT = "bot"
    SYSTEM = "system"


@dataclass
class Message:
    """Доменная сущность сообщения"""

    user_id: int
    chat_id: int
    text: str
    role: MessageRole = MessageRole.USER
    
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    has_links: bool = False
    has_mentions: bool = False
    has_images: bool = False
    is_forward: bool = False
    emoji_count: int = 0

    is_spam: Optional[bool] = None
    spam_confidence: Optional[float] = None

    id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Автоматически заполняем метаданные на основе текста"""
        if self.text:
            self.has_links = self.has_links or (
                "http://" in self.text.lower() or "https://" in self.text.lower()
            )

            self.has_mentions = self.has_mentions or "@" in self.text

            self.emoji_count = self.emoji_count or len([c for c in self.text if ord(c) > 0x1F600])

    @property
    def is_clean(self) -> bool:
        """Возвращает True если сообщение не спам"""
        return self.is_spam is False

    @property
    def links_count(self) -> int:
        """Подсчитывает количество ссылок в сообщении"""
        return self.text.lower().count("http://") + self.text.lower().count("https://")

    @property
    def mentions_count(self) -> int:
        """Подсчитывает количество упоминаний в сообщении"""
        return self.text.count("@")

    def mark_as_spam(self, confidence: float, reason: Optional[str] = None) -> None:
        """Помечает сообщение как спам"""
        self.is_spam = True
        self.spam_confidence = confidence

    def mark_as_clean(self, confidence: float) -> None:
        """Помечает сообщение как не спам"""
        self.is_spam = False
        self.spam_confidence = confidence
