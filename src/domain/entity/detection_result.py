from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class DetectionReason(Enum):
    """Причины детекции спама - только современная архитектура"""

    # CAS детектор
    CAS_BANNED = "cas_banned"  # Забанен в CAS базе

    # RUSpam BERT детектор
    CLASSIFIER = "classifier"  # RUSpam BERT классификатор
    RUSPAM_DETECTED = "ruspam_detected"  # RUSpam обнаружил спам
    RUSPAM_CLEAN = "ruspam_clean"  # RUSpam определил как чистое

    # BotHub LLM детектор
    BOTHUB_DETECTED = "bothub_detected"  # Обнаружено BotHub
    BOTHUB_CLEAN = "bothub_clean"  # BotHub определил как чистое

    # Административные действия
    ADMIN_REPORTED = "admin_reported"  # Помечено админом


@dataclass
class DetectorResult:
    """Результат одного детектора"""

    detector_name: str
    is_spam: bool
    confidence: float
    details: str
    processing_time_ms: float = 0.0
    error: Optional[str] = None
    token_usage: Optional[Dict[str, int]] = (
        None  # Для BotHub: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    )


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
            # Для предупреждений удаление не обязательно
            self.should_delete = self.overall_confidence > 0.5

    def to_summary(self) -> str:
        """Возвращает краткое описание результата"""
        if not self.is_spam:
            return f"✅ Clean message (confidence: {self.overall_confidence:.2f})"

        action = (
            "🔨 Ban" if self.should_ban else "🔇 Restrict" if self.should_restrict else "⚠️ Warn"
        )
        detectors = ", ".join(self.spam_detector_names)

        return (
            f"🚨 Spam detected: {action}\n"
            f"📊 Confidence: {self.overall_confidence:.2f}\n"
            f"🔍 Detectors: {detectors}\n"
            f"⚡ Time: {self.processing_time_ms:.1f}ms"
        )
