from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Dict, Any, List
import time


class UsagePeriod(Enum):
    """Период для статистики использования"""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


class RequestStatus(Enum):
    """Статус API запроса"""

    SUCCESS = "success"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    INVALID_REQUEST = "invalid_request"


@dataclass
class ApiUsageRecord:
    """Запись об использовании API"""

    api_key_id: int
    endpoint: str
    method: str
    status: RequestStatus

    # Детали запроса
    client_ip: str
    user_agent: Optional[str] = None
    request_size_bytes: int = 0
    response_size_bytes: int = 0
    processing_time_ms: float = 0.0

    # Результат детекции (если применимо)
    is_spam_detected: Optional[bool] = None
    detection_confidence: Optional[float] = None
    detection_reason: Optional[str] = None

    # Временные метки
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Системные поля
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь для JSON сериализации"""
        return {
            "id": self.id,
            "api_key_id": self.api_key_id,
            "endpoint": self.endpoint,
            "method": self.method,
            "status": self.status.value,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "request_size_bytes": self.request_size_bytes,
            "response_size_bytes": self.response_size_bytes,
            "processing_time_ms": self.processing_time_ms,
            "is_spam_detected": self.is_spam_detected,
            "detection_confidence": self.detection_confidence,
            "detection_reason": self.detection_reason,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ApiUsageStats:
    """Агрегированная статистика использования API"""

    api_key_id: int
    period: UsagePeriod
    period_start: datetime

    # Основная статистика
    total_requests: int = 0
    successful_requests: int = 0
    error_requests: int = 0
    rate_limited_requests: int = 0

    # Статистика детекции
    spam_detected: int = 0
    clean_detected: int = 0
    avg_confidence: float = 0.0

    # Производительность
    avg_processing_time_ms: float = 0.0
    max_processing_time_ms: float = 0.0
    total_data_processed_bytes: int = 0

    # Временные метки
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Системные поля
    id: Optional[int] = None

    @property
    def success_rate(self) -> float:
        """Процент успешных запросов"""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def error_rate(self) -> float:
        """Процент ошибочных запросов"""
        if self.total_requests == 0:
            return 0.0
        return (self.error_requests / self.total_requests) * 100

    @property
    def spam_detection_rate(self) -> float:
        """Доля обнаруженного спама (0.0-1.0)"""
        detected_total = self.spam_detected + self.clean_detected
        if detected_total == 0:
            return 0.0
        return self.spam_detected / detected_total

    @property
    def spam_detection_percentage(self) -> float:
        """Процент обнаруженного спама (0-100)"""
        return self.spam_detection_rate * 100

    def update_stats(self, usage_record: ApiUsageRecord):
        """Обновляет статистику новой записью"""
        self.total_requests += 1
        self.updated_at = datetime.now(timezone.utc)

        # Обновляем статистику по статусу
        if usage_record.status == RequestStatus.SUCCESS:
            self.successful_requests += 1
        elif usage_record.status == RequestStatus.ERROR:
            self.error_requests += 1
        elif usage_record.status == RequestStatus.RATE_LIMITED:
            self.rate_limited_requests += 1

        # Обновляем статистику детекции
        if usage_record.is_spam_detected is not None:
            if usage_record.is_spam_detected:
                self.spam_detected += 1
            else:
                self.clean_detected += 1

            # Обновляем среднюю уверенность (простое скользящее среднее)
            if usage_record.detection_confidence is not None:
                total_detections = self.spam_detected + self.clean_detected
                self.avg_confidence = (
                    self.avg_confidence * (total_detections - 1) + usage_record.detection_confidence
                ) / total_detections

        # Обновляем производительность
        if usage_record.processing_time_ms > 0:
            # Обновляем среднее время обработки
            self.avg_processing_time_ms = (
                self.avg_processing_time_ms * (self.total_requests - 1)
                + usage_record.processing_time_ms
            ) / self.total_requests

            # Обновляем максимальное время
            self.max_processing_time_ms = max(
                self.max_processing_time_ms, usage_record.processing_time_ms
            )

        # Обновляем объем данных
        self.total_data_processed_bytes += usage_record.request_size_bytes

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь для JSON сериализации"""
        return {
            "api_key_id": self.api_key_id,
            "period": self.period.value,
            "period_start": self.period_start.isoformat(),
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "error_requests": self.error_requests,
            "rate_limited_requests": self.rate_limited_requests,
            "success_rate": round(self.success_rate, 2),
            "error_rate": round(self.error_rate, 2),
            "spam_detected": self.spam_detected,
            "clean_detected": self.clean_detected,
            "spam_detection_rate": round(self.spam_detection_rate, 2),
            "avg_confidence": round(self.avg_confidence, 3),
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "max_processing_time_ms": round(self.max_processing_time_ms, 2),
            "total_data_processed_mb": round(self.total_data_processed_bytes / 1024 / 1024, 2),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class RateLimitStatus:
    """Статус rate limiting для API ключа"""

    api_key_id: int

    # Текущие счетчики
    requests_this_minute: int = 0
    requests_this_hour: int = 0
    requests_this_day: int = 0
    requests_this_month: int = 0

    # Окна времени
    minute_window_start: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(second=0, microsecond=0)
    )
    hour_window_start: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
    )
    day_window_start: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    )
    month_window_start: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
    )

    # Последний запрос
    last_request_time: Optional[datetime] = None

    def reset_if_needed(self):
        """Сбрасывает счетчики если прошло соответствующее время"""
        now = datetime.now(timezone.utc)

        # Проверяем минутное окно
        current_minute = now.replace(second=0, microsecond=0)
        if current_minute > self.minute_window_start:
            self.requests_this_minute = 0
            self.minute_window_start = current_minute

        # Проверяем часовое окно
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        if current_hour > self.hour_window_start:
            self.requests_this_hour = 0
            self.hour_window_start = current_hour

        # Проверяем дневное окно
        current_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if current_day > self.day_window_start:
            self.requests_this_day = 0
            self.day_window_start = current_day

        # Проверяем месячное окно
        current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if current_month > self.month_window_start:
            self.requests_this_month = 0
            self.month_window_start = current_month

    def increment_counters(self):
        """Увеличивает счетчики запросов"""
        self.reset_if_needed()

        self.requests_this_minute += 1
        self.requests_this_hour += 1
        self.requests_this_day += 1
        self.requests_this_month += 1
        self.last_request_time = datetime.now(timezone.utc)

    def check_limits(self, rate_limits: Dict[str, int]) -> Optional[str]:
        """
        Проверяет лимиты и возвращает None если OK, иначе описание превышения

        Args:
            rate_limits: Словарь с лимитами {"requests_per_minute": 60, ...}

        Returns:
            None если лимиты не превышены, иначе строка с описанием
        """
        self.reset_if_needed()

        # Проверяем минутный лимит
        minute_limit = rate_limits.get("requests_per_minute", -1)
        if minute_limit > 0 and self.requests_this_minute >= minute_limit:
            return f"Rate limit exceeded: {self.requests_this_minute}/{minute_limit} requests per minute"

        # Проверяем дневной лимит
        day_limit = rate_limits.get("requests_per_day", -1)
        if day_limit > 0 and self.requests_this_day >= day_limit:
            return f"Rate limit exceeded: {self.requests_this_day}/{day_limit} requests per day"

        # Проверяем месячный лимит
        month_limit = rate_limits.get("requests_per_month", -1)
        if month_limit > 0 and self.requests_this_month >= month_limit:
            return (
                f"Rate limit exceeded: {self.requests_this_month}/{month_limit} requests per month"
            )

        return None

    def get_remaining_requests(self, rate_limits: Dict[str, int]) -> Dict[str, int]:
        """Возвращает количество оставшихся запросов по каждому лимиту"""
        self.reset_if_needed()

        result = {}

        minute_limit = rate_limits.get("requests_per_minute", -1)
        if minute_limit > 0:
            result["minute"] = max(0, minute_limit - self.requests_this_minute)
        else:
            result["minute"] = -1  # Unlimited

        day_limit = rate_limits.get("requests_per_day", -1)
        if day_limit > 0:
            result["day"] = max(0, day_limit - self.requests_this_day)
        else:
            result["day"] = -1  # Unlimited

        month_limit = rate_limits.get("requests_per_month", -1)
        if month_limit > 0:
            result["month"] = max(0, month_limit - self.requests_this_month)
        else:
            result["month"] = -1  # Unlimited

        return result
