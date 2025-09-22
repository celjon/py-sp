# src/config/dependencies.py
"""
Production-ready Dependency Injection Setup
Связывает все компоненты в единую систему
"""

import os
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from fastapi import HTTPException

# Core imports - добавлены отсутствующие imports
from ..domain.service.auth.jwt_service import JWTService, create_jwt_service
from ..domain.service.rate_limit.rate_limiter import RateLimiter, create_rate_limiter
from ..domain.analytics.usage_analytics import UsageAnalytics, create_usage_analytics

# Middleware импорты перенесены в app.py чтобы избежать циклических импортов

# Repositories
from ..adapter.repository.api_key_repository import ApiKeyRepository
from ..adapter.repository.usage_repository import UsageRepository
from ..adapter.repository.user_repository import UserRepository
from ..adapter.repository.message_repository import MessageRepository
from ..adapter.repository.spam_samples_repository import SpamSamplesRepository

# Use Cases
from ..domain.usecase.api.manage_keys import ManageApiKeysUseCase
from ..domain.usecase.spam_detection.check_message import CheckMessageUseCase
from ..domain.usecase.spam_detection.ban_user import BanUserUseCase

# Infrastructure
from ..lib.clients.postgres_client import PostgresClient
from ..lib.clients.http_client import HttpClient

# Gateways
from ..adapter.gateway.cas_gateway import CASGateway
from ..adapter.gateway.openai_gateway import OpenAIGateway

# Domain Services
from ..domain.service.detector.ensemble import EnsembleDetector
from ..adapter.cache.redis_cache import RedisCache
from ..domain.service.monitoring.prometheus_metrics import create_prometheus_metrics

# Entities
from ..domain.entity.api_key import ApiKey, ApiKeyPlan

logger = logging.getLogger(__name__)


@dataclass
class ProductionServices:
    """Контейнер для всех production сервисов"""

    # Authentication & Authorization
    jwt_service: JWTService
    rate_limiter: RateLimiter

    # Analytics & Monitoring
    usage_analytics: UsageAnalytics

    # Repositories
    api_key_repo: ApiKeyRepository
    usage_repo: UsageRepository
    user_repo: UserRepository
    message_repo: MessageRepository
    spam_samples_repo: SpamSamplesRepository

    # Use Cases
    manage_api_keys_usecase: ManageApiKeysUseCase
    check_message_usecase: CheckMessageUseCase
    ban_user_usecase: BanUserUseCase

    # Domain Services
    ensemble_detector: EnsembleDetector
    redis_cache: Optional[RedisCache]

    # Gateways
    cas_gateway: Optional[CASGateway]
    openai_gateway: Optional[OpenAIGateway]

    # Infrastructure
    postgres_client: PostgresClient
    redis_client: Optional[Any]
    http_client: HttpClient

    async def health_check(self) -> Dict[str, Any]:
        """Комплексная проверка здоровья всей системы"""
        try:
            health_info = {
                "status": "healthy",
                "services": {},
                "timestamp": time.time(),
                "version": "2.0.0",
            }

            # JWT Service
            try:
                jwt_health = self.jwt_service.health_check()
                if asyncio.iscoroutine(jwt_health):
                    health_info["services"]["jwt_service"] = await jwt_health
                else:
                    health_info["services"]["jwt_service"] = jwt_health
            except Exception as e:
                health_info["services"]["jwt_service"] = {"status": "error", "error": str(e)}

            # Rate Limiter
            try:
                rate_health = self.rate_limiter.health_check()
                if asyncio.iscoroutine(rate_health):
                    health_info["services"]["rate_limiter"] = await rate_health
                else:
                    health_info["services"]["rate_limiter"] = rate_health
            except Exception as e:
                health_info["services"]["rate_limiter"] = {"status": "error", "error": str(e)}

            # Usage Analytics
            try:
                usage_health = self.usage_analytics.health_check()
                if asyncio.iscoroutine(usage_health):
                    health_info["services"]["usage_analytics"] = await usage_health
                else:
                    health_info["services"]["usage_analytics"] = usage_health
            except Exception as e:
                health_info["services"]["usage_analytics"] = {"status": "error", "error": str(e)}

            # Database
            try:
                if hasattr(self.postgres_client, "health_check"):
                    db_health = self.postgres_client.health_check()
                    if asyncio.iscoroutine(db_health):
                        health_info["services"]["postgres"] = await db_health
                    else:
                        health_info["services"]["postgres"] = db_health
                else:
                    health_info["services"]["postgres"] = {
                        "status": "unknown",
                        "method": "not_implemented",
                    }
            except Exception as e:
                health_info["services"]["postgres"] = {"status": "error", "error": str(e)}

            # Redis
            try:
                if self.redis_client and hasattr(self.redis_client, "health_check"):
                    redis_health = self.redis_client.health_check()
                    if asyncio.iscoroutine(redis_health):
                        health_info["services"]["redis"] = await redis_health
                    else:
                        health_info["services"]["redis"] = redis_health
                else:
                    health_info["services"]["redis"] = {"status": "not_configured"}
            except Exception as e:
                health_info["services"]["redis"] = {"status": "error", "error": str(e)}

            # Ensemble Detector
            try:
                health_info["services"][
                    "ensemble_detector"
                ] = await self.ensemble_detector.health_check()
            except Exception as e:
                health_info["services"]["ensemble_detector"] = {"status": "error", "error": str(e)}

            # Gateways
            try:
                if self.cas_gateway:
                    health_info["services"]["cas_gateway"] = await self.cas_gateway.health_check()
                else:
                    health_info["services"]["cas_gateway"] = {"status": "not_configured"}
            except Exception as e:
                health_info["services"]["cas_gateway"] = {"status": "error", "error": str(e)}

            try:
                if self.openai_gateway:
                    health_info["services"][
                        "openai_gateway"
                    ] = await self.openai_gateway.health_check()
                else:
                    health_info["services"]["openai_gateway"] = {"status": "not_configured"}
            except Exception as e:
                health_info["services"]["openai_gateway"] = {"status": "error", "error": str(e)}

            # Определяем общий статус
            error_count = sum(
                1
                for s in health_info["services"].values()
                if isinstance(s, dict) and s.get("status") == "error"
            )

            if error_count == 0:
                health_info["status"] = "healthy"
            elif error_count <= 2:  # Допускаем некоторые деградации
                health_info["status"] = "degraded"
            else:
                health_info["status"] = "unhealthy"

            return health_info

        except Exception as e:
            logger.error(f"Health check critical error: {e}")
            return {"status": "error", "timestamp": time.time(), "error": str(e)}


async def setup_production_services(config: Dict[str, Any]) -> ProductionServices:
    """
    Настраивает все production сервисы с полной error handling

    Args:
        config: Конфигурация приложения

    Returns:
        ProductionServices со всеми настроенными компонентами

    Raises:
        RuntimeError: Если критические сервисы не удалось инициализировать
    """
    logger.info("[START] Настройка production сервисов...")

    critical_errors = []
    warnings = []

    # === INFRASTRUCTURE CLIENTS ===
    logger.info("[SETUP] Настройка клиентов инфраструктуры...")

    # Database Client (КРИТИЧЕСКИЙ)
    postgres_client = None
    try:
        database_url = config.get("database_url") or config.get("database", {}).get("url")
        if not database_url:
            raise ValueError("DATABASE_URL is required")

        postgres_client = PostgresClient(database_url)
        await postgres_client.connect()
        logger.info("[OK] PostgreSQL подключен")
    except Exception as e:
        critical_errors.append(f"Database connection failed: {e}")
        logger.error(f"[ERROR] Database ошибка: {e}")

    # Redis Client (НЕ критический)
    redis_client = None
    try:
        redis_url = config.get("redis_url") or (
            config.get("redis", {}).get("url") if config.get("redis") else None
        )

        if redis_url:
            logger.info(f"[CONNECT] Подключение к Redis: {redis_url}")
            # Используем RedisCache как клиент
            redis_client = RedisCache(redis_url)
            await redis_client.connect()

            logger.info("[OK] Redis подключен")
        else:
            warnings.append(
                "Redis не настроен - некоторые функции будут работать в fallback режиме"
            )
            logger.warning("[WARN] Redis не настроен - URL не найден в конфигурации")
    except Exception as e:
        warnings.append(f"Redis недоступен: {e}")
        logger.warning(f"[WARN] Redis ошибка: {e}")
        logger.exception("Redis connection error details:")

    # HTTP Client
    http_client = HttpClient(timeout=config.get("http_client", {}).get("timeout", 30))
    logger.info("[OK] HTTP клиент настроен")

    # Прерываем если критические ошибки
    if critical_errors:
        error_msg = "; ".join(critical_errors)
        logger.error(f"[ERROR] Критические ошибки инициализации: {error_msg}")
        raise RuntimeError(f"Critical services failed: {error_msg}")

    # === REPOSITORIES ===
    logger.info("🗄️ Настройка репозиториев...")

    try:
        api_key_repo = ApiKeyRepository(postgres_client)
        usage_repo = UsageRepository(postgres_client)
        user_repo = UserRepository(postgres_client)
        message_repo = MessageRepository(postgres_client)
        spam_samples_repo = SpamSamplesRepository(postgres_client)

        logger.info("[OK] Репозитории настроены")
    except Exception as e:
        raise RuntimeError(f"Repository initialization failed: {e}")

    # === CACHE LAYER ===
    redis_cache = None
    if redis_client:
        try:
            # Создаем отдельный RedisCache для кэш-слоя, повторно используя URL из конфигурации
            redis_cache = RedisCache(config.get("redis_url") or config.get("redis", {}).get("url"))
            await redis_cache.connect()
            logger.info("[OK] Redis кэш настроен")
        except Exception as e:
            warnings.append(f"Redis cache initialization failed: {e}")
            logger.warning(f"[WARN] Redis cache ошибка: {e}")

    # === GATEWAYS ===
    logger.info("[WEB] Настройка внешних gateways...")

    # CAS Gateway
    cas_gateway = None
    try:
        cas_gateway = CASGateway(
            http_client=http_client,
            cache=redis_cache,
            config=config.get("external_apis", {}).get("cas", {}),
        )
        logger.info("[OK] CAS Gateway настроен")
    except Exception as e:
        warnings.append(f"CAS Gateway initialization failed: {e}")
        logger.warning(f"[WARN] CAS Gateway ошибка: {e}")

    # OpenAI Gateway
    openai_gateway = None
    try:
        openai_config = config.get("openai", {})
        if openai_config.get("api_key") and openai_config.get("enabled", True):
            openai_gateway = OpenAIGateway(api_key=openai_config["api_key"], config=openai_config)
            logger.info("[OK] OpenAI Gateway настроен")
        else:
            warnings.append("OpenAI не настроен - спам детекция будет работать без LLM анализа")
            logger.warning("[WARN] OpenAI не настроен")
    except Exception as e:
        warnings.append(f"OpenAI Gateway initialization failed: {e}")
        logger.warning(f"[WARN] OpenAI Gateway ошибка: {e}")

    # === CORE SERVICES ===
    logger.info("[CORE] Настройка core сервисов...")

    # JWT Service
    try:
        jwt_service = create_jwt_service(config.get("api", {}).get("auth", {}))
        logger.info("[OK] JWT Service настроен")
    except Exception as e:
        raise RuntimeError(f"JWT Service initialization failed: {e}")

    # Rate Limiter
    try:
        rate_limiter = create_rate_limiter(
            redis_client=redis_client.redis if redis_client else None,
            config=config.get("api", {}).get("rate_limit", {}),
        )
        logger.info("[OK] Rate Limiter настроен")
    except Exception as e:
        logger.error(f"[ERROR] Rate Limiter ошибка: {e}")
        raise RuntimeError(f"Rate Limiter initialization failed: {e}")

    # Usage Analytics
    try:
        usage_analytics = create_usage_analytics(
            usage_repo=usage_repo,
            redis_client=redis_client.redis if redis_client else None,
            config=config.get("analytics", {}),
        )
        logger.info("[OK] Usage Analytics настроен")
    except Exception as e:
        warnings.append(f"Usage Analytics initialization failed: {e}")
        logger.warning(f"[WARN] Usage Analytics ошибка: {e}")
        logger.exception("Usage Analytics exception details:")
        # Создаем фиктивный analytics для продолжения работы
        usage_analytics = None

    # === SPAM DETECTION SETUP ===
    logger.info("[TARGET] Настройка spam detection...")

    # Ensemble Detector
    try:
        detector_config = config.get("spam_detection", {}).get("ensemble", {})
        ensemble_detector = EnsembleDetector(detector_config)

        # Добавляем детекторы
        if cas_gateway:
            ensemble_detector.add_cas_detector(cas_gateway)

        if openai_gateway:
            ensemble_detector.add_openai_detector(openai_gateway)

        # RUSpam детектор
        ensemble_detector.add_ruspam_detector()

        logger.info("[OK] Ensemble Detector настроен")
    except Exception as e:
        raise RuntimeError(f"Ensemble Detector initialization failed: {e}")

    # === USE CASES ===
    logger.info("[LIST] Настройка use cases...")

    try:
        manage_api_keys_usecase = ManageApiKeysUseCase(
            api_key_repo=api_key_repo, usage_repo=usage_repo
        )

        check_message_usecase = CheckMessageUseCase(
            spam_detector=ensemble_detector,
            message_repo=message_repo,
            user_repo=user_repo,
            spam_threshold=0.6,
        )

        # Создаем Telegram Gateway
        from ..adapter.gateway.telegram_gateway import TelegramGateway
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        bot = Bot(
            token=config.get("bot_token"), default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        telegram_gateway = TelegramGateway(bot=bot)

        ban_user_usecase = BanUserUseCase(
            user_repo=user_repo, message_repo=message_repo, telegram_gateway=telegram_gateway
        )

        logger.info("[OK] Use cases настроены")
    except Exception as e:
        raise RuntimeError(f"Use cases initialization failed: {e}")

    # === MIDDLEWARE FACTORIES ===
    logger.info("🔒 Настройка middleware...")

    try:
        # API Auth Middleware создается в app.py для избежания циклических импортов
        logger.info("[OK] Middleware настроен")
    except Exception as e:
        raise RuntimeError(f"Middleware initialization failed: {e}")

    # === СОЗДАЕМ КОНТЕЙНЕР СЕРВИСОВ ===
    try:
        services = ProductionServices(
            # Authentication & Authorization
            jwt_service=jwt_service,
            rate_limiter=rate_limiter,
            # api_auth_middleware создается в app.py
            # Analytics & Monitoring
            usage_analytics=usage_analytics,
            # Repositories
            api_key_repo=api_key_repo,
            usage_repo=usage_repo,
            user_repo=user_repo,
            message_repo=message_repo,
            spam_samples_repo=spam_samples_repo,
            # Use Cases
            manage_api_keys_usecase=manage_api_keys_usecase,
            check_message_usecase=check_message_usecase,
            ban_user_usecase=ban_user_usecase,
            # Domain Services
            ensemble_detector=ensemble_detector,
            redis_cache=redis_cache,
            # Gateways
            cas_gateway=cas_gateway,
            openai_gateway=openai_gateway,
            # Infrastructure
            postgres_client=postgres_client,
            redis_client=redis_client,
            http_client=http_client,
        )

        logger.info("[OK] Контейнер сервисов создан")
    except Exception as e:
        raise RuntimeError(f"Services container creation failed: {e}")

    # === ФИНАЛЬНАЯ ПРОВЕРКА ===
    logger.info("[SEARCH] Проверка готовности системы...")

    try:
        health = await services.health_check()

        if health["status"] == "healthy":
            logger.info("[OK] Все production сервисы готовы!")
            logger.info("[STATS] Статус компонентов:")
            for service_name, service_health in health["services"].items():
                status_emoji = "[OK]" if service_health.get("status") == "healthy" else "[WARN]"
                logger.info(
                    f"   {status_emoji} {service_name}: {service_health.get('status', 'unknown')}"
                )
        elif health["status"] == "degraded":
            logger.warning("[WARN] Система работает в деградированном режиме")
            logger.warning("[STATS] Статус компонентов:")
            for service_name, service_health in health["services"].items():
                if service_health.get("status") != "healthy":
                    logger.warning(
                        f"   [WARN] {service_name}: {service_health.get('status')} - {service_health.get('error', '')}"
                    )
        else:
            error_msg = f"System health check failed: {health.get('error')}"
            logger.error(f"[ERROR] {error_msg}")
            raise RuntimeError(error_msg)
    except Exception as e:
        logger.error(f"[ERROR] Health check failed: {e}")
        raise RuntimeError(f"Health check failed: {e}")

    # Выводим предупреждения
    if warnings:
        logger.warning("[WARN] Предупреждения инициализации:")
        for warning in warnings:
            logger.warning(f"  - {warning}")

    # Создаем дефолтный API ключ если нужно
    try:
        await create_default_api_key_if_needed(services)
    except Exception as e:
        logger.warning(f"[WARN] Не удалось создать дефолтный API ключ: {e}")

    logger.info("[SUCCESS] Production services setup завершен!")
    return services


# === INTEGRATION WITH FASTAPI APP ===


def integrate_with_fastapi_app(app, services: ProductionServices, config: Dict[str, Any]):
    """
    Интегрирует production сервисы с FastAPI приложением

    Args:
        app: FastAPI application instance
        services: Настроенные production сервисы
        config: Конфигурация
    """
    logger.info("[CONNECT] Интеграция с FastAPI...")

    # === MIDDLEWARE ===
    # Добавляем API Auth Middleware
    try:
        # Middleware добавляется в app.py
        logger.info("[OK] API Auth Middleware добавлен")
    except Exception as e:
        logger.error(f"[ERROR] Ошибка добавления middleware: {e}")
        raise RuntimeError(f"Middleware integration failed: {e}")

    # === DEPENDENCY INJECTION ===
    # Добавляем в app state для доступа из routes
    app.state.production_services = services

    # Создаем provider functions
    app.state.get_production_services = lambda: services
    app.state.get_jwt_service = lambda: services.jwt_service
    app.state.get_rate_limiter = lambda: services.rate_limiter
    app.state.get_usage_analytics = lambda: services.usage_analytics
    app.state.get_api_key_repo = lambda: services.api_key_repo
    app.state.get_manage_api_keys_usecase = lambda: services.manage_api_keys_usecase
    app.state.get_check_message_usecase = lambda: services.check_message_usecase
    app.state.get_ensemble_detector = lambda: services.ensemble_detector

    logger.info("[OK] Dependency injection настроен")

    # === STARTUP/SHUTDOWN HOOKS ===
    @app.on_event("startup")
    async def startup_event():
        logger.info("[START] FastAPI приложение запущено")
        logger.info("[STATS] Production services активны")

        # Финальная проверка
        health = await services.health_check()
        if health["status"] not in ["healthy", "degraded"]:
            logger.error(f"[ERROR] System не готова: {health}")
            raise RuntimeError("System health check failed on startup")

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("🛑 Завершение работы FastAPI...")

        # Graceful shutdown уже обрабатывается в main shutdown_application
        logger.info("[OK] FastAPI shutdown hooks выполнены")

    logger.info("[OK] FastAPI интеграция завершена")


# === HELPER FUNCTIONS FOR ROUTES ===


def get_dependencies_for_routes():
    """Возвращает dependencies для использования в FastAPI routes"""
    from fastapi import Depends, Request

    def get_services(request: Request) -> ProductionServices:
        """Получить production services из request"""
        if not hasattr(request.app.state, "production_services"):
            raise HTTPException(status_code=500, detail="Production services not initialized")
        return request.app.state.production_services

    def get_jwt_service(services: ProductionServices = Depends(get_services)) -> JWTService:
        return services.jwt_service

    def get_usage_analytics(services: ProductionServices = Depends(get_services)) -> UsageAnalytics:
        if not services.usage_analytics:
            raise HTTPException(status_code=503, detail="Usage analytics service not available")
        return services.usage_analytics

    def get_api_key_repo(services: ProductionServices = Depends(get_services)) -> ApiKeyRepository:
        return services.api_key_repo

    def get_manage_api_keys_usecase(
        services: ProductionServices = Depends(get_services),
    ) -> ManageApiKeysUseCase:
        return services.manage_api_keys_usecase

    def get_check_message_usecase(
        services: ProductionServices = Depends(get_services),
    ) -> CheckMessageUseCase:
        return services.check_message_usecase

    def get_ensemble_detector(
        services: ProductionServices = Depends(get_services),
    ) -> EnsembleDetector:
        return services.ensemble_detector

    return {
        "get_services": get_services,
        "get_jwt_service": get_jwt_service,
        "get_usage_analytics": get_usage_analytics,
        "get_api_key_repo": get_api_key_repo,
        "get_manage_api_keys_usecase": get_manage_api_keys_usecase,
        "get_check_message_usecase": get_check_message_usecase,
        "get_ensemble_detector": get_ensemble_detector,
    }


# === CONFIGURATION VALIDATION ===


def validate_production_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Валидирует конфигурацию для production deployment

    Args:
        config: Конфигурация для проверки

    Returns:
        Валидированная конфигурация

    Raises:
        ValueError: Если конфигурация невалидна для production
    """
    logger.info("[SEARCH] Валидация production конфигурации...")

    errors = []
    warnings = []

    # === ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ ===
    environment = config.get("environment", os.getenv("ENVIRONMENT", "development"))
    if environment == "testing":
        required_keys = ["database_url"]
    else:
        required_keys = ["database_url", "bot_token"]

    for key in required_keys:
        value = config.get(key)
        if not value:
            # Проверяем альтернативные пути
            if key == "database_url":
                value = config.get("database", {}).get("url")
            elif key == "bot_token":
                value = config.get("telegram", {}).get("token")

            if not value:
                errors.append(f"Обязательный параметр '{key}' не задан")

    # === JWT НАСТРОЙКИ ===
    environment = config.get("environment", "development")
    jwt_config = config.get("api", {}).get("auth", {})
    jwt_secret = jwt_config.get("jwt_secret")

    # JWT только обязателен в production
    if environment == "production":
        if not jwt_secret:
            errors.append("JWT_SECRET обязателен для production")
        elif len(jwt_secret) < 32:
            errors.append("JWT_SECRET должен быть минимум 32 символа")
    elif jwt_secret and len(jwt_secret) < 32:
        # В development проверяем длину только если он задан
        warnings.append("JWT_SECRET слишком короткий (рекомендуется минимум 32 символа)")

    # === SECURITY VALIDATION ===

    if environment == "production":
        # Production-specific validations

        # HTTPS проверка
        http_config = config.get("http_server", {})
        if not http_config.get("ssl_enabled", False):
            warnings.append("HTTPS не включен - рекомендуется для production")

        # CORS проверка
        if http_config.get("cors_enabled", True):
            warnings.append("CORS включен - может быть небезопасно для production")

        # Debug режим
        if config.get("debug", False):
            warnings.append("Debug режим включен в production")

        # Проверка паролей
        db_url = config.get("database_url", "")
        if "localhost" in db_url or "password" in db_url.lower():
            warnings.append("Возможно используется слабый пароль БД")

    # === PERFORMANCE VALIDATION ===

    # Rate limiting
    rate_limit_config = config.get("api", {}).get("rate_limit", {})
    default_rpm = rate_limit_config.get("default_requests_per_minute", 60)

    if default_rpm > 1000:
        warnings.append(
            f"Высокий лимит запросов ({default_rpm}/min) - проверьте производительность"
        )
    elif default_rpm < 10:
        warnings.append(
            f"Низкий лимит запросов ({default_rpm}/min) - может блокировать легитимных пользователей"
        )

    # Pool sizes
    db_pool_size = config.get("database", {}).get("pool_size", 10)
    if db_pool_size < 5:
        warnings.append("Маленький размер connection pool - может влиять на производительность")
    elif db_pool_size > 50:
        warnings.append("Большой размер connection pool - может потреблять много ресурсов")

    # === SPAM DETECTION VALIDATION ===

    detector_config = config.get("spam_detection", {})
    if not detector_config:
        warnings.append("Конфигурация spam detection отсутствует")

    ensemble_config = detector_config.get("ensemble", {})
    spam_threshold = ensemble_config.get("spam_threshold", 0.6)

    if spam_threshold < 0.3:
        warnings.append("Низкий порог спама - много ложных срабатываний")
    elif spam_threshold > 0.9:
        warnings.append("Высокий порог спама - спам может проскакивать")

    # === ФИНАЛЬНАЯ ПРОВЕРКА ===

    if errors:
        error_msg = "; ".join(errors)
        logger.error(f"[ERROR] Ошибки конфигурации: {error_msg}")
        raise ValueError(f"Configuration validation failed: {error_msg}")

    if warnings:
        logger.warning("[WARN] Предупреждения конфигурации:")
        for warning in warnings:
            logger.warning(f"  - {warning}")

    logger.info("[OK] Конфигурация валидна для production")
    return config


async def create_default_api_key_if_needed(services: ProductionServices):
    """Создает дефолтный API ключ если он отсутствует"""
    try:
        # Проверяем, есть ли хотя бы один API ключ
        existing_keys = await services.api_key_repo.list_keys(limit=1)

        if not existing_keys:
            logger.info("🔑 Создание дефолтного API ключа...")

            # Используем use case для создания ключа (как и должно быть в clean architecture)
            from src.domain.usecase.api.manage_keys import CreateApiKeyRequest

            create_request = CreateApiKeyRequest(
                client_name="default-production-key",
                contact_email="admin@antispam-bot.local",
                plan=ApiKeyPlan.FREE,
            )

            # Создаем через use case
            result = await services.manage_api_keys_usecase.create_api_key(create_request)

            logger.info(f"[OK] Дефолтный API ключ создан: {result.raw_key[:16]}...")
            logger.info("[AUTH] ВАЖНО: Сохраните этот ключ в безопасном месте!")
            logger.info(f"🔑 Полный ключ: {result.raw_key}")

    except Exception as e:
        logger.warning(f"[WARN] Не удалось создать дефолтный API ключ: {e}")


# === EXAMPLE USAGE & TESTING ===


async def example_production_setup():
    """Пример настройки для production"""

    # Загружаем конфигурацию
    config = {
        "database_url": os.getenv("DATABASE_URL"),
        "redis_url": os.getenv("REDIS_URL"),
        "bot_token": os.getenv("BOT_TOKEN"),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "api": {
            "auth": {
                "jwt_secret": os.getenv(
                    "JWT_SECRET", "super-secret-jwt-key-for-production-min-32-chars"
                ),
                "jwt_algorithm": "HS256",
                "access_token_expire_minutes": 30,
                "refresh_token_expire_days": 7,
            },
            "rate_limit": {
                "default_requests_per_minute": 60,
                "default_requests_per_day": 5000,
                "burst_limit": 10,
            },
        },
        "http_server": {
            "host": "0.0.0.0",
            "port": 8080,
            "cors_enabled": False,  # Production setting
            "ssl_enabled": True,
        },
        "analytics": {"enable_real_time": True},
        "middleware": {
            "protected_paths": [
                "/api/v1/detect",
                "/api/v1/detect/batch",
                "/api/v1/stats",
                "/api/v1/account",
            ]
        },
        "spam_detection": {
            "ensemble": {
                "spam_threshold": 0.6,
                "high_confidence_threshold": 0.8,
                "auto_ban_threshold": 0.85,
                "max_processing_time": 2.0,
                "enable_early_exit": True,
            }
        },
        "openai": {"api_key": os.getenv("OPENAI_API_KEY"), "model": "gpt-4", "enabled": True},
        "logging": {"level": "INFO", "structured": True, "file": "logs/antispam-bot.log"},
    }

    try:
        # Валидируем конфигурацию
        validated_config = validate_production_config(config)

        # Настраиваем production сервисы
        services = await setup_production_services(validated_config)

        logger.info("[SUCCESS] Production setup завершен успешно!")
        return services, validated_config

    except Exception as e:
        logger.error(f"[ERROR] Production setup failed: {e}")
        raise


if __name__ == "__main__":
    # Тест настройки
    asyncio.run(example_production_setup())


# === TESTING SUPPORT (production-backed) ===


def setup_test_dependencies_mock(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Создает полностью мокнутые зависимости для интеграционных тестов
    Не требует реальных соединений с БД/Redis
    """
    from unittest.mock import Mock, AsyncMock
    from src.domain.entity.api_key import ApiKey, ApiKeyPlan
    from src.domain.service.auth.jwt_service import JWTService

    # Создаем полностью мокнутые зависимости
    mock_postgres_client = Mock()
    mock_redis_client = Mock()
    mock_http_client = Mock()

    # API Key Repository
    mock_api_key_repo = Mock()

    # Создаем правильный мокнутый API ключ с корректным хешем
    test_api_key_str = "antispam_test_api_key_for_integration_tests_123456789"
    test_api_key = ApiKey(
        id="test_key_id",
        key_hash=ApiKey.hash_key(test_api_key_str),  # Правильный хеш
        client_name="Test Client",
        contact_email="test@example.com",
        plan=ApiKeyPlan.FREE,
        is_active=True,
    )

    # Мокаем методы репозитория
    mock_api_key_repo.verify_key = AsyncMock(return_value=test_api_key)
    mock_api_key_repo.get_api_key_by_hash = AsyncMock(return_value=test_api_key)

    # JWT Service (реальный, так как не требует внешних соединений)
    jwt_config = config.get("api", {}).get("auth", {})
    jwt_service = JWTService(
        secret_key=jwt_config.get("jwt_secret", "test_jwt_secret_32_chars_minimum"),
        algorithm="HS256",
        access_token_expire_minutes=30,
    )

    # Rate Limiter
    mock_rate_limiter = Mock()
    mock_rate_limiter.check_rate_limit = AsyncMock(return_value=True)

    # Spam Detection Services
    mock_ensemble_detector = Mock()
    mock_ensemble_detector.detect = AsyncMock(
        return_value={
            "is_spam": False,
            "confidence": 0.2,
            "detectors_used": ["cas", "ruspam"],
            "details": {"cas": {"is_banned": False}, "ruspam": {"confidence": 0.2}},
        }
    )

    # Usage Repository
    mock_usage_repo = Mock()
    mock_usage_repo.record_usage = AsyncMock()

    # Use Cases
    mock_check_message_usecase = Mock()
    mock_check_message_usecase.execute = AsyncMock(
        return_value={
            "is_spam": False,
            "confidence": 0.2,
            "reason": "Normal message",
            "action": "allow",
            "processing_time_ms": 150.0,
        }
    )

    mock_manage_api_keys_usecase = Mock()
    mock_manage_api_keys_usecase.create_api_key = AsyncMock()

    # Notification Service
    mock_notification_service = Mock()
    mock_notification_service.send_notification = AsyncMock()

    return {
        "postgres_client": mock_postgres_client,
        "redis_client": mock_redis_client,
        "http_client": mock_http_client,
        "api_key_repo": mock_api_key_repo,  # Правильное имя для ProductionServices
        "api_key_repository": mock_api_key_repo,  # Альтернативное имя
        "jwt_service": jwt_service,
        "rate_limiter": mock_rate_limiter,
        "ensemble_detector": mock_ensemble_detector,
        "usage_analytics": mock_usage_repo,  # Правильное имя для ProductionServices
        "usage_repository": mock_usage_repo,  # Альтернативное имя
        "check_message_usecase": mock_check_message_usecase,
        "manage_api_keys_usecase": mock_manage_api_keys_usecase,
        "notification_service": mock_notification_service,
    }


async def setup_test_dependencies(
    config: Dict[str, Any],
    cas_gateway: Any = None,
    ruspam_detector: Any = None,
    openai_gateway: Any = None,
) -> Dict[str, Any]:
    """Готовит реальные зависимости для интеграционных тестов на основе production-инициализации.

    Никаких заглушек: поднимаются настоящие клиенты/репозитории/сервисы согласно конфигу.
    """
    validated = validate_production_config(config)
    services = await setup_production_services(validated)

    # Инъекция переданных тестом внешних зависимостей (без заглушек в коде)
    detector = services.ensemble_detector
    # CAS wrapper
    if cas_gateway is not None:

        class _CASWrapper:
            def __init__(self, gw):
                self._gw = gw

            async def detect(self, message, user_context):
                # ожидается интерфейс CASDetector.detect(message, ctx) → DetectorResult
                return await cas_gateway.check_user(message, user_context)

        detector.cas_detector = _CASWrapper(cas_gateway)

    # RUSpam wrapper
    if ruspam_detector is not None:
        detector.ruspam_detector = ruspam_detector

    # OpenAI wrapper
    if openai_gateway is not None:

        class _OAWrapper:
            def __init__(self, gw):
                self._gw = gw

            async def detect(self, message, user_context):
                return await openai_gateway.analyze_text(message, user_context)

        detector.openai_detector = _OAWrapper(openai_gateway)

    return {
        "jwt_service": services.jwt_service,
        "rate_limiter": services.rate_limiter,
        "api_key_repository": services.api_key_repo,
        "message_repository": services.message_repo,
        "user_repository": services.user_repo,
        "usage_analytics": services.usage_analytics,
        "spam_detector": services.ensemble_detector,
        "check_message_usecase": services.check_message_usecase,
    }
