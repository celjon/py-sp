from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any
import secrets
import hashlib


class ApiKeyStatus(Enum):
    """Статус API ключа"""
    ACTIVE = "active"
    SUSPENDED = "suspended" 
    REVOKED = "revoked"
    EXPIRED = "expired"


class ApiKeyPlan(Enum):
    """Тарифный план для API ключа"""
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class ApiKey:
    """Доменная сущность API ключа"""
    client_name: str
    contact_email: str
    plan: ApiKeyPlan = ApiKeyPlan.FREE
    status: ApiKeyStatus = ApiKeyStatus.ACTIVE
    
    # Лимиты
    requests_per_minute: int = 60
    requests_per_day: int = 1000
    requests_per_month: int = 10000
    
    # Ключи (хешируются в базе)
    key_prefix: Optional[str] = None  # Первые 8 символов для отображения
    key_hash: Optional[str] = None    # SHA256 хеш полного ключа
    
    # Временные метки
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Системные поля
    id: Optional[int] = None
    is_active: bool = True
    
    # Дополнительные настройки
    allowed_ips: list[str] = field(default_factory=list)
    webhook_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Автоматическая генерация временных меток"""
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()
        
        # Устанавливаем дефолтное время истечения (1 год для FREE)
        if self.expires_at is None:
            if self.plan == ApiKeyPlan.FREE:
                self.expires_at = self.created_at + timedelta(days=365)
            else:
                self.expires_at = self.created_at + timedelta(days=365 * 5)
    
    @classmethod
    def generate_key(cls) -> str:
        """Генерирует новый API ключ"""
        # Формат: antispam_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        random_part = secrets.token_urlsafe(32)
        return f"antispam_{random_part}"
    
    @classmethod
    def hash_key(cls, api_key: str) -> str:
        """Создает хеш API ключа для безопасного хранения"""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    def set_key(self, api_key: str):
        """Устанавливает API ключ с хешированием"""
        self.key_prefix = api_key[:16] + "..."  # antispam_XXXXXXXX...
        self.key_hash = self.hash_key(api_key)
    
    def verify_key(self, provided_key: str) -> bool:
        """Проверяет предоставленный ключ"""
        if not self.key_hash:
            return False
        return self.hash_key(provided_key) == self.key_hash
    
    @property
    def is_expired(self) -> bool:
        """Проверяет, истек ли ключ"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Проверяет, валиден ли ключ"""
        return (
            self.is_active and 
            self.status == ApiKeyStatus.ACTIVE and 
            not self.is_expired
        )
    
    def update_last_used(self):
        """Обновляет время последнего использования"""
        self.last_used_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def suspend(self, reason: str = None):
        """Приостанавливает ключ"""
        self.status = ApiKeyStatus.SUSPENDED
        self.updated_at = datetime.utcnow()
        if reason:
            self.metadata["suspension_reason"] = reason
    
    def revoke(self, reason: str = None):
        """Отзывает ключ"""
        self.status = ApiKeyStatus.REVOKED
        self.is_active = False
        self.updated_at = datetime.utcnow()
        if reason:
            self.metadata["revocation_reason"] = reason
    
    def get_rate_limits(self) -> Dict[str, int]:
        """Возвращает актуальные лимиты для ключа"""
        # Базовые лимиты по планам
        plan_limits = {
            ApiKeyPlan.FREE: {
                "requests_per_minute": 10,
                "requests_per_day": 1000,
                "requests_per_month": 10000
            },
            ApiKeyPlan.BASIC: {
                "requests_per_minute": 60,
                "requests_per_day": 10000,
                "requests_per_month": 100000
            },
            ApiKeyPlan.PRO: {
                "requests_per_minute": 300,
                "requests_per_day": 50000,
                "requests_per_month": 1000000
            },
            ApiKeyPlan.ENTERPRISE: {
                "requests_per_minute": 1000,
                "requests_per_day": -1,  # Unlimited
                "requests_per_month": -1  # Unlimited
            }
        }
        
        # Берем лимиты плана или кастомные
        default_limits = plan_limits.get(self.plan, plan_limits[ApiKeyPlan.FREE])
        
        return {
            "requests_per_minute": self.requests_per_minute or default_limits["requests_per_minute"],
            "requests_per_day": self.requests_per_day or default_limits["requests_per_day"], 
            "requests_per_month": self.requests_per_month or default_limits["requests_per_month"]
        }
    
    def check_ip_allowed(self, client_ip: str) -> bool:
        """Проверяет, разрешен ли IP адрес"""
        if not self.allowed_ips:
            return True  # Если белый список пустой, разрешаем все
        return client_ip in self.allowed_ips
    
    def to_public_dict(self) -> Dict[str, Any]:
        """Возвращает публичное представление ключа (без секретов)"""
        return {
            "id": self.id,
            "client_name": self.client_name,
            "key_prefix": self.key_prefix,
            "plan": self.plan.value,
            "status": self.status.value,
            "rate_limits": self.get_rate_limits(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "allowed_ips": self.allowed_ips,
            "webhook_url": self.webhook_url
        }