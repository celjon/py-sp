from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class DetectionReason(Enum):
    """Причины детекции спама"""
    SIMILARITY = "similarity"  # Похожесть на известный спам
    CLASSIFIER = "classifier"  # ML классификатор
    CAS_BANNED = "cas_banned"  # Забанен в CAS
    STOP_WORDS = "stop_words"  # Содержит стоп-слова
    TOO_MANY_EMOJI = "too_many_emoji"  # Слишком много эмоджи
    TOO_MANY_LINKS = "too_many_links"  # Слишком много ссылок
    TOO_MANY_MENTIONS = "too_many_mentions"  # Слишком много упоминаний
    LINKS_ONLY = "links_only"  # Только ссылки
    IMAGES_ONLY = "images_only"  # Только изображения
    FORWARD_SPAM = "forward_spam"  # Форвард спама
    MULTI_LANGUAGE = "multi_language"  # Мультиязычность
    OPENAI_DETECTED = "openai_detected"  # Обнаружено OpenAI
    ADMIN_REPORTED = "admin_reported"  # Помечено админом
    DUPLICATE_MESSAGE = "duplicate_message"  # Дублирующееся сообщение
    ABNORMAL_SPACING = "abnormal_spacing"  # Аномальные пробелы
    USERNAME_SYMBOLS = "username_symbols"  # Запрещенные символы в имени
    PLUGIN_DETECTED = "plugin_detected"  # Обнаружено плагином


@dataclass
class DetectorResult:
    """Результат одного детектора"""
    detector_name: str
    is_spam: bool
    confidence: float
    details: str
    processing_time_ms: float = 0.0
    error: Optional[str] = None


@dataclass 
class DetectionResult:
    """Результат полной детекции сообщения"""
    message_id: Optional[int]
    user_id: int
    is_spam: bool
    overall_confidence: float
    primary_reason: DetectionReason
    detector_results: List[DetectorResult] = field(default_factory=list)
    
    # Рекомендуемые действия
    should_delete: bool = False
    should_ban: bool = False
    should_restrict: bool = False
    should_warn: bool = False
    
    # Дополнительная информация
    processing_time_ms: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def spam_detectors(self) -> List[DetectorResult]:
        """Возвращает детекторы, которые обнаружили спам"""
        return [dr for dr in self.detector_results if dr.is_spam]
    
    @property
    def clean_detectors(self) -> List[DetectorResult]:
        """Возвращает детекторы, которые не обнаружили спам"""
        return [dr for dr in self.detector_results if not dr.is_spam]
    
    @property
    def max_confidence(self) -> float:
        """Возвращает максимальную уверенность среди всех детекторов"""
        if not self.detector_results:
            return 0.0
        return max(dr.confidence for dr in self.detector_results)
    
    @property
    def spam_detector_names(self) -> List[str]:
        """Возвращает имена детекторов, обнаруживших спам"""
        return [dr.detector_name for dr in self.spam_detectors]
    
    def add_detector_result(self, result: DetectorResult):
        """Добавляет результат детектора"""
        self.detector_results.append(result)
        
        # Обновляем общую уверенность (взвешенное среднее)
        if result.is_spam and result.confidence > self.overall_confidence:
            self.overall_confidence = result.confidence
    
    def determine_actions(self, spam_threshold: float = 0.6):
        """Определяет рекомендуемые действия на основе результатов"""
        if not self.is_spam:
            return
        
        # Высокая уверенность - бан
        if self.overall_confidence >= 0.9:
            self.should_ban = True
            self.should_delete = True
        # Средняя уверенность - ограничение
        elif self.overall_confidence >= spam_threshold:
            self.should_restrict = True
            self.should_delete = True
        # Низкая уверенность - предупреждение
        else:
            self.should_warn = True
            self.should_delete = True
    
    def to_summary(self) -> str:
        """Возвращает краткое описание результата"""
        if not self.is_spam:
            return f"✅ Clean message (confidence: {self.overall_confidence:.2f})"
        
        action = "🔨 Ban" if self.should_ban else "🔇 Restrict" if self.should_restrict else "⚠️ Warn"
        detectors = ", ".join(self.spam_detector_names)
        
        return (
            f"🚨 Spam detected: {action}\n"
            f"📊 Confidence: {self.overall_confidence:.2f}\n"
            f"🔍 Detectors: {detectors}\n"
            f"⚡ Time: {self.processing_time_ms:.1f}ms"
        )

