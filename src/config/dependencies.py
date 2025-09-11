# src/config/dependencies.py
"""
Production-ready Dependency Injection Setup
Связывает все компоненты в единую систему
"""

import os
import asyncio
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# Core imports - добавлены отсутствующие imports
from ..domain.service.auth.jwt_service import JWTService, create_jwt_service
from ..domain.service.rate_limit.rate_limiter import RateLimiter, create_rate_limiter
from ..domain.service.analytics.usage_analytics import UsageAnalytics, create_usage_analytics
from ..delivery.http.middleware.api_auth import ApiAuthMiddleware, create_api_auth_middleware

# Repositories
from ..adapter.repository.api_key_repository import ApiKeyRepository
from ..adapter.repository.usage_repository import UsageRepository
from ..adapter.repository.user_repository import UserRepository
from ..adapter.repository.message_repository import MessageRepository
from ..adapter.repository.spam_samples_repository import SpamSamplesRepository

# Use Cases
from ..domain.usecase.api.manage_keys import ManageApiKeysUseCase
from ..domain.usecase.spam_detection.check_message import CheckMessageUseCase
from ..domain.usecase.admin.ban_user import BanUserUseCase

# Infrastructure
from ..lib.clients.redis_client import RedisClient
from ..lib.clients.postgres_client import PostgresClient
from ..lib.clients.http_client import HttpClient

# Gateways
from ..adapter.gateway.cas_gateway import CASGateway
from ..adapter.gateway.openai_gateway import OpenAIGateway

# Domain Services
from ..domain.service.detector.ensemble import EnsembleDetector
from ..domain.service.cache.redis_cache import RedisCache
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
    api_auth_middleware: Any  # Factory function
    
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
    redis_client: Optional[RedisClient]
    http_client: HttpClient
    
    def health_check(self) -> Dict[str, Any]:
        """Комплексная проверка здоровья всей системы"""
        try:
            health_info = {
                "status": "healthy",
                "services": {},
                "timestamp": time.time(),
                "version": "2.0.0"
            }
            
            # JWT Service
            try:
                health_info["services"]["jwt_service"] = self.jwt_service.health_check()
            except Exception as e:
                health_info["services"]["jwt_service"] = {"status": "error", "error": str(e)}
            
            # Rate Limiter
            try:
                health_info["services"]["rate_limiter"] = self.rate_limiter.health_check()
            except Exception as e:
                health_info["services"]["rate_limiter"] = {"status": "error", "error": str(e)}
            
            # Usage Analytics
            try:
                health_info["services"]["usage_analytics"] = self.usage_analytics.health_check()
            except Exception as e:
                health_info["services"]["usage_analytics"] = {"status": "error", "error": str(e)}
            
            # Database
            try:
                if hasattr(self.postgres_client, 'health_check'):
                    health_info["services"]["postgres"] = self.postgres_client.health_check()
                else:
                    health_info["services"]["postgres"] = {"status": "unknown", "method": "not_implemented"}
            except Exception as e:
                health_info["services"]["postgres"] = {"status": "error", "error": str(e)}
            
            # Redis
            try:
                if self.redis_client and hasattr(self.redis_client, 'health_check'):
                    health_info["services"]["redis"] = self.redis_client.health_check()
                else:
                    health_info["services"]["redis"] = {"status": "not_configured"}
            except Exception as e:
                health_info["services"]["redis"] = {"status": "error", "error": str(e)}
            
            # Ensemble Detector
            try:
                health_info["services"]["ensemble_detector"] = await self.ensemble_detector.health_check()
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
                    health_info["services"]["openai_gateway"] = await self.openai_gateway.health_check()
                else:
                    health_info["services"]["openai_gateway"] = {"status": "not_configured"}
            except Exception as e:
                health_info["services"]["openai_gateway"] = {"status": "error", "error": str(e)}
            
            # Определяем общий статус
            error_count = sum(1 for s in health_info["services"].values() 
                            if isinstance(s, dict) and s.get("status") == "error")
            
            if error_count == 0:
                health_info["status"] = "healthy"
            elif error_count <= 2:  # Допускаем некоторые деградации
                health_info["status"] = "degraded"
            else:
                health_info["status"] = "unhealthy"
            
            return health_info
            
        except Exception as e:
            logger.error(f"Health check critical error: {e}")
            return {
                "status": "error",
                "timestamp": time.time(),
                "error": str(e)
            }


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
    logger.info("🚀 Настройка production сервисов...")
    
    critical_errors = []
    warnings = []
    
    # === INFRASTRUCTURE CLIENTS ===
    logger.info("📦 Настройка клиентов инфраструктуры...")
    
    # PostgreSQL Client (КРИТИЧЕСКИЙ)
    postgres_client = None
    try:
        database_url = config.get("database_url") or config.get("database", {}).get("url")
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        
        postgres_client = PostgresClient(database_url)
        await postgres_client.connect()
        logger.info("✅ PostgreSQL подключен")
    except Exception as e:
        critical_errors.append(f"PostgreSQL connection failed: {e}")
        logger.error(f"❌ PostgreSQL ошибка: {e}")
    
    # Redis Client (НЕ критический)
    redis_client = None
    try:
        redis_url = config.get("redis_url") or config.get("redis", {}).get("url")
        if redis_url:
            redis_client = RedisClient(redis_url)
            await redis_client.connect()
            logger.info("✅ Redis подключен")
        else:
            warnings.append("Redis не настроен - некоторые функции будут работать в fallback режиме")
            logger.warning("⚠️ Redis не настроен")
    except Exception as e:
        warnings.append(f"Redis недоступен: {e}")
        logger.warning(f"⚠️ Redis ошибка: {e}")
    
    # HTTP Client
    http_client = HttpClient(
        timeout=config.get("http_client", {}).get("timeout", 30),
        max_retries=config.get("http_client", {}).get("max_retries", 3)
    )
    logger.info("✅ HTTP клиент настроен")
    
    # Прерываем если критические ошибки
    if critical_errors:
        error_msg = "; ".join(critical_errors)
        logger.error(f"❌ Критические ошибки инициализации: {error_msg}")
        raise RuntimeError(f"Critical services failed: {error_msg}")
    
    # === REPOSITORIES ===
    logger.info("🗄️ Настройка репозиториев...")
    
    try:
        api_key_repo = ApiKeyRepository(postgres_client)
        usage_repo = UsageRepository(postgres_client)
        user_repo = UserRepository(postgres_client)
        message_repo = MessageRepository(postgres_client)
        spam_samples_repo = SpamSamplesRepository(postgres_client)
        
        logger.info("✅ Репозитории настроены")
    except Exception as e:
        raise RuntimeError(f"Repository initialization failed: {e}")
    
    # === CACHE LAYER ===
    redis_cache = None
    if redis_client:
        try:
            redis_cache = RedisCache(redis_client)
            logger.info("✅ Redis кэш настроен")
        except Exception as e:
            warnings.append(f"Redis cache initialization failed: {e}")
            logger.warning(f"⚠️ Redis cache ошибка: {e}")
    
    # === GATEWAYS ===
    logger.info("🌐 Настройка внешних gateways...")
    
    # CAS Gateway
    cas_gateway = None
    try:
        cas_gateway = CASGateway(
            http_client=http_client,
            cache=redis_cache,
            config=config.get("external_apis", {}).get("cas", {})
        )
        logger.info("✅ CAS Gateway настроен")
    except Exception as e:
        warnings.append(f"CAS Gateway initialization failed: {e}")
        logger.warning(f"⚠️ CAS Gateway ошибка: {e}")
    
    # OpenAI Gateway
    openai_gateway = None
    try:
        openai_config = config.get("openai", {})
        if openai_config.get("api_key") and openai_config.get("enabled", True):
            openai_gateway = OpenAIGateway(
                http_client=http_client,
                config=openai_config
            )
            logger.info("✅ OpenAI Gateway настроен")
        else:
            warnings.append("OpenAI не настроен - спам детекция будет работать без LLM анализа")
            logger.warning("⚠️ OpenAI не настроен")
    except Exception as e:
        warnings.append(f"OpenAI Gateway initialization failed: {e}")
        logger.warning(f"⚠️ OpenAI Gateway ошибка: {e}")
    
    # === CORE SERVICES ===
    logger.info("⚙️ Настройка core сервисов...")
    
    # JWT Service
    try:
        jwt_service = create_jwt_service(config.get("api", {}).get("auth", {}))
        logger.info("✅ JWT Service настроен")
    except Exception as e:
        raise RuntimeError(f"JWT Service initialization failed: {e}")
    
    # Rate Limiter
    try:
        rate_limiter = create_rate_limiter(
            redis_client=redis_client,
            config=config.get("api", {}).get("rate_limit", {})
        )
        logger.info("✅ Rate Limiter настроен")
    except Exception as e:
        raise RuntimeError(f"Rate Limiter initialization failed: {e}")
    
    # Usage Analytics
    try:
        usage_analytics = create_usage_analytics(
            usage_repo=usage_repo,
            redis_client=redis_client,
            config=config.get("analytics", {})
        )
        logger.info("✅ Usage Analytics настроен")
    except Exception as e:
        warnings.append(f"Usage Analytics initialization failed: {e}")
        logger.warning(f"⚠️ Usage Analytics ошибка: {e}")
        # Создаем фиктивный analytics для продолжения работы
        usage_analytics = None
    
    # === SPAM DETECTION SETUP ===
    logger.info("🎯 Настройка spam detection...")
    
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
        
        logger.info("✅ Ensemble Detector настроен")
    except Exception as e:
        raise RuntimeError(f"Ensemble Detector initialization failed: {e}")
    
    # === USE CASES ===
    logger.info("📋 Настройка use cases...")
    
    try:
        manage_api_keys_usecase = ManageApiKeysUseCase(
            api_key_repo=api_key_repo,
            usage_repo=usage_repo
        )
        
        check_message_usecase = CheckMessageUseCase(
            detector=ensemble_detector,
            message_repo=message_repo,
            user_repo=user_repo,
            cache=redis_cache
        )
        
        ban_user_usecase = BanUserUseCase(
            user_repo=user_repo,
            message_repo=message_repo
        )
        
        logger.info("✅ Use cases настроены")
    except Exception as e:
        raise RuntimeError(f"Use cases initialization failed: {e}")
    
    # === MIDDLEWARE FACTORIES ===
    logger.info("🔒 Настройка middleware...")
    
    try:
        api_auth_middleware_factory = create_api_auth_middleware(
            jwt_service=jwt_service,
            rate_limiter=rate_limiter,
            api_key_repo=api_key_repo,
            config=config.get("middleware", {})
        )
        logger.info("✅ Middleware настроен")
    except Exception as e:
        raise RuntimeError(f"Middleware initialization failed: {e}")
    
    # === СОЗДАЕМ КОНТЕЙНЕР СЕРВИСОВ ===
    try:
        services = ProductionServices(
            # Authentication & Authorization
            jwt_service=jwt_service,
            rate_limiter=rate_limiter,
            api_auth_middleware=api_auth_middleware_factory,
            
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
            http_client=http_client
        )
        
        logger.info("✅ Контейнер сервисов создан")
    except Exception as e:
        raise RuntimeError(f"Services container creation failed: {e}")
    
    # === ФИНАЛЬНАЯ ПРОВЕРКА ===
    logger.info("🔍 Проверка готовности системы...")
    
    try:
        health = services.health_check()
        
        if health["status"] == "healthy":
            logger.info("✅ Все production сервисы готовы!")
            logger.info("📊 Статус компонентов:")
            for service_name, service_health in health["services"].items():
                status_emoji = "✅" if service_health.get("status") == "healthy" else "⚠️"
                logger.info(f"   {status_emoji} {service_name}: {service_health.get('status', 'unknown')}")
        elif health["status"] == "degraded":
            logger.warning("⚠️ Система работает в деградированном режиме")
            logger.warning("📊 Статус компонентов:")
            for service_name, service_health in health["services"].items():
                if service_health.get("status") != "healthy":
                    logger.warning(f"   ⚠️ {service_name}: {service_health.get('status')} - {service_health.get('error', '')}")
        else:
            error_msg = f"System health check failed: {health.get('error')}"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        raise RuntimeError(f"Health check failed: {e}")
    
    # Выводим предупреждения
    if warnings:
        logger.warning("⚠️ Предупреждения инициализации:")
        for warning in warnings:
            logger.warning(f"  - {warning}")
    
    # Создаем дефолтный API ключ если нужно
    try:
        await create_default_api_key_if_needed(services)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось создать дефолтный API ключ: {e}")
    
    logger.info("🎉 Production services setup завершен!")
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
    logger.info("🔌 Интеграция с FastAPI...")
    
    # === MIDDLEWARE ===
    # Добавляем API Auth Middleware
    try:
        # ВАЖНО: middleware добавляется через фабрику
        middleware_instance = services.api_auth_middleware(app)
        logger.info("✅ API Auth Middleware добавлен")
    except Exception as e:
        logger.error(f"❌ Ошибка добавления middleware: {e}")
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
    
    logger.info("✅ Dependency injection настроен")
    
    # === STARTUP/SHUTDOWN HOOKS ===
    @app.on_event("startup")
    async def startup_event():
        logger.info("🚀 FastAPI приложение запущено")
        logger.info("📊 Production services активны")
        
        # Финальная проверка
        health = services.health_check()
        if health["status"] not in ["healthy", "degraded"]:
            logger.error(f"❌ System не готова: {health}")
            raise RuntimeError("System health check failed on startup")
    
    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("🛑 Завершение работы FastAPI...")
        
        # Graceful shutdown уже обрабатывается в main shutdown_application
        logger.info("✅ FastAPI shutdown hooks выполнены")
    
    logger.info("✅ FastAPI интеграция завершена")


# === HELPER FUNCTIONS FOR ROUTES ===

def get_dependencies_for_routes():
    """Возвращает dependencies для использования в FastAPI routes"""
    from fastapi import Depends, Request
    
    def get_services(request: Request) -> ProductionServices:
        """Получить production services из request"""
        if not hasattr(request.app.state, 'production_services'):
            raise HTTPException(
                status_code=500, 
                detail="Production services not initialized"
            )
        return request.app.state.production_services
    
    def get_jwt_service(services: ProductionServices = Depends(get_services)) -> JWTService:
        return services.jwt_service
    
    def get_usage_analytics(services: ProductionServices = Depends(get_services)) -> UsageAnalytics:
        if not services.usage_analytics:
            raise HTTPException(
                status_code=503,
                detail="Usage analytics service not available"
            )
        return services.usage_analytics
    
    def get_api_key_repo(services: ProductionServices = Depends(get_services)) -> ApiKeyRepository:
        return services.api_key_repo
    
    def get_manage_api_keys_usecase(services: ProductionServices = Depends(get_services)) -> ManageApiKeysUseCase:
        return services.manage_api_keys_usecase
    
    def get_check_message_usecase(services: ProductionServices = Depends(get_services)) -> CheckMessageUseCase:
        return services.check_message_usecase
    
    def get_ensemble_detector(services: ProductionServices = Depends(get_services)) -> EnsembleDetector:
        return services.ensemble_detector
    
    return {
        "get_services": get_services,
        "get_jwt_service": get_jwt_service,
        "get_usage_analytics": get_usage_analytics,
        "get_api_key_repo": get_api_key_repo,
        "get_manage_api_keys_usecase": get_manage_api_keys_usecase,
        "get_check_message_usecase": get_check_message_usecase,
        "get_ensemble_detector": get_ensemble_detector
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
    logger.info("🔍 Валидация production конфигурации...")
    
    errors = []
    warnings = []
    
    # === ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ ===
    required_keys = [
        "database_url",
        "bot_token"
    ]
    
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
    jwt_config = config.get("api", {}).get("auth", {})
    jwt_secret = jwt_config.get("jwt_secret")
    
    if not jwt_secret:
        errors.append("JWT_SECRET обязателен для production")
    elif len(jwt_secret) < 32:
        errors.append("JWT_SECRET должен быть минимум 32 символа")
    
    # === SECURITY VALIDATION ===
    environment = config.get("environment", os.getenv("ENVIRONMENT", "development"))
    
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
        warnings.append(f"Высокий лимит запросов ({default_rpm}/min) - проверьте производительность")
    elif default_rpm < 10:
        warnings.append(f"Низкий лимит запросов ({default_rpm}/min) - может блокировать легитимных пользователей")
    
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
        logger.error(f"❌ Ошибки конфигурации: {error_msg}")
        raise ValueError(f"Configuration validation failed: {error_msg}")
    
    if warnings:
        logger.warning("⚠️ Предупреждения конфигурации:")
        for warning in warnings:
            logger.warning(f"  - {warning}")
    
    logger.info("✅ Конфигурация валидна для production")
    return config


async def create_default_api_key_if_needed(services: ProductionServices):
    """Создает дефолтный API ключ если он отсутствует"""
    try:
        # Проверяем, есть ли хотя бы один API ключ
        existing_keys = await services.api_key_repo.list_keys(limit=1)
        
        if not existing_keys:
            logger.info("🔑 Создание дефолтного API ключа...")
            
            # Создаем API ключ
            api_key = ApiKey.create_new(
                name="default-production-key",
                plan=ApiKeyPlan.BASIC,
                description="Auto-generated default API key for production"
            )
            
            # Сохраняем в базе
            await services.api_key_repo.create(api_key)
            
            logger.info(f"✅ Дефолтный API ключ создан: {api_key.key[:8]}...")
            logger.info("🔐 ВАЖНО: Сохраните этот ключ в безопасном месте!")
            
    except Exception as e:
        logger.warning(f"⚠️ Не удалось создать дефолтный API ключ: {e}")


# === EXAMPLE USAGE & TESTING ===

async def example_production_setup():
    """Пример настройки для production"""
    
    # Загружаем конфигурацию
    config = {
        "database_url": os.getenv("DATABASE_URL", "postgresql://antispam_user:StrongPassword123!@localhost:5432/antispam_bot"),
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "bot_token": os.getenv("BOT_TOKEN"),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "api": {
            "auth": {
                "jwt_secret": os.getenv("JWT_SECRET", "super-secret-jwt-key-for-production-min-32-chars"),
                "jwt_algorithm": "HS256",
                "access_token_expire_minutes": 30,
                "refresh_token_expire_days": 7
            },
            "rate_limit": {
                "default_requests_per_minute": 60,
                "default_requests_per_day": 5000,
                "burst_limit": 10
            }
        },
        "http_server": {
            "host": "0.0.0.0",
            "port": 8080,
            "cors_enabled": False,  # Production setting
            "ssl_enabled": True
        },
        "analytics": {
            "enable_real_time": True
        },
        "middleware": {
            "protected_paths": [
                "/api/v1/detect",
                "/api/v1/detect/batch",
                "/api/v1/stats",
                "/api/v1/account"
            ]
        },
        "spam_detection": {
            "ensemble": {
                "spam_threshold": 0.6,
                "high_confidence_threshold": 0.8,
                "auto_ban_threshold": 0.85,
                "max_processing_time": 2.0,
                "enable_early_exit": True
            }
        },
        "openai": {
            "api_key": os.getenv("OPENAI_API_KEY"),
            "model": "gpt-4",
            "enabled": True
        },
        "logging": {
            "level": "INFO",
            "structured": True,
            "file": "logs/antispam-bot.log"
        }
    }
    
    try:
        # Валидируем конфигурацию
        validated_config = validate_production_config(config)
        
        # Настраиваем production сервисы
        services = await setup_production_services(validated_config)
        
        logger.info("🎉 Production setup завершен успешно!")
        return services, validated_config
        
    except Exception as e:
        logger.error(f"❌ Production setup failed: {e}")
        raise


if __name__ == "__main__":
    # Тест настройки
    asyncio.run(example_production_setup())
