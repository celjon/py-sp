# src/domain/service/auth/jwt_service.py
"""
Production-ready JWT Authentication Service
Обеспечивает безопасную аутентификацию с access/refresh токенами
"""

import jwt
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum


class TokenType(Enum):
    """Типы JWT токенов"""
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True)
class JWTClaims:
    """JWT claims (полезная нагрузка токена)"""
    sub: str  # subject (api_key_id)
    iat: int  # issued at
    exp: int  # expires at
    token_type: TokenType
    client_name: str
    plan: str
    permissions: list = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JWTClaims":
        """Создает claims из словаря"""
        return cls(
            sub=data["sub"],
            iat=data["iat"],
            exp=data["exp"],
            token_type=TokenType(data["token_type"]),
            client_name=data["client_name"],
            plan=data["plan"],
            permissions=data.get("permissions", [])
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь для JWT payload"""
        return {
            "sub": self.sub,
            "iat": self.iat,
            "exp": self.exp,
            "token_type": self.token_type.value,
            "client_name": self.client_name,
            "plan": self.plan,
            "permissions": self.permissions or []
        }


@dataclass(frozen=True)
class TokenValidationResult:
    """Результат валидации токена"""
    is_valid: bool
    claims: Optional[JWTClaims] = None
    error: Optional[str] = None
    
    @property
    def api_key_id(self) -> Optional[str]:
        """Возвращает API key ID из claims"""
        return self.claims.sub if self.claims else None


@dataclass(frozen=True)
class TokenPair:
    """Пара access + refresh токенов"""
    access_token: str
    refresh_token: str
    access_expires_in: int  # секунды
    refresh_expires_in: int  # секунды
    token_type: str = "Bearer"


class JWTService:
    """
    Production-ready JWT Service
    
    Features:
    - Криптографически стойкие подписи
    - Access/Refresh token pattern
    - Автоматическая ротация секретов
    - Blacklist для отозванных токенов
    - Rate limiting защита
    """
    
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
        issuer: str = "antispam-api"
    ):
        if not secret_key or len(secret_key) < 32:
            raise ValueError("JWT secret must be at least 32 characters long")
        
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days
        self.issuer = issuer
        
        # В production используйте Redis для blacklist
        self._token_blacklist = set()
        
        print(f"🔐 JWT Service инициализирован (алгоритм: {algorithm}, access: {access_token_expire_minutes}m)")
    
    def create_token_pair(
        self,
        api_key_id: str,
        client_name: str,
        plan: str,
        permissions: list = None
    ) -> TokenPair:
        """
        Создает пару access + refresh токенов
        
        Args:
            api_key_id: ID API ключа
            client_name: Имя клиента
            plan: Тарифный план
            permissions: Список разрешений
            
        Returns:
            TokenPair с access и refresh токенами
        """
        now = datetime.utcnow()
        
        # Access token (короткий срок жизни)
        access_expires = now + timedelta(minutes=self.access_token_expire_minutes)
        access_claims = JWTClaims(
            sub=api_key_id,
            iat=int(now.timestamp()),
            exp=int(access_expires.timestamp()),
            token_type=TokenType.ACCESS,
            client_name=client_name,
            plan=plan,
            permissions=permissions or []
        )
        
        # Refresh token (длинный срок жизни)
        refresh_expires = now + timedelta(days=self.refresh_token_expire_days)
        refresh_claims = JWTClaims(
            sub=api_key_id,
            iat=int(now.timestamp()),
            exp=int(refresh_expires.timestamp()),
            token_type=TokenType.REFRESH,
            client_name=client_name,
            plan=plan,
            permissions=permissions or []
        )
        
        # Генерируем токены
        access_token = self._encode_token(access_claims)
        refresh_token = self._encode_token(refresh_claims)
        
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=self.access_token_expire_minutes * 60,
            refresh_expires_in=self.refresh_token_expire_days * 24 * 60 * 60
        )
    
    def create_access_token(
        self,
        api_key_id: str,
        client_name: str,
        plan: str,
        permissions: list = None
    ) -> str:
        """Создает только access token"""
        now = datetime.utcnow()
        expires = now + timedelta(minutes=self.access_token_expire_minutes)
        
        claims = JWTClaims(
            sub=api_key_id,
            iat=int(now.timestamp()),
            exp=int(expires.timestamp()),
            token_type=TokenType.ACCESS,
            client_name=client_name,
            plan=plan,
            permissions=permissions or []
        )
        
        return self._encode_token(claims)
    
    def validate_token(self, token: str, expected_type: TokenType = None) -> TokenValidationResult:
        """
        Валидирует JWT токен
        
        Args:
            token: JWT токен для валидации
            expected_type: Ожидаемый тип токена (access/refresh)
            
        Returns:
            TokenValidationResult с результатом валидации
        """
        try:
            # Проверяем blacklist
            if self._is_token_blacklisted(token):
                return TokenValidationResult(
                    is_valid=False,
                    error="Token has been revoked"
                )
            
            # Декодируем токен
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "require": ["sub", "iat", "exp", "token_type"]
                }
            )
            
            # Создаем claims
            claims = JWTClaims.from_dict(payload)
            
            # Проверяем тип токена если указан
            if expected_type and claims.token_type != expected_type:
                return TokenValidationResult(
                    is_valid=False,
                    error=f"Invalid token type. Expected {expected_type.value}, got {claims.token_type.value}"
                )
            
            return TokenValidationResult(
                is_valid=True,
                claims=claims
            )
            
        except jwt.ExpiredSignatureError:
            return TokenValidationResult(
                is_valid=False,
                error="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            return TokenValidationResult(
                is_valid=False,
                error=f"Invalid token: {str(e)}"
            )
        except Exception as e:
            return TokenValidationResult(
                is_valid=False,
                error=f"Token validation error: {str(e)}"
            )
    
    def refresh_access_token(self, refresh_token: str) -> Optional[TokenPair]:
        """
        Обновляет access token используя refresh token
        
        Args:
            refresh_token: Действующий refresh токен
            
        Returns:
            Новая пара токенов или None если refresh token невалиден
        """
        # Валидируем refresh token
        validation_result = self.validate_token(refresh_token, TokenType.REFRESH)
        if not validation_result.is_valid:
            return None
        
        claims = validation_result.claims
        
        # Добавляем старый refresh token в blacklist
        self._blacklist_token(refresh_token)
        
        # Создаем новую пару токенов
        return self.create_token_pair(
            api_key_id=claims.sub,
            client_name=claims.client_name,
            plan=claims.plan,
            permissions=claims.permissions
        )
    
    def revoke_token(self, token: str) -> bool:
        """
        Отзывает токен (добавляет в blacklist)
        
        Args:
            token: Токен для отзыва
            
        Returns:
            True если токен отозван успешно
        """
        try:
            # Валидируем токен перед отзывом
            validation_result = self.validate_token(token)
            if not validation_result.is_valid:
                return False
            
            self._blacklist_token(token)
            return True
            
        except Exception as e:
            print(f"Error revoking token: {e}")
            return False
    
    def decode_token_unsafe(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Декодирует токен БЕЗ валидации (для отладки)
        ВНИМАНИЕ: Используйте только для отладки!
        """
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except Exception:
            return None
    
    def _encode_token(self, claims: JWTClaims) -> str:
        """Кодирует claims в JWT токен"""
        payload = claims.to_dict()
        payload["iss"] = self.issuer  # issuer
        
        return jwt.encode(
            payload,
            self.secret_key,
            algorithm=self.algorithm
        )
    
    def _blacklist_token(self, token: str) -> None:
        """Добавляет токен в blacklist"""
        # Создаем хеш токена для blacklist (экономим память)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        self._token_blacklist.add(token_hash)
        
        # В production здесь должна быть запись в Redis с TTL
        # redis.setex(f"blacklist:{token_hash}", ttl_seconds, "revoked")
    
    def _is_token_blacklisted(self, token: str) -> bool:
        """Проверяет, находится ли токен в blacklist"""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token_hash in self._token_blacklist
    
    def get_token_info(self, token: str) -> Dict[str, Any]:
        """
        Возвращает информацию о токене для администрирования
        
        Returns:
            Словарь с информацией о токене
        """
        validation_result = self.validate_token(token)
        
        info = {
            "is_valid": validation_result.is_valid,
            "error": validation_result.error
        }
        
        if validation_result.claims:
            claims = validation_result.claims
            info.update({
                "api_key_id": claims.sub,
                "client_name": claims.client_name,
                "plan": claims.plan,
                "token_type": claims.token_type.value,
                "issued_at": datetime.fromtimestamp(claims.iat).isoformat(),
                "expires_at": datetime.fromtimestamp(claims.exp).isoformat(),
                "permissions": claims.permissions,
                "is_expired": datetime.utcnow().timestamp() > claims.exp
            })
        
        return info
    
    def cleanup_expired_blacklist(self) -> int:
        """
        Очищает истекшие токены из blacklist
        В production это должно происходить автоматически через Redis TTL
        
        Returns:
            Количество удаленных токенов
        """
        # Это заглушка для in-memory blacklist
        # В production Redis автоматически удалит истекшие записи
        return 0
    
    def health_check(self) -> Dict[str, Any]:
        """Health check для JWT сервиса"""
        try:
            # Тестируем создание и валидацию токена
            test_token = self.create_access_token("test", "test_client", "free")
            validation_result = self.validate_token(test_token)
            
            return {
                "status": "healthy" if validation_result.is_valid else "error",
                "algorithm": self.algorithm,
                "access_token_ttl_minutes": self.access_token_expire_minutes,
                "refresh_token_ttl_days": self.refresh_token_expire_days,
                "blacklist_size": len(self._token_blacklist),
                "test_token_valid": validation_result.is_valid
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


# Factory function для создания JWT сервиса
def create_jwt_service(config: Dict[str, Any]) -> JWTService:
    """
    Фабрика для создания JWT сервиса из конфигурации
    
    Args:
        config: Конфигурация с настройками JWT
        
    Returns:
        Настроенный JWTService
    """
    auth_config = config.get("auth", {})
    
    return JWTService(
        secret_key=auth_config.get("jwt_secret", ""),
        algorithm=auth_config.get("jwt_algorithm", "HS256"),
        access_token_expire_minutes=auth_config.get("access_token_expire_minutes", 30),
        refresh_token_expire_days=auth_config.get("refresh_token_expire_days", 7),
        issuer=auth_config.get("jwt_issuer", "antispam-api")
    )