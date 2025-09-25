# src/config/dependencies.py
"""
Production-ready Dependency Injection Setup для Telegram бота
Связывает все компоненты в единую систему
"""

import os
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from fastapi import HTTPException

# Repositories
from ..adapter.repository.user_repository import UserRepository
from ..adapter.repository.message_repository import MessageRepository
from ..adapter.repository.spam_samples_repository import SpamSamplesRepository
from ..adapter.repository.chat_repository import ChatRepository

# Use Cases
from ..domain.usecase.spam_detection.check_message import CheckMessageUseCase
from ..domain.usecase.spam_detection.ban_user import BanUserUseCase

# Infrastructure
from ..lib.clients.postgres_client import PostgresClient
from ..lib.clients.http_client import HttpClient

# Gateways
from ..adapter.gateway.cas_gateway import CASGateway
from ..adapter.gateway.bothub_gateway import BotHubGateway
from ..adapter.gateway.telegram_chat_gateway import TelegramChatGateway

# Domain Services
from ..domain.service.detector.ensemble import EnsembleDetector
from ..adapter.cache.redis_cache import RedisCache
from ..domain.service.monitoring.prometheus_metrics import create_prometheus_metrics

logger = logging.getLogger(__name__)


@dataclass
class ProductionServices:
    """Контейнер для всех production сервисов - только Telegram бот"""

    # Repositories
    user_repo: UserRepository
    message_repo: MessageRepository
    spam_samples_repo: SpamSamplesRepository
    chat_repo: ChatRepository

    # Use Cases
    check_message_usecase: CheckMessageUseCase
    ban_user_usecase: BanUserUseCase

    # Domain Services
    ensemble_detector: EnsembleDetector
    redis_cache: Optional[RedisCache]

    # Gateways
    cas_gateway: Optional[CASGateway]
    bothub_gateway: Optional[BotHubGateway]
    telegram_chat_gateway: Optional[TelegramChatGateway]

    # Infrastructure
    postgres_client: PostgresClient
    redis_client: Optional[Any]
    http_client: HttpClient

    async def health_check(self) -> Dict[str, Any]:
        """Комплексная проверка здоровья Telegram бота"""
        try:
            health_info = {
                "status": "healthy",
                "services": {},
                "timestamp": time.time(),
                "version": "2.0.0",
            }

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
                if self.bothub_gateway:
                    health_info["services"][
                        "bothub_gateway"
                    ] = await self.bothub_gateway.health_check()
                else:
                    health_info["services"]["bothub_gateway"] = {"status": "not_configured"}
            except Exception as e:
                health_info["services"]["bothub_gateway"] = {"status": "error", "error": str(e)}

            # Определяем общий статус
            error_count = sum(
                1 for service in health_info["services"].values()
                if service.get("status") == "error"
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
    Настраивает все production сервисы для Telegram бота

    Args:
        config: Конфигурация приложения

    Returns:
        ProductionServices со всеми настроенными компонентами

    Raises:
        RuntimeError: Если критические сервисы не удалось инициализировать
    """
    logger.info("[START] Настройка production сервисов для Telegram бота...")

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

    # HTTP Client
    http_client = None
    try:
        http_client = HttpClient()
        logger.info("[OK] HTTP Client настроен")
    except Exception as e:
        critical_errors.append(f"HTTP Client initialization failed: {e}")
        logger.error(f"[ERROR] HTTP Client ошибка: {e}")

    # Проверяем критические ошибки
    if critical_errors:
        error_msg = "; ".join(critical_errors)
        logger.error(f"[ERROR] Критические ошибки инициализации: {error_msg}")
        raise RuntimeError(f"Critical services failed: {error_msg}")

    # === REPOSITORIES ===
    logger.info("🗄️ Настройка репозиториев...")

    try:
        user_repo = UserRepository(postgres_client)
        message_repo = MessageRepository(postgres_client)
        spam_samples_repo = SpamSamplesRepository(postgres_client)
        chat_repo = ChatRepository(postgres_client)

        logger.info("[OK] Репозитории настроены")
    except Exception as e:
        raise RuntimeError(f"Repository initialization failed: {e}")

    # === CACHE LAYER ===
    redis_cache = redis_client  # redis_client уже является RedisCache
    if redis_cache:
        logger.info("[OK] Redis Cache настроен")

    # === GATEWAYS ===
    logger.info("🌐 Настройка gateways...")

    # CAS Gateway
    cas_gateway = None
    try:
        cas_config = config.get("external_apis", {}).get("cas", {})
        if cas_config.get("enabled", True):
            cas_gateway = CASGateway(
                http_client=http_client,
                cache=redis_cache,
                config=cas_config,
            )
            logger.info("[OK] CAS Gateway настроен")
        else:
            logger.info("[SKIP] CAS Gateway отключен в конфигурации")
    except Exception as e:
        warnings.append(f"CAS Gateway initialization failed: {e}")
        logger.warning(f"[WARN] CAS Gateway ошибка: {e}")

    # BotHub Gateway (новый провайдер)
    bothub_gateway = None
    try:
        bothub_config = config.get("bothub", {})
        # BotHub Gateway будет создаваться динамически с токеном пользователя
        logger.info("[OK] BotHub Gateway готов к использованию")
    except Exception as e:
        warnings.append(f"BotHub Gateway initialization failed: {e}")
        logger.warning(f"[WARN] BotHub Gateway ошибка: {e}")

    # === SPAM DETECTION SETUP ===
    logger.info("[TARGET] Настройка spam detection...")

    # Ensemble Detector
    try:
        detector_config = config.get("spam_detection", {}).get("ensemble", {})
        ensemble_detector = EnsembleDetector(detector_config)

        # Добавляем CAS детектор
        if cas_gateway:
            ensemble_detector.add_cas_detector(cas_gateway)

        # Добавляем RUSpam детектор (критический компонент)
        ensemble_detector.add_ruspam_detector()

        # BotHub детектор будет создаваться динамически с токеном пользователя
        # ensemble_detector.add_bothub_detector(bothub_gateway) - вызывается при необходимости

        logger.info("[OK] Ensemble Detector настроен")
    except Exception as e:
        raise RuntimeError(f"Ensemble Detector initialization failed: {e}")

    # === USE CASES ===
    logger.info("[LIST] Настройка use cases...")

    try:
        check_message_usecase = CheckMessageUseCase(
            spam_detector=ensemble_detector,
            message_repo=message_repo,
            user_repo=user_repo,
            spam_threshold=0.6,
            max_daily_spam=3,  # Максимум 3 спама в день перед баном
        )

        # BanUserUseCase требует TelegramGateway, который создается в bot.py
        # Поэтому создаем его позже с None
        ban_user_usecase = BanUserUseCase(
            user_repo=user_repo, 
            message_repo=message_repo, 
            telegram_gateway=None  # Будет установлен в bot.py
        )

        logger.info("[OK] Use cases настроены")
    except Exception as e:
        raise RuntimeError(f"Use cases initialization failed: {e}")

    # === СОЗДАЕМ КОНТЕЙНЕР СЕРВИСОВ ===
    try:
        services = ProductionServices(
            # Repositories
            user_repo=user_repo,
            message_repo=message_repo,
            spam_samples_repo=spam_samples_repo,
            chat_repo=chat_repo,
            # Use Cases
            check_message_usecase=check_message_usecase,
            ban_user_usecase=ban_user_usecase,
            # Domain Services
            ensemble_detector=ensemble_detector,
            redis_cache=redis_cache,
            # Gateways
            cas_gateway=cas_gateway,
            bothub_gateway=bothub_gateway,
            telegram_chat_gateway=None,  # Будет создан в bot.py
            # Infrastructure
            postgres_client=postgres_client,
            redis_client=redis_client,
            http_client=http_client,
        )

        logger.info("[OK] Production Services контейнер создан")
    except Exception as e:
        raise RuntimeError(f"Production Services container creation failed: {e}")

    # === ФИНАЛЬНАЯ ПРОВЕРКА ===
    if warnings:
        logger.warning(f"[WARN] Предупреждения при инициализации: {'; '.join(warnings)}")

    logger.info("[SUCCESS] Все production сервисы успешно настроены!")
    return services


# === HELPER FUNCTIONS FOR ROUTES ===


def get_dependencies_for_routes():
    """Возвращает dependencies для использования в FastAPI routes"""
    from fastapi import Depends, Request

    def get_services(request: Request) -> ProductionServices:
        """Получить production services из request"""
        if not hasattr(request.app.state, "production_services"):
            raise HTTPException(status_code=500, detail="Production services not initialized")
        return request.app.state.production_services

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
        ValueError: Если конфигурация невалидна
    """
    required_fields = ["database_url"]
    missing_fields = [field for field in required_fields if not config.get(field)]

    if missing_fields:
        raise ValueError(f"Missing required configuration fields: {missing_fields}")

    # Добавляем значения по умолчанию
    default_config = {
        "database": {"url": config.get("database_url")},
        "redis": {"url": config.get("redis_url")},
        "cas": {
            "enabled": True,
            "api_url": "https://api.cas.chat/check",
            "timeout": 5.0,
        },
        "bothub": {
            "model": "gpt-4o-mini",
            "max_tokens": 150,
            "temperature": 0.0,
            "timeout": 10.0,
            "max_retries": 2,
            "retry_delay": 1.0,
        },
        "spam_detection": {
            "ensemble": {
                "spam_threshold": 0.6,
                "auto_ban_threshold": 0.8,
                "max_processing_time": 2.0,
                "cas_enabled": True,
                "ruspam_enabled": True,
                "bothub_min_length": 5,
                "use_bothub_fallback": True,
                "bothub_timeout": 5.0,
                "bothub_min_ruspam_confidence": 0.2,
            }
        },
    }

    # Объединяем с переданной конфигурацией
    for key, value in default_config.items():
        if key not in config:
            config[key] = value
        elif isinstance(value, dict) and isinstance(config[key], dict):
            for sub_key, sub_value in value.items():
                if sub_key not in config[key]:
                    config[key][sub_key] = sub_value

    return config
