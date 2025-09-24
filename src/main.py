# src/main.py
"""
Production-Ready AntiSpam Bot v2.0 Main Application
Полная интеграция всех production компонентов
"""

import os
import sys
import asyncio
import logging
import signal
import traceback
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

# Загружаем переменные окружения из .env файла
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Если python-dotenv не установлен, загружаем вручную
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# Core imports
from .config.config import load_config
from .config.dependencies import (
    setup_production_services,
    validate_production_config,
    ProductionServices,
)

# HTTP routes - API удален, используем только Telegram бот

# Services
from .domain.service.monitoring.prometheus_metrics import (
    PrometheusMetrics,
    MetricsMiddleware,
    create_prometheus_metrics,
)
# ErrorHandler удален

# Bot imports
from .delivery.telegram.bot import AntiSpamBot

# Global state
app_state = {
    "telegram_bot": None,
    "production_services": None,
    "metrics": None,
    "error_handler": None,
    "shutdown_event": asyncio.Event(),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    logger = logging.getLogger(__name__)
    logger.info("[START] Starting AntiSpam Bot v2.0...")

    try:
        # Startup
        await startup_application()
        logger.info("[OK] Application started successfully")

        yield

    except Exception as e:
        logger.error(f"[ERROR] Startup failed: {e}")
        raise
    finally:
        # Shutdown
        logger.info("🛑 Shutting down application...")
        try:
            await shutdown_application()
            logger.info("[OK] Application shutdown complete")
        except Exception as e:
            logger.error(f"[WARN] Shutdown error: {e}")


async def startup_application():
    """Application startup logic"""
    logger = logging.getLogger(__name__)

    try:
        # Загрузка и валидация конфигурации
        config = load_config()
        # Преобразуем Config в плоский словарь для совместимости
        config_dict = config_to_dict(config)
        validated_config = validate_production_config(config_dict)
        logger.info("[OK] Configuration loaded and validated")

        # Настройка логирования
        setup_logging(validated_config)
        logger.info("[OK] Logging configured")

        # Инициализация production сервисов
        production_services = await setup_production_services(validated_config)
        app_state["production_services"] = production_services
        logger.info("[OK] Production services initialized")

        # Инициализация мониторинга
        metrics = create_prometheus_metrics()
        app_state["metrics"] = metrics

        # Запуск Prometheus сервера
        if validated_config.get("metrics", {}).get("enabled", True):
            metrics_port = validated_config.get("metrics", {}).get("prometheus_port", 9090)
            try:
                metrics.start_metrics_server(metrics_port)
                logger.info(f"[OK] Prometheus metrics server started on port {metrics_port}")
            except Exception as e:
                logger.warning(f"[WARN] Failed to start metrics server: {e}")

        # Error handler удален

        # HTTP API components настраиваются при создании приложения
        run_mode = os.getenv("RUN_MODE", "both").lower()
        logger.info(f"[INFO] Running in {run_mode} mode")

        # Запуск Telegram бота
        if run_mode in ("telegram", "both"):
            await start_telegram_bot(validated_config, production_services)
            logger.info("[OK] Telegram bot started")

        logger.info("[SUCCESS] All services initialized successfully!")

    except Exception as e:
        logger.error(f"[ERROR] Startup failed: {e}")
        logger.error(traceback.format_exc())
        raise


async def shutdown_application():
    """Application shutdown logic"""
    logger = logging.getLogger(__name__)

    try:
        # Устанавливаем событие завершения
        app_state["shutdown_event"].set()

        # Останавливаем Telegram бота
        if app_state["telegram_bot"]:
            try:
                await app_state["telegram_bot"].stop()
                logger.info("[OK] Telegram bot stopped")
            except Exception as e:
                logger.error(f"[WARN] Error stopping Telegram bot: {e}")

        # Закрываем production сервисы
        if app_state["production_services"]:
            services = app_state["production_services"]

            # Останавливаем метрики сервер
            if app_state["metrics"]:
                try:
                    app_state["metrics"].stop_metrics_server()
                    logger.info("[OK] Metrics server stopped")
                except Exception as e:
                    logger.warning(f"[WARN] Error stopping metrics server: {e}")

            # Закрываем PostgreSQL
            if services.postgres_client:
                try:
                    await services.postgres_client.disconnect()
                    logger.info("[OK] PostgreSQL disconnected")
                except Exception as e:
                    logger.error(f"[WARN] Error disconnecting PostgreSQL: {e}")

            # Закрываем Redis
            if services.redis_client:
                try:
                    await services.redis_client.disconnect()
                    logger.info("[OK] Redis disconnected")
                except Exception as e:
                    logger.error(f"[WARN] Error disconnecting Redis: {e}")

    except Exception as e:
        logger.error(f"[WARN] Shutdown error: {e}")
        logger.error(traceback.format_exc())


def setup_logging(config: Dict[str, Any]):
    """Настройка системы логирования"""
    log_config = config.get("logging", {})

    # Создаем директорию для логов
    log_file = log_config.get("file", "logs/antispam-bot.log")
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # Настройка обработчиков
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    # Настройка основного логгера
    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO")),
        format=log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        handlers=handlers,
        force=True,  # Перезаписываем существующую конфигурацию
    )

    # Настройка structured logging если включен
    if log_config.get("structured", False):
        try:
            import structlog

            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.PositionalArgumentsFormatter(),
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.JSONRenderer(),
                ],
                wrapper_class=structlog.stdlib.BoundLogger,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )
            print("✅ Structured logging configured")
        except ImportError:
            print("⚠️ structlog not available, using standard logging")


async def start_telegram_bot(config: Dict[str, Any], services: ProductionServices):
    """Запуск Telegram бота"""
    logger = logging.getLogger(__name__)

    try:
        # Получаем токен бота
        bot_token = config.get("bot_token") or config.get("telegram", {}).get("token")
        if not bot_token:
            raise ValueError("BOT_TOKEN is required")

        # Получаем Redis URL
        redis_url = config.get("redis_url") or config.get("redis", {}).get("url")

        # Создаем зависимости для бота - только Telegram компоненты
        bot_dependencies = {
            # Domain Services
            "ensemble_detector": services.ensemble_detector,

            # Repositories
            "user_repository": services.user_repo,
            "message_repository": services.message_repo,
            "spam_samples_repository": services.spam_samples_repo,
            "chat_repository": services.chat_repo,

            # Use Cases
            "check_message_usecase": services.check_message_usecase,
            "ban_user_usecase": services.ban_user_usecase,

            # Infrastructure
            "postgres_client": services.postgres_client,
            "redis_client": services.redis_client,
            "redis_cache": services.redis_cache,

            # Gateways
            "cas_gateway": services.cas_gateway,
            "bothub_gateway": services.bothub_gateway,

            # Configuration
            "config": config,
            "admin_chat_id": config.get("admin_chat_id"),
            "admin_users": config.get("admin_users", []),
        }

        # Создаем бота
        bot = AntiSpamBot(bot_token=bot_token, redis_url=redis_url, dependencies=bot_dependencies)

        # Запускаем бота
        await bot.start_polling()
        app_state["telegram_bot"] = bot

        logger.info("[OK] Telegram bot started successfully")

    except Exception as e:
        logger.error(f"[ERROR] Failed to start Telegram bot: {e}")
        raise


def setup_middleware(
    app: FastAPI, services: ProductionServices, metrics: PrometheusMetrics, error_handler
):
    """Настройка middleware для FastAPI"""

    # CORS middleware (только для development)
    if os.getenv("ENVIRONMENT", "development") == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Metrics middleware
    app.add_middleware(MetricsMiddleware, metrics=metrics)

    # API Auth middleware удален - используем только Telegram бот


def setup_basic_routes(app: FastAPI):
    """Настройка базовых маршрутов при создании приложения"""

    # Health check endpoint
    @app.get("/health", tags=["System"])
    async def health_check():
        """Production health check endpoint"""
        try:
            health_data = {
                "status": "healthy",
                "version": "2.0.0",
                "timestamp": time.time(),
                "components": {},
            }

            # Проверяем production services
            if app_state.get("production_services"):
                try:
                    services_health = await app_state["production_services"].health_check()
                    health_data["components"]["production_services"] = services_health
                except Exception as e:
                    health_data["components"]["production_services"] = {"status": "error", "error": str(e)}

            # Проверяем Telegram bot
            if app_state.get("telegram_bot"):
                try:
                    bot_health = {
                        "status": "healthy" if app_state["telegram_bot"].is_running else "stopped"
                    }
                    health_data["components"]["telegram_bot"] = bot_health
                except Exception as e:
                    health_data["components"]["telegram_bot"] = {"status": "error", "error": str(e)}

            # Проверяем метрики
            if app_state.get("metrics"):
                try:
                    metrics_health = await app_state["metrics"].health_check() if hasattr(app_state["metrics"], "health_check") and callable(app_state["metrics"].health_check) else {"status": "healthy"}
                    health_data["components"]["metrics"] = metrics_health
                except Exception as e:
                    health_data["components"]["metrics"] = {"status": "error", "error": str(e)}

            # Проверяем error handler
            if app_state.get("error_handler"):
                try:
                    error_handler_health = await app_state["error_handler"].health_check() if hasattr(app_state["error_handler"], "health_check") and callable(app_state["error_handler"].health_check) else {"status": "healthy"}
                    health_data["components"]["error_handler"] = error_handler_health
                except Exception as e:
                    health_data["components"]["error_handler"] = {"status": "error", "error": str(e)}

            # Определяем общий статус
            overall_status = "healthy"
            for component_health in health_data["components"].values():
                if isinstance(component_health, dict):
                    if component_health.get("status") == "error":
                        overall_status = "error"
                        break
                    elif component_health.get("status") in ["degraded", "warning"]:
                        overall_status = "degraded"

            health_data["status"] = overall_status

            return health_data

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Health check failed: {e}")
            return JSONResponse(
                status_code=500,
                content={"status": "error", "timestamp": time.time(), "error": str(e)},
            )

    # Metrics endpoint
    @app.get("/metrics", tags=["System"])
    async def get_metrics():
        """Prometheus metrics endpoint"""
        try:
            if app_state.get("metrics"):
                metrics_data = app_state["metrics"].get_metrics()
                return Response(
                    content=metrics_data, media_type="text/plain; version=0.0.4; charset=utf-8"
                )
            else:
                return JSONResponse(status_code=503, content={"error": "Metrics not available"})
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Metrics endpoint failed: {e}")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    print("[ROUTES] Basic routes configured")


def setup_routes(app: FastAPI):
    """Настройка всех маршрутов включая API"""
    # API routes
    # API роуты удалены - используем только Telegram бот

    print("[ROUTES] Full API routes configured")


def config_to_dict(config) -> Dict[str, Any]:
    """Преобразует Config объект в плоский словарь"""
    result = {}

    # Основные параметры из переменных окружения
    result["bot_token"] = os.getenv("BOT_TOKEN")
    result["database_url"] = os.getenv("DATABASE_URL")
    result["redis_url"] = os.getenv("REDIS_URL")
    # OpenRouter удален
    result["admin_chat_id"] = os.getenv("ADMIN_CHAT_ID")
    result["admin_users"] = (
        os.getenv("ADMIN_USERS", "").split(",") if os.getenv("ADMIN_USERS") else []
    )
    result["environment"] = os.getenv("ENVIRONMENT", "development")
    result["log_level"] = os.getenv("LOG_LEVEL", "INFO")
    result["jwt_secret"] = os.getenv("JWT_SECRET")
    result["api_secret"] = os.getenv("API_SECRET_KEY")

    # Если есть конфиг объект, берем из него недостающие параметры
    if hasattr(config, "database") and hasattr(config.database, "url"):
        result["database_url"] = result["database_url"] or config.database.url
    if hasattr(config, "redis") and hasattr(config.redis, "url"):
        result["redis_url"] = config.redis.url
    if hasattr(config, "telegram") and hasattr(config.telegram, "token"):
        result["bot_token"] = result["bot_token"] or config.telegram.token

    # Настройки спам детекции
    if hasattr(config, "spam_detection"):
        result["spam_detection"] = (
            vars(config.spam_detection)
            if hasattr(config.spam_detection, "__dict__")
            else config.spam_detection
        )

    # OpenRouter удален

    # Внешние API
    if hasattr(config, "external_apis"):
        result["external_apis"] = (
            vars(config.external_apis)
            if hasattr(config.external_apis, "__dict__")
            else config.external_apis
        )

    # Настройки логирования
    if hasattr(config, "logging"):
        result["logging"] = (
            vars(config.logging) if hasattr(config.logging, "__dict__") else config.logging
        )

    # API настройки для JWT
    result["api"] = {
        "auth": {
            "jwt_secret": result["jwt_secret"]
            or "development_jwt_secret_32_chars_minimum_length_required",
            "jwt_algorithm": "HS256",
            "access_token_expire_minutes": 30,
        },
        "rate_limit": {
            "default_requests_per_minute": 60,
            "default_requests_per_day": 5000,
            "burst_limit": 10,
        },
    }

    return result


def setup_signal_handlers():
    """Настройка обработчиков сигналов для graceful shutdown"""

    def signal_handler(signum, frame):
        logger = logging.getLogger(__name__)
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")

        # Устанавливаем событие завершения
        if app_state["shutdown_event"]:
            app_state["shutdown_event"].set()

        # Для synchronous contexts
        if hasattr(asyncio, "_get_running_loop"):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(shutdown_application())
            except RuntimeError:
                pass

    # Регистрируем обработчики для UNIX сигналов
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal_handler)


# FastAPI app instance
def create_app() -> FastAPI:
    """Factory function для создания FastAPI приложения"""
    app = FastAPI(
        title="AntiSpam Detection API",
        description="Production-ready API для высокоточной детекции спама в Telegram",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        # Production settings
        debug=os.getenv("DEBUG", "false").lower() == "true",
        # Security headers
        responses={
            422: {"description": "Validation Error"},
            429: {"description": "Rate Limit Exceeded"},
            500: {"description": "Internal Server Error"},
        },
    )

    # Добавляем базовые маршруты сразу при создании приложения
    setup_basic_routes(app)

    return app


app = create_app()

# Настройка signal handlers
setup_signal_handlers()


# Интеграция с приложением после создания
async def setup_app_components():
    """Настройка компонентов после создания приложения"""
    logger = logging.getLogger(__name__)

    try:
        # Получаем сервисы из app state после startup
        services = app_state.get("production_services")
        metrics = app_state.get("metrics")
        error_handler = app_state.get("error_handler")

        if services and metrics and error_handler:
            # Настройка middleware
            setup_middleware(app, services, metrics, error_handler)

            # Настройка роутеров
            setup_routes(app)

            # Настройка OpenAPI документации
            # OpenAPI документация удалена

            logger.info("[OK] App components configured")

    except Exception as e:
        logger.error(f"[ERROR] Failed to setup app components: {e}")
        raise


async def main():
    """Основная функция приложения"""
    logger = logging.getLogger(__name__)

    try:
        # Определяем режим запуска
        run_mode = os.getenv("RUN_MODE", "both").lower()
        environment = os.getenv("ENVIRONMENT", "development")

        logger.info(f"[START] Starting AntiSpam Bot v2.0 in {run_mode} mode ({environment})")

        if run_mode == "telegram":
            # Только Telegram bot
            config = load_config()
            # Преобразуем Config в плоский словарь для совместимости
            config_dict = config_to_dict(config)
            validated_config = validate_production_config(config_dict)
            setup_logging(validated_config)

            services = await setup_production_services(validated_config)
            await start_telegram_bot(validated_config, services)

            # Ждем завершения
            while not app_state["shutdown_event"].is_set():
                await asyncio.sleep(1)

        elif run_mode == "http":
            # Только HTTP API
            await setup_app_components()

            # Запуск uvicorn сервера
            uvicorn_config = {
                "host": os.getenv("HOST", "0.0.0.0"),
                "port": int(os.getenv("PORT", 8080)),
                "reload": environment == "development",
                "log_level": "info",
                "access_log": True,
                "use_colors": environment == "development",
                "workers": 1 if environment == "development" else int(os.getenv("WORKERS", 4)),
            }

            logger.info(
                f"[WEB] Starting HTTP server on {uvicorn_config['host']}:{uvicorn_config['port']}"
            )

            # Используем строку импорта если reload или workers > 1 для избежания предупреждений
            if uvicorn_config.get("reload") or uvicorn_config.get("workers", 1) > 1:
                await uvicorn.run("src.main:app", **uvicorn_config)
            else:
                await uvicorn.run(app, **uvicorn_config)

        else:  # both
            # HTTP + Telegram - запускаем uvicorn с lifespan
            uvicorn_config = uvicorn.Config(
                app=app,
                host=os.getenv("HTTP_HOST", os.getenv("HOST", "0.0.0.0")),
                port=int(os.getenv("HTTP_PORT", os.getenv("PORT", "8080"))),
                log_level=os.getenv("LOG_LEVEL", "info").lower(),
                access_log=True,
            )

            logger.info(f"[BOTH] Starting HTTP+Telegram in both mode")

            # Запускаем uvicorn - lifespan автоматически запустит Telegram бота
            server = uvicorn.Server(uvicorn_config)
            await server.serve()

    except KeyboardInterrupt:
        logger.info("👋 Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"[ERROR] Application failed: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    # Запуск приложения
    asyncio.run(main())
