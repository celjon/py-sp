"""
Сущность для хранения образцов спама
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SampleType(Enum):
    """Тип образца"""
    SPAM = "spam"
    HAM = "ham"  # Не спам


class SampleSource(Enum):
    """Источник образца"""
    ADMIN_REPORT = "admin_report"
    AUTO_DETECTION = "auto_detection"
    USER_REPORT = "user_report"
    MANUAL_ADDITION = "manual_addition"


@dataclass
class SpamSample:
    """Образец спама для обучения"""
    text: str
    type: SampleType
    source: SampleSource
    chat_id: Optional[int] = None
    user_id: Optional[int] = None
    
    # Идентификатор (заполняется после сохранения в БД)
    id: Optional[int] = None
    
    # Метаданные
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Дополнительная информация
    language: Optional[str] = None
    confidence: Optional[float] = None
    tags: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Автоматическое определение языка"""
        if not self.language:
            # Простая эвристика для определения языка
            cyrillic_chars = sum(1 for c in self.text if '\u0400' <= c <= '\u04FF')
            if cyrillic_chars > len(self.text) * 0.3:
                self.language = "ru"
            else:
                self.language = "en"
    
    def add_tag(self, tag: str):
        """Добавляет тег к образцу"""
        if tag not in self.tags:
            self.tags.append(tag)
    
    def remove_tag(self, tag: str):
        """Удаляет тег из образца"""
        if tag in self.tags:
            self.tags.remove(tag)
    
    def update(self, **kwargs):
        """Обновляет поля образца"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now()
    
    @property
    def is_spam(self) -> bool:
        """Проверяет, является ли образец спамом"""
        return self.type == SampleType.SPAM
    
    @property
    def is_ham(self) -> bool:
        """Проверяет, является ли образец не спамом"""
        return self.type == SampleType.HAM
    
    def __str__(self) -> str:
        """Строковое представление"""
        return f"SpamSample({self.type.value}, {self.source.value}, '{self.text[:50]}...')"
