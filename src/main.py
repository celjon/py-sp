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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
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

from .config.config import load_config
from .config.dependencies import (
    setup_production_services,
    validate_production_config,
    ProductionServices,
)


from .domain.service.monitoring.prometheus_metrics import (
    PrometheusMetrics,
    MetricsMiddleware,
    create_prometheus_metrics,
)

from .delivery.telegram.bot import AntiSpamBot

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
        await startup_application()
        logger.info("[OK] Application started successfully")

        yield

    except Exception as e:
        logger.error(f"[ERROR] Startup failed: {e}")
        raise
    finally:
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
        config = load_config()
        config_dict = config_to_dict(config)
        validated_config = validate_production_config(config_dict)
        logger.info("[OK] Configuration loaded and validated")

        setup_logging(validated_config)
        logger.info("[OK] Logging configured")

        production_services = await setup_production_services(validated_config)
        app_state["production_services"] = production_services
        logger.info("[OK] Production services initialized")

        metrics = create_prometheus_metrics()
        app_state["metrics"] = metrics

        if validated_config.get("metrics", {}).get("enabled", True):
            metrics_port = validated_config.get("metrics", {}).get("prometheus_port", 9090)
            try:
                metrics.start_metrics_server(metrics_port)
                logger.info(f"[OK] Prometheus metrics server started on port {metrics_port}")
            except Exception as e:
                logger.warning(f"[WARN] Failed to start metrics server: {e}")


        run_mode = os.getenv("RUN_MODE", "both").lower()
        logger.info(f"[INFO] Running in {run_mode} mode")

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
        app_state["shutdown_event"].set()

        if app_state["telegram_bot"]:
            try:
                await app_state["telegram_bot"].stop()
                logger.info("[OK] Telegram bot stopped")
            except Exception as e:
                logger.error(f"[WARN] Error stopping Telegram bot: {e}")

        if app_state["production_services"]:
            services = app_state["production_services"]

            if services.background_cleanup:
                try:
                    await services.background_cleanup.stop_cleanup_scheduler()
                    logger.info("[OK] Cleanup scheduler stopped")
                except Exception as e:
                    logger.warning(f"[WARN] Error stopping cleanup scheduler: {e}")

            if app_state["metrics"]:
                try:
                    app_state["metrics"].stop_metrics_server()
                    logger.info("[OK] Metrics server stopped")
                except Exception as e:
                    logger.warning(f"[WARN] Error stopping metrics server: {e}")

            if services.postgres_client:
                try:
                    await services.postgres_client.disconnect()
                    logger.info("[OK] PostgreSQL disconnected")
                except Exception as e:
                    logger.error(f"[WARN] Error disconnecting PostgreSQL: {e}")

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

    log_file = log_config.get("file", "logs/antispam-bot.log")
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO")),
        format=log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        handlers=handlers,
        force=True,
    )

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
            pass
        except ImportError:
            pass


async def start_telegram_bot(config: Dict[str, Any], services: ProductionServices):
    """Запуск Telegram бота"""
    logger = logging.getLogger(__name__)

    try:
        bot_token = config.get("bot_token") or config.get("telegram", {}).get("token")
        if not bot_token:
            raise ValueError("BOT_TOKEN is required")

        redis_url = config.get("redis_url") or config.get("redis", {}).get("url")

        bot_dependencies = {
            "ensemble_detector": services.ensemble_detector,

            "user_repository": services.user_repo,
            "message_repository": services.message_repo,
            "spam_samples_repository": services.spam_samples_repo,
            "chat_repository": services.chat_repo,

            "check_message_usecase": services.check_message_usecase,
            "ban_user_usecase": services.ban_user_usecase,

            "postgres_client": services.postgres_client,
            "redis_client": services.redis_client,
            "redis_cache": services.redis_cache,

            "cas_gateway": services.cas_gateway,
            "bothub_gateway": services.bothub_gateway,

            "config": config,
            "admin_chat_id": config.get("admin_chat_id"),
            "admin_users": config.get("admin_users", []),
        }

        bot = AntiSpamBot(bot_token=bot_token, redis_url=redis_url, dependencies=bot_dependencies)

        if services.background_cleanup:
            await services.background_cleanup.start_cleanup_scheduler(interval_hours=6)
            logger.info("[OK] Automatic cleanup scheduler started (every 6 hours)")

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

    if os.getenv("ENVIRONMENT", "development") == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_middleware(MetricsMiddleware, metrics=metrics)



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

            if app_state.get("production_services"):
                try:
                    services_health = await app_state["production_services"].health_check()
                    health_data["components"]["production_services"] = services_health
                except Exception as e:
                    health_data["components"]["production_services"] = {"status": "error", "error": str(e)}

            if app_state.get("telegram_bot"):
                try:
                    bot_health = {
                        "status": "healthy" if app_state["telegram_bot"].is_running else "stopped"
                    }
                    health_data["components"]["telegram_bot"] = bot_health
                except Exception as e:
                    health_data["components"]["telegram_bot"] = {"status": "error", "error": str(e)}

            if app_state.get("metrics"):
                try:
                    metrics_health = await app_state["metrics"].health_check() if hasattr(app_state["metrics"], "health_check") and callable(app_state["metrics"].health_check) else {"status": "healthy"}
                    health_data["components"]["metrics"] = metrics_health
                except Exception as e:
                    health_data["components"]["metrics"] = {"status": "error", "error": str(e)}

            if app_state.get("error_handler"):
                try:
                    error_handler_health = await app_state["error_handler"].health_check() if hasattr(app_state["error_handler"], "health_check") and callable(app_state["error_handler"].health_check) else {"status": "healthy"}
                    health_data["components"]["error_handler"] = error_handler_health
                except Exception as e:
                    health_data["components"]["error_handler"] = {"status": "error", "error": str(e)}

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



def setup_routes(app: FastAPI):
    """Настройка всех маршрутов включая API"""



def config_to_dict(config) -> Dict[str, Any]:
    """Преобразует Config объект в плоский словарь"""
    result = {}

    result["bot_token"] = os.getenv("BOT_TOKEN")
    result["database_url"] = os.getenv("DATABASE_URL")
    result["redis_url"] = os.getenv("REDIS_URL")
    result["admin_chat_id"] = os.getenv("ADMIN_CHAT_ID")
    result["admin_users"] = (
        os.getenv("ADMIN_USERS", "").split(",") if os.getenv("ADMIN_USERS") else []
    )
    result["environment"] = os.getenv("ENVIRONMENT", "development")
    result["log_level"] = os.getenv("LOG_LEVEL", "INFO")
    result["jwt_secret"] = os.getenv("JWT_SECRET")
    result["api_secret"] = os.getenv("API_SECRET_KEY")

    if hasattr(config, "database") and hasattr(config.database, "url"):
        result["database_url"] = result["database_url"] or config.database.url
    if hasattr(config, "redis") and hasattr(config.redis, "url"):
        result["redis_url"] = config.redis.url
    if hasattr(config, "telegram") and hasattr(config.telegram, "token"):
        result["bot_token"] = result["bot_token"] or config.telegram.token

    if hasattr(config, "spam_detection"):
        result["spam_detection"] = (
            vars(config.spam_detection)
            if hasattr(config.spam_detection, "__dict__")
            else config.spam_detection
        )


    if hasattr(config, "external_apis"):
        result["external_apis"] = (
            vars(config.external_apis)
            if hasattr(config.external_apis, "__dict__")
            else config.external_apis
        )

    if hasattr(config, "logging"):
        result["logging"] = (
            vars(config.logging) if hasattr(config.logging, "__dict__") else config.logging
        )

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

        if app_state["shutdown_event"]:
            app_state["shutdown_event"].set()

        if hasattr(asyncio, "_get_running_loop"):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(shutdown_application())
            except RuntimeError:
                pass

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal_handler)


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
        debug=os.getenv("DEBUG", "false").lower() == "true",
        responses={
            422: {"description": "Validation Error"},
            429: {"description": "Rate Limit Exceeded"},
            500: {"description": "Internal Server Error"},
        },
    )

    setup_basic_routes(app)

    return app


app = create_app()

setup_signal_handlers()


async def setup_app_components():
    """Настройка компонентов после создания приложения"""
    logger = logging.getLogger(__name__)

    try:
        services = app_state.get("production_services")
        metrics = app_state.get("metrics")
        error_handler = app_state.get("error_handler")

        if services and metrics and error_handler:
            setup_middleware(app, services, metrics, error_handler)

            setup_routes(app)

            logger.info("[OK] App components configured")

    except Exception as e:
        logger.error(f"[ERROR] Failed to setup app components: {e}")
        raise


async def main():
    """Основная функция приложения"""
    logger = logging.getLogger(__name__)

    try:
        run_mode = os.getenv("RUN_MODE", "both").lower()
        environment = os.getenv("ENVIRONMENT", "development")

        logger.info(f"[START] Starting AntiSpam Bot v2.0 in {run_mode} mode ({environment})")

        if run_mode == "telegram":
            config = load_config()
            config_dict = config_to_dict(config)
            validated_config = validate_production_config(config_dict)
            setup_logging(validated_config)

            services = await setup_production_services(validated_config)
            await start_telegram_bot(validated_config, services)

            while not app_state["shutdown_event"].is_set():
                await asyncio.sleep(1)

        elif run_mode == "http":
            await setup_app_components()

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

            if uvicorn_config.get("reload") or uvicorn_config.get("workers", 1) > 1:
                await uvicorn.run("src.main:app", **uvicorn_config)
            else:
                await uvicorn.run(app, **uvicorn_config)

        else:
            uvicorn_config = uvicorn.Config(
                app=app,
                host=os.getenv("HTTP_HOST", os.getenv("HOST", "0.0.0.0")),
                port=int(os.getenv("HTTP_PORT", os.getenv("PORT", "8080"))),
                log_level=os.getenv("LOG_LEVEL", "info").lower(),
                access_log=True,
            )

            logger.info(f"[BOTH] Starting HTTP+Telegram in both mode")

            server = uvicorn.Server(uvicorn_config)
            await server.serve()

    except KeyboardInterrupt:
        logger.info("👋 Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"[ERROR] Application failed: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
