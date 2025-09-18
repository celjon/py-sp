from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class UsageStats:
    """Статистика использования API"""

    api_key_id: str
    endpoint: str
    timestamp: datetime
    request_count: int = 1
    processing_time_ms: float = 0.0
    is_spam_detected: bool = False
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None

    # Дополнительные метрики
    response_status: int = 200
    error_message: Optional[str] = None
    detection_confidence: Optional[float] = None

    def to_dict(self) -> dict:
        """Преобразует в словарь для записи в БД"""
        return {
            "api_key_id": self.api_key_id,
            "endpoint": self.endpoint,
            "timestamp": self.timestamp,
            "request_count": self.request_count,
            "processing_time_ms": self.processing_time_ms,
            "is_spam_detected": self.is_spam_detected,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "response_status": self.response_status,
            "error_message": self.error_message,
            "detection_confidence": self.detection_confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UsageStats":
        """Создает из словаря БД"""
        return cls(
            api_key_id=data["api_key_id"],
            endpoint=data["endpoint"],
            timestamp=data["timestamp"],
            request_count=data.get("request_count", 1),
            processing_time_ms=data.get("processing_time_ms", 0.0),
            is_spam_detected=data.get("is_spam_detected", False),
            client_ip=data.get("client_ip"),
            user_agent=data.get("user_agent"),
            response_status=data.get("response_status", 200),
            error_message=data.get("error_message"),
            detection_confidence=data.get("detection_confidence"),
        )
