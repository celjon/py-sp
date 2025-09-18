# src/domain/service/error_handling/error_handler.py
"""
Production Error Handler with Graceful Degradation
Обеспечивает устойчивость системы при различных типах ошибок
"""

import traceback
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Callable, List, Union
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class ErrorSeverity(Enum):
    """Уровни серьезности ошибок"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Категории ошибок"""

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    EXTERNAL_SERVICE = "external_service"
    DATABASE = "database"
    CACHE = "cache"
    BUSINESS_LOGIC = "business_logic"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    """Контекст ошибки для логирования и мониторинга"""

    error_id: str
    timestamp: datetime
    severity: ErrorSeverity
    category: ErrorCategory
    service_name: str
    endpoint: Optional[str] = None
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    request_id: Optional[str] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CircuitBreakerState:
    """Состояние circuit breaker"""

    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    success_count: int = 0


class ProductionErrorHandler:
    """
    Production-ready Error Handler

    Features:
    - Graceful degradation при отказе внешних сервисов
    - Circuit breaker pattern для защиты
    - Structured error logging
    - Error aggregation и alerting
    - Automatic retry logic
    - Fallback mechanisms
    """

    def __init__(
        self,
        service_name: str = "antispam-api",
        enable_circuit_breaker: bool = True,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: int = 60,
        enable_error_aggregation: bool = True,
        max_error_cache_size: int = 1000,
    ):
        """
        Инициализация error handler

        Args:
            service_name: Название сервиса
            enable_circuit_breaker: Включить circuit breaker
            circuit_breaker_threshold: Порог ошибок для открытия circuit
            circuit_breaker_timeout: Таймаут circuit breaker в секундах
            enable_error_aggregation: Включить агрегацию ошибок
            max_error_cache_size: Максимальный размер кэша ошибок
        """
        self.service_name = service_name
        self.enable_circuit_breaker = enable_circuit_breaker
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_timeout = circuit_breaker_timeout
        self.enable_error_aggregation = enable_error_aggregation

        # Circuit breakers для внешних сервисов
        self.circuit_breakers: Dict[str, CircuitBreakerState] = {}

        # Кэш ошибок для агрегации
        self.error_cache: List[ErrorContext] = []
        self.max_error_cache_size = max_error_cache_size

        # Статистика ошибок
        self.error_stats: Dict[str, Any] = {
            "total_errors": 0,
            "errors_by_category": {},
            "errors_by_severity": {},
            "last_error_time": None,
        }

        # Настройка логирования
        self.logger = logging.getLogger(f"{service_name}.error_handler")

        print(f"🛡️ Production Error Handler инициализирован для {service_name}")

    async def handle_error(
        self,
        error: Exception,
        context: Optional[ErrorContext] = None,
        request: Optional[Request] = None,
    ) -> JSONResponse:
        """
        Основной обработчик ошибок

        Args:
            error: Исключение для обработки
            context: Контекст ошибки
            request: FastAPI Request объект

        Returns:
            JSONResponse с детальной информацией об ошибке
        """
        try:
            # Создаем контекст если не передан
            if not context:
                context = await self._create_error_context(error, request)

            # Логируем ошибку
            await self._log_error(error, context)

            # Обновляем статистику
            self._update_error_stats(context)

            # Кэшируем для агрегации
            if self.enable_error_aggregation:
                self._cache_error(context)

            # Определяем тип ошибки и создаем ответ
            response = await self._create_error_response(error, context)

            return response

        except Exception as e:
            # Fallback на минимальный ответ если error handler сам упал
            self.logger.critical(f"Error handler failed: {e}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "Internal server error",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error_id": "fallback_error",
                },
            )

    async def _create_error_context(
        self, error: Exception, request: Optional[Request] = None
    ) -> ErrorContext:
        """Создает контекст ошибки"""
        import uuid

        error_id = str(uuid.uuid4())[:8]
        severity = self._determine_severity(error)
        category = self._determine_category(error)

        context = ErrorContext(
            error_id=error_id,
            timestamp=datetime.now(timezone.utc),
            severity=severity,
            category=category,
            service_name=self.service_name,
        )

        # Добавляем информацию из request
        if request:
            context.endpoint = str(request.url.path)
            context.request_id = request.headers.get("X-Request-ID")

            # API key info если доступно
            if hasattr(request.state, "api_key"):
                context.api_key_id = str(request.state.api_key.id)
                context.user_id = request.state.api_key.client_name

        return context

    def _determine_severity(self, error: Exception) -> ErrorSeverity:
        """Определяет серьезность ошибки"""
        if isinstance(error, (ConnectionError, TimeoutError)):
            return ErrorSeverity.HIGH
        elif isinstance(error, HTTPException):
            if error.status_code >= 500:
                return ErrorSeverity.HIGH
            elif error.status_code == 429:
                return ErrorSeverity.MEDIUM
            else:
                return ErrorSeverity.LOW
        elif isinstance(error, (ValueError, TypeError)):
            return ErrorSeverity.MEDIUM
        else:
            return ErrorSeverity.HIGH

    def _determine_category(self, error: Exception) -> ErrorCategory:
        """Определяет категорию ошибки"""
        if isinstance(error, HTTPException):
            if error.status_code == 401:
                return ErrorCategory.AUTHENTICATION
            elif error.status_code == 403:
                return ErrorCategory.AUTHORIZATION
            elif error.status_code == 429:
                return ErrorCategory.RATE_LIMIT
            elif error.status_code == 422:
                return ErrorCategory.VALIDATION
        elif isinstance(error, (ConnectionError, TimeoutError)):
            return ErrorCategory.EXTERNAL_SERVICE
        elif isinstance(error, ValueError):
            return ErrorCategory.VALIDATION
        else:
            return ErrorCategory.UNKNOWN

    async def _log_error(self, error: Exception, context: ErrorContext):
        """Структурированное логирование ошибки"""
        log_data = {
            "error_id": context.error_id,
            "timestamp": context.timestamp.isoformat(),
            "severity": context.severity.value,
            "category": context.category.value,
            "service": context.service_name,
            "endpoint": context.endpoint,
            "api_key_id": context.api_key_id,
            "user_id": context.user_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": (
                traceback.format_exc()
                if context.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]
                else None
            ),
        }

        # Выбираем уровень логирования
        if context.severity == ErrorSeverity.CRITICAL:
            self.logger.critical("Critical error occurred", extra=log_data)
        elif context.severity == ErrorSeverity.HIGH:
            self.logger.error("High severity error", extra=log_data)
        elif context.severity == ErrorSeverity.MEDIUM:
            self.logger.warning("Medium severity error", extra=log_data)
        else:
            self.logger.info("Low severity error", extra=log_data)

    def _update_error_stats(self, context: ErrorContext):
        """Обновляет статистику ошибок"""
        self.error_stats["total_errors"] += 1
        self.error_stats["last_error_time"] = context.timestamp

        # По категориям
        category_key = context.category.value
        if category_key not in self.error_stats["errors_by_category"]:
            self.error_stats["errors_by_category"][category_key] = 0
        self.error_stats["errors_by_category"][category_key] += 1

        # По серьезности
        severity_key = context.severity.value
        if severity_key not in self.error_stats["errors_by_severity"]:
            self.error_stats["errors_by_severity"][severity_key] = 0
        self.error_stats["errors_by_severity"][severity_key] += 1

    def _cache_error(self, context: ErrorContext):
        """Кэширует ошибку для агрегации"""
        self.error_cache.append(context)

        # Ограничиваем размер кэша
        if len(self.error_cache) > self.max_error_cache_size:
            self.error_cache = self.error_cache[-self.max_error_cache_size :]

    async def _create_error_response(self, error: Exception, context: ErrorContext) -> JSONResponse:
        """Создает ответ об ошибке"""

        # Базовая структура ответа
        response_data = {
            "error": self._get_user_friendly_message(error, context),
            "error_id": context.error_id,
            "timestamp": context.timestamp.isoformat(),
            "category": context.category.value,
        }

        # Добавляем детали в зависимости от типа ошибки
        if isinstance(error, HTTPException):
            status_code = error.status_code
            if hasattr(error, "detail") and error.detail:
                response_data["details"] = error.detail
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        # Добавляем дополнительную информацию для разработчиков
        if context.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            response_data["support_info"] = {
                "contact": "support@antispam.com",
                "documentation": "https://docs.antispam.com/troubleshooting",
                "error_reference": f"ERR-{context.error_id}",
            }

        # Добавляем информацию о retry для временных ошибок
        if context.category == ErrorCategory.EXTERNAL_SERVICE:
            response_data["retry_info"] = {
                "retryable": True,
                "suggested_delay_seconds": 30,
                "max_retries": 3,
            }
        elif context.category == ErrorCategory.RATE_LIMIT:
            response_data["retry_info"] = {
                "retryable": True,
                "suggested_delay_seconds": 60,
                "rate_limit_reset": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            }

        return JSONResponse(
            status_code=status_code,
            content=response_data,
            headers={"X-Error-ID": context.error_id, "X-Error-Category": context.category.value},
        )

    def _get_user_friendly_message(self, error: Exception, context: ErrorContext) -> str:
        """Возвращает понятное пользователю сообщение об ошибке"""

        if context.category == ErrorCategory.AUTHENTICATION:
            return "Authentication failed. Please check your API key."
        elif context.category == ErrorCategory.AUTHORIZATION:
            return "Access denied. Insufficient permissions."
        elif context.category == ErrorCategory.RATE_LIMIT:
            return "Rate limit exceeded. Please slow down your requests."
        elif context.category == ErrorCategory.VALIDATION:
            return "Invalid request data. Please check your input."
        elif context.category == ErrorCategory.EXTERNAL_SERVICE:
            return "External service temporarily unavailable. Please try again later."
        elif context.category == ErrorCategory.DATABASE:
            return "Database service temporarily unavailable. Please try again."
        elif context.category == ErrorCategory.CACHE:
            return "Cache service unavailable. Functionality may be slower."
        else:
            return "An unexpected error occurred. Please try again or contact support."

    # === CIRCUIT BREAKER METHODS ===

    def get_circuit_breaker(self, service_name: str) -> CircuitBreakerState:
        """Получает состояние circuit breaker для сервиса"""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreakerState()
        return self.circuit_breakers[service_name]

    def is_circuit_open(self, service_name: str) -> bool:
        """Проверяет, открыт ли circuit breaker"""
        if not self.enable_circuit_breaker:
            return False

        breaker = self.get_circuit_breaker(service_name)

        if breaker.state == "OPEN":
            # Проверяем, можно ли попробовать снова
            if breaker.last_failure_time:
                time_since_failure = datetime.now(timezone.utc) - breaker.last_failure_time
                if time_since_failure.total_seconds() > self.circuit_breaker_timeout:
                    breaker.state = "HALF_OPEN"
                    breaker.success_count = 0
                    return False
            return True

        return False

    def record_success(self, service_name: str):
        """Записывает успешный вызов сервиса"""
        if not self.enable_circuit_breaker:
            return

        breaker = self.get_circuit_breaker(service_name)

        if breaker.state == "HALF_OPEN":
            breaker.success_count += 1
            if breaker.success_count >= 3:  # 3 успешных вызова для закрытия
                breaker.state = "CLOSED"
                breaker.failure_count = 0
        elif breaker.state == "CLOSED":
            breaker.failure_count = max(0, breaker.failure_count - 1)  # Уменьшаем счетчик ошибок

    def record_failure(self, service_name: str):
        """Записывает неудачный вызов сервиса"""
        if not self.enable_circuit_breaker:
            return

        breaker = self.get_circuit_breaker(service_name)
        breaker.failure_count += 1
        breaker.last_failure_time = datetime.now(timezone.utc)

        if breaker.failure_count >= self.circuit_breaker_threshold:
            breaker.state = "OPEN"
            self.logger.warning(f"Circuit breaker opened for service: {service_name}")

    # === GRACEFUL DEGRADATION DECORATORS ===

    def with_fallback(self, fallback_func: Callable, service_name: str = "default"):
        """Декоратор для graceful degradation с fallback функцией"""

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Проверяем circuit breaker
                if self.is_circuit_open(service_name):
                    self.logger.info(f"Circuit breaker open for {service_name}, using fallback")
                    return await fallback_func(*args, **kwargs)

                try:
                    result = await func(*args, **kwargs)
                    self.record_success(service_name)
                    return result

                except Exception as e:
                    self.record_failure(service_name)

                    # Для критических ошибок используем fallback
                    context = await self._create_error_context(e)
                    if context.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
                        self.logger.warning(f"Using fallback for {service_name} due to error: {e}")
                        return await fallback_func(*args, **kwargs)
                    else:
                        raise

            return wrapper

        return decorator

    def with_retry(self, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
        """Декоратор для автоматического retry"""

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                last_exception = None

                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e

                        # Определяем, стоит ли повторять
                        if not self._should_retry(e):
                            raise

                        if attempt < max_retries:
                            wait_time = delay * (backoff**attempt)
                            self.logger.info(
                                f"Retrying {func.__name__} in {wait_time}s (attempt {attempt + 1})"
                            )
                            await asyncio.sleep(wait_time)
                        else:
                            self.logger.error(f"Max retries exceeded for {func.__name__}")

                raise last_exception

            return wrapper

        return decorator

    def _should_retry(self, error: Exception) -> bool:
        """Определяет, стоит ли повторять запрос при данной ошибке"""
        # Повторяем только для временных ошибок
        if isinstance(error, (ConnectionError, TimeoutError)):
            return True
        elif isinstance(error, HTTPException):
            # Повторяем для 5xx ошибок, но не для 4xx
            return 500 <= error.status_code < 600
        return False

    # === MONITORING AND HEALTH ===

    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Возвращает сводку ошибок за период"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        recent_errors = [error for error in self.error_cache if error.timestamp > cutoff_time]

        summary = {
            "period_hours": hours,
            "total_errors": len(recent_errors),
            "errors_by_category": {},
            "errors_by_severity": {},
            "top_endpoints": {},
            "circuit_breaker_status": {
                name: breaker.state for name, breaker in self.circuit_breakers.items()
            },
        }

        # Агрегируем по категориям
        for error in recent_errors:
            category = error.category.value
            severity = error.severity.value
            endpoint = error.endpoint or "unknown"

            summary["errors_by_category"][category] = (
                summary["errors_by_category"].get(category, 0) + 1
            )
            summary["errors_by_severity"][severity] = (
                summary["errors_by_severity"].get(severity, 0) + 1
            )
            summary["top_endpoints"][endpoint] = summary["top_endpoints"].get(endpoint, 0) + 1

        return summary

    def health_check(self) -> Dict[str, Any]:
        """Health check для error handler"""
        try:
            recent_errors = len(
                [
                    error
                    for error in self.error_cache
                    if error.timestamp > datetime.now(timezone.utc) - timedelta(minutes=5)
                ]
            )

            # Определяем здоровье на основе недавних ошибок
            if recent_errors > 50:
                health_status = "critical"
            elif recent_errors > 20:
                health_status = "degraded"
            elif recent_errors > 5:
                health_status = "warning"
            else:
                health_status = "healthy"

            return {
                "status": health_status,
                "total_errors": self.error_stats["total_errors"],
                "recent_errors_5min": recent_errors,
                "circuit_breakers": {
                    name: breaker.state for name, breaker in self.circuit_breakers.items()
                },
                "error_cache_size": len(self.error_cache),
                "last_error": (
                    self.error_stats["last_error_time"].isoformat()
                    if self.error_stats["last_error_time"]
                    else None
                ),
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}


# === FACTORY FUNCTION ===


def create_error_handler(
    service_name: str = "antispam-api", config: Optional[Dict[str, Any]] = None
) -> ProductionErrorHandler:
    """
    Factory function для создания error handler

    Args:
        service_name: Название сервиса
        config: Конфигурация error handler

    Returns:
        Настроенный ProductionErrorHandler
    """
    if config is None:
        config = {}

    return ProductionErrorHandler(
        service_name=service_name,
        enable_circuit_breaker=config.get("enable_circuit_breaker", True),
        circuit_breaker_threshold=config.get("circuit_breaker_threshold", 5),
        circuit_breaker_timeout=config.get("circuit_breaker_timeout", 60),
        enable_error_aggregation=config.get("enable_error_aggregation", True),
        max_error_cache_size=config.get("max_error_cache_size", 1000),
    )


# === EXAMPLE USAGE ===

if __name__ == "__main__":
    import asyncio

    async def example_usage():
        # Создаем error handler
        error_handler = create_error_handler("test-service")

        # Пример fallback функции
        async def fallback_detection(text: str):
            return {
                "is_spam": False,
                "confidence": 0.5,
                "reason": "fallback_mode",
                "notes": "Service unavailable, using fallback",
            }

        # Пример функции с ошибками
        @error_handler.with_fallback(fallback_detection, "spam_detector")
        @error_handler.with_retry(max_retries=3, delay=1.0)
        async def detect_spam(text: str):
            # Симулируем ошибку
            if "error" in text:
                raise ConnectionError("External service unavailable")
            return {"is_spam": True, "confidence": 0.9}

        # Тестируем
        result1 = await detect_spam("normal text")
        print(f"Normal: {result1}")

        result2 = await detect_spam("error text")  # Используется fallback
        print(f"With error: {result2}")

        # Проверяем здоровье
        health = error_handler.health_check()
        print(f"Health: {health}")

    asyncio.run(example_usage())
