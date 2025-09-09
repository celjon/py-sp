# src/config/dependencies.py
"""
Production-ready Dependency Injection Setup
Связывает все компоненты в единую систему
"""

import os
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Core imports
from ..domain.service.auth.jwt_service import JWTService, create_jwt_service
from ..domain.service.rate_limit.rate_limiter import RateLimiter, create_rate_limiter
from ..domain.service.analytics.usage_analytics import UsageAnalytics, create_usage_analytics
from ..delivery.http.middleware.api_auth import ApiAuthMiddleware, create_api_auth_middleware

# Existing imports
from ..adapter.repository.api_key_repository import ApiKeyRepository
from ..adapter.repository.usage_repository import UsageRepository
from ..domain.usecase.api.manage_keys import ManageApiKeysUseCase
from ..lib.clients.redis_client import RedisClient
from ..lib.clients.postgres_client import PostgresClient


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
    
    # Use Cases
    manage_api_keys_usecase: ManageApiKeysUseCase
    
    # Infrastructure
    postgres_client: PostgresClient
    redis_client: Optional[RedisClient]
    
    def health_check(self) -> Dict[str, Any]:
        """Комплексная проверка здоровья всей системы"""
        try:
            return {
                "status": "healthy",
                "services": {
                    "jwt_service": self.jwt_service.health_check(),
                    "rate_limiter": self.rate_limiter.health_check(),
                    "usage_analytics": self.usage_analytics.health_check(),
                    "postgres": self.postgres_client.health_check() if hasattr(self.postgres_client, 'health_check') else {"status": "unknown"},
                    "redis": self.redis_client.health_check() if self.redis_client else {"status": "not_configured"}
                },
                "middleware_status": "configured"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


async def setup_production_services(config: Dict[str, Any]) -> ProductionServices:
    """
    Настраивает все production сервисы
    
    Args:
        config: Конфигурация приложения
        
    Returns:
        ProductionServices со всеми настроенными компонентами
    """
    print("🚀 Настройка production сервисов...")
    
    # === INFRASTRUCTURE CLIENTS ===
    print("📦 Настройка клиентов инфраструктуры...")
    
    # PostgreSQL Client
    postgres_client = PostgresClient(config.get("database_url"))
    await postgres_client.connect()
    print("✅ PostgreSQL подключен")
    
    # Redis Client (опционально)
    redis_client = None
    redis_url = config.get("redis_url")
    if redis_url:
        try:
            redis_client = RedisClient(redis_url)
            await redis_client.connect()
            print("✅ Redis подключен")
        except Exception as e:
            print(f"⚠️ Redis недоступен: {e}")
            print("   Работаем без Redis (fallback режим)")
    
    # === REPOSITORIES ===
    print("🗄️ Настройка репозиториев...")
    
    api_key_repo = ApiKeyRepository(postgres_client)
    usage_repo = UsageRepository(postgres_client)
    
    print("✅ Репозитории настроены")
    
    # === CORE SERVICES ===
    print("⚙️ Настройка core сервисов...")
    
    # JWT Service
    jwt_service = create_jwt_service(config.get("api", {}))
    print("✅ JWT Service настроен")
    
    # Rate Limiter
    rate_limiter = create_rate_limiter(
        redis_client=redis_client,
        config=config.get("rate_limiting", {})
    )
    print("✅ Rate Limiter настроен")
    
    # Usage Analytics
    usage_analytics = create_usage_analytics(
        usage_repo=usage_repo,
        redis_client=redis_client,
        config=config.get("analytics", {})
    )
    print("✅ Usage Analytics настроен")
    
    # === USE CASES ===
    print("📋 Настройка use cases...")
    
    manage_api_keys_usecase = ManageApiKeysUseCase(
        api_key_repo=api_key_repo,
        usage_repo=usage_repo
    )
    print("✅ Use cases настроены")
    
    # === MIDDLEWARE FACTORIES ===
    print("🔒 Настройка middleware...")
    
    api_auth_middleware_factory = create_api_auth_middleware(
        jwt_service=jwt_service,
        rate_limiter=rate_limiter,
        api_key_repo=api_key_repo,
        config=config.get("middleware", {})
    )
    print("✅ Middleware настроен")
    
    # === СОЗДАЕМ КОНТЕЙНЕР СЕРВИСОВ ===
    services = ProductionServices(
        jwt_service=jwt_service,
        rate_limiter=rate_limiter,
        api_auth_middleware=api_auth_middleware_factory,
        usage_analytics=usage_analytics,
        api_key_repo=api_key_repo,
        usage_repo=usage_repo,
        manage_api_keys_usecase=manage_api_keys_usecase,
        postgres_client=postgres_client,
        redis_client=redis_client
    )
    
    # === ФИНАЛЬНАЯ ПРОВЕРКА ===
    print("🔍 Проверка готовности системы...")
    health = services.health_check()
    
    if health["status"] == "healthy":
        print("✅ Все production сервисы готовы!")
        print("📊 Статус компонентов:")
        for service_name, service_health in health["services"].items():
            status_emoji = "✅" if service_health.get("status") == "healthy" else "⚠️"
            print(f"   {status_emoji} {service_name}: {service_health.get('status', 'unknown')}")
    else:
        print(f"❌ Ошибка инициализации: {health.get('error')}")
        raise RuntimeError(f"Failed to initialize production services: {health.get('error')}")
    
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
    print("🔌 Интеграция с FastAPI...")
    
    # === MIDDLEWARE ===
    # Добавляем API Auth Middleware
    app.add_middleware(services.api_auth_middleware)
    print("✅ API Auth Middleware добавлен")
    
    # === DEPENDENCY INJECTION ===
    # Создаем provider для dependency injection
    def get_production_services():
        return services
    
    def get_jwt_service():
        return services.jwt_service
    
    def get_rate_limiter():
        return services.rate_limiter
    
    def get_usage_analytics():
        return services.usage_analytics
    
    def get_api_key_repo():
        return services.api_key_repo
    
    def get_manage_api_keys_usecase():
        return services.manage_api_keys_usecase
    
    # Добавляем в app state для доступа из routes
    app.state.production_services = services
    app.state.get_production_services = get_production_services
    app.state.get_jwt_service = get_jwt_service
    app.state.get_rate_limiter = get_rate_limiter
    app.state.get_usage_analytics = get_usage_analytics
    app.state.get_api_key_repo = get_api_key_repo
    app.state.get_manage_api_keys_usecase = get_manage_api_keys_usecase
    
    print("✅ Dependency injection настроен")
    
    # === STARTUP/SHUTDOWN HOOKS ===
    @app.on_event("startup")
    async def startup_event():
        print("🚀 FastAPI приложение запущено")
        print("📊 Production services активны")
        
        # Опционально: создание дефолтного API ключа
        await create_default_api_key_if_needed(services)
    
    @app.on_event("shutdown")
    async def shutdown_event():
        print("🛑 Завершение работы...")
        
        # Закрываем соединения
        if services.postgres_client:
            await services.postgres_client.disconnect()
            print("✅ PostgreSQL отключен")
        
        if services.redis_client:
            await services.redis_client.disconnect()
            print("✅ Redis отключен")
        
        print("✅ Graceful shutdown завершен")
    
    print("✅ Startup/shutdown hooks настроены")


async def create_default_api_key_if_needed(services: ProductionServices):
    """Создает дефолтный API ключ если нужно"""
    try:
        # Проверяем, есть ли уже API ключи
        existing_keys = await services.api_key_repo.search_api_keys(limit=1)
        
        if existing_keys:
            print(f"ℹ️ Найдено {len(existing_keys)} API ключей")
            return
        
        # Создаем дефолтный ключ
        from ..domain.usecase.api.manage_keys import CreateApiKeyRequest
        from ..domain.entity.api_key import ApiKeyPlan
        
        request = CreateApiKeyRequest(
            client_name="Default Development Client",
            contact_email="dev@antispam.local",
            plan=ApiKeyPlan.BASIC,
            requests_per_minute=120,
            requests_per_day=10000,
            description="Auto-created development API key",
            metadata={
                "created_by": "auto_setup",
                "environment": "development",
                "purpose": "testing"
            }
        )
        
        result = await services.manage_api_keys_usecase.create_api_key(request)
        
        print("🔑 Создан дефолтный API ключ:")
        print(f"   Client: {result.api_key.client_name}")
        print(f"   Plan: {result.api_key.plan.value}")
        print(f"   API Key: {result.raw_key}")
        print(f"   ⚠️ Сохраните этот ключ!")
        
    except Exception as e:
        print(f"⚠️ Не удалось создать дефолтный API ключ: {e}")


# === HELPER FUNCTIONS FOR ROUTES ===

def get_dependencies_for_routes():
    """Возвращает dependencies для использования в FastAPI routes"""
    from fastapi import Depends, Request
    
    def get_services(request: Request) -> ProductionServices:
        return request.app.state.production_services
    
    def get_jwt_service(services: ProductionServices = Depends(get_services)) -> JWTService:
        return services.jwt_service
    
    def get_usage_analytics(services: ProductionServices = Depends(get_services)) -> UsageAnalytics:
        return services.usage_analytics
    
    def get_api_key_repo(services: ProductionServices = Depends(get_services)) -> ApiKeyRepository:
        return services.api_key_repo
    
    def get_manage_api_keys_usecase(services: ProductionServices = Depends(get_services)) -> ManageApiKeysUseCase:
        return services.manage_api_keys_usecase
    
    return {
        "get_services": get_services,
        "get_jwt_service": get_jwt_service,
        "get_usage_analytics": get_usage_analytics,
        "get_api_key_repo": get_api_key_repo,
        "get_manage_api_keys_usecase": get_manage_api_keys_usecase
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
        ValueError: Если конфигурация невалидна
    """
    errors = []
    
    # === ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ ===
    required_fields = [
        "database_url",
        "bot_token"
    ]
    
    for field in required_fields:
        if not config.get(field):
            errors.append(f"Отсутствует обязательный параметр: {field}")
    
    # === ПРОВЕРКА JWT SECRET ===
    jwt_secret = config.get("api", {}).get("auth", {}).get("jwt_secret", "")
    if not jwt_secret or jwt_secret == "dev_secret_change_in_production":
        errors.append("JWT secret не установлен или использует дефолтное значение")
    
    if len(jwt_secret) < 32:
        errors.append("JWT secret должен быть не менее 32 символов")
    
    # === ПРОВЕРКА БЕЗОПАСНОСТИ ===
    if config.get("environment") == "production":
        # В production должны быть более строгие настройки
        api_config = config.get("api", {})
        rate_limits = api_config.get("rate_limit", {})
        
        if rate_limits.get("default_requests_per_minute", 0) > 1000:
            errors.append("Слишком высокий rate limit для production (>1000 RPM)")
        
        # Проверяем CORS
        http_config = config.get("http_server", {})
        if http_config.get("cors_enabled", False):
            errors.append("CORS должен быть отключен в production")
    
    # === ПРЕДУПРЕЖДЕНИЯ ===
    warnings = []
    
    if not config.get("redis_url"):
        warnings.append("Redis не настроен - performance будет снижен")
    
    if not config.get("openai_api_key"):
        warnings.append("OpenAI API key не настроен - детекция спама будет ограничена")
    
    # === РЕЗУЛЬТАТ ===
    if errors:
        error_msg = "Ошибки конфигурации:\n" + "\n".join(f"  - {error}" for error in errors)
        raise ValueError(error_msg)
    
    if warnings:
        print("⚠️ Предупреждения конфигурации:")
        for warning in warnings:
            print(f"  - {warning}")
    
    print("✅ Конфигурация валидна")
    return config


# === EXAMPLE USAGE ===

async def example_production_setup():
    """Пример настройки для production"""
    
    # Загружаем конфигурацию
    config = {
        "database_url": os.getenv("DATABASE_URL"),
        "redis_url": os.getenv("REDIS_URL"),
        "bot_token": os.getenv("BOT_TOKEN"),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "api": {
            "auth": {
                "jwt_secret": os.getenv("JWT_SECRET"),
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
            "cors_enabled": False  # Production setting
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
        }
    }
    
    # Валидируем конфигурацию
    validated_config = validate_production_config(config)
    
    # Настраиваем production сервисы
    services = await setup_production_services(validated_config)
    
    print("🎉 Production setup завершен успешно!")
    return services, validated_config


if __name__ == "__main__":
    # Тест настройки
    asyncio.run(example_production_setup())