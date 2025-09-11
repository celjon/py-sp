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
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Core imports
from .config.config import load_config
from .config.dependencies import (
    setup_production_services, 
    integrate_with_fastapi_app,
    validate_production_config,
    ProductionServices
)

# HTTP routes
from .delivery.http.routes.auth_v2 import router as auth_router
from .delivery.http.routes.public_api_v2 import router as public_api_router
from .delivery.http.schema.openapi_generator import setup_openapi_documentation

# Services
from .domain.service.monitoring.prometheus_metrics import (
    PrometheusMetrics, 
    MetricsMiddleware,
    create_prometheus_metrics
)
from .domain.service.error_handling.error_handler import (
    ProductionErrorHandler,
    create_error_handler
)

# Bot imports
from .delivery.telegram.bot import TelegramBot
from .delivery.telegram.handlers import setup_handlers

# Global state
app_state = {
    "telegram_bot": None,
    "production_services": None,
    "metrics": None,
    "error_handler": None,
    "shutdown_event": asyncio.Event()
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting AntiSpam Bot v2.0...")
    
    try:
        # Startup
        await startup_application()
        logger.info("✅ Application started successfully")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    finally:
        # Shutdown
        logger.info("🛑 Shutting down application...")
        try:
            await shutdown_application()
            logger.info("✅ Application shutdown complete")
        except Exception as e:
            logger.error(f"⚠️ Shutdown error: {e}")


async def startup_application():
    """Application startup logic"""
    logger = logging.getLogger(__name__)
    
    try:
        # Загрузка и валидация конфигурации
        config = load_config()
        validated_config = validate_production_config(config)
        logger.info("✅ Configuration loaded and validated")
        
        # Настройка логирования
        setup_logging(validated_config)
        logger.info("✅ Logging configured")
        
        # Инициализация production сервисов
        production_services = await setup_production_services(validated_config)
        app_state["production_services"] = production_services
        logger.info("✅ Production services initialized")
        
        # Инициализация мониторинга
        metrics = create_prometheus_metrics()
        app_state["metrics"] = metrics
        
        # Запуск Prometheus сервера
        if validated_config.get("metrics", {}).get("enabled", True):
            metrics_port = validated_config.get("metrics", {}).get("prometheus_port", 9090)
            try:
                metrics.start_metrics_server(metrics_port)
                logger.info(f"✅ Prometheus metrics server started on port {metrics_port}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to start metrics server: {e}")
        
        # Инициализация error handler
        error_handler = create_error_handler(
            service_name="antispam-api",
            config=validated_config.get("error_handling", {})
        )
        app_state["error_handler"] = error_handler
        logger.info("✅ Error handler configured")
        
        # Запуск Telegram бота если нужно
        run_mode = os.getenv("RUN_MODE", "both").lower()
        if run_mode in ["telegram", "both"]:
            await start_telegram_bot(validated_config, production_services)
            logger.info("✅ Telegram bot started")
        
        logger.info("🎉 All services initialized successfully!")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
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
                logger.info("✅ Telegram bot stopped")
            except Exception as e:
                logger.error(f"⚠️ Error stopping Telegram bot: {e}")
        
        # Закрываем production сервисы
        if app_state["production_services"]:
            services = app_state["production_services"]
            
            # Останавливаем метрики сервер
            if app_state["metrics"]:
                try:
                    app_state["metrics"].stop_metrics_server()
                    logger.info("✅ Metrics server stopped")
                except Exception as e:
                    logger.warning(f"⚠️ Error stopping metrics server: {e}")
            
            # Закрываем PostgreSQL
            if services.postgres_client:
                try:
                    await services.postgres_client.disconnect()
                    logger.info("✅ PostgreSQL disconnected")
                except Exception as e:
                    logger.error(f"⚠️ Error disconnecting PostgreSQL: {e}")
            
            # Закрываем Redis
            if services.redis_client:
                try:
                    await services.redis_client.disconnect()
                    logger.info("✅ Redis disconnected")
                except Exception as e:
                    logger.error(f"⚠️ Error disconnecting Redis: {e}")
        
    except Exception as e:
        logger.error(f"⚠️ Shutdown error: {e}")
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
        handlers.append(
            logging.FileHandler(log_file, encoding='utf-8')
        )
    
    # Настройка основного логгера
    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO")),
        format=log_config.get(
            "format", 
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ),
        handlers=handlers,
        force=True  # Перезаписываем существующую конфигурацию
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
                    structlog.processors.JSONRenderer()
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
        # Создаем бота
        bot = TelegramBot(
            token=config.get("bot_token") or config.get("telegram", {}).get("token"),
            config=config.get("telegram", {})
        )
        
        # Настраиваем обработчики
        setup_handlers(bot.dp, services)
        
        # Запускаем бота
        await bot.start()
        app_state["telegram_bot"] = bot
        
        logger.info("✅ Telegram bot started successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to start Telegram bot: {e}")
        raise


def setup_middleware(app: FastAPI, services: ProductionServices, metrics: PrometheusMetrics, error_handler):
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
    
    # API Auth middleware (создается в dependencies)
    auth_middleware = services.api_auth_middleware(app)
    # Примечание: auth middleware добавляется через factory pattern в dependencies


def setup_routes(app: FastAPI):
    """Настройка маршрутов"""
    # API routes
    app.include_router(auth_router, prefix="/api/v1", tags=["Authentication"])
    app.include_router(public_api_router, prefix="/api/v1", tags=["Detection"])
    
    # Health check endpoint
    @app.get("/health", tags=["System"])
    async def health_check():
        """Production health check endpoint"""
        try:
            health_data = {
                "status": "healthy",
                "version": "2.0.0",
                "timestamp": time.time(),
                "components": {}
            }
            
            # Проверяем production services
            if app_state["production_services"]:
                services_health = app_state["production_services"].health_check()
                health_data["components"]["production_services"] = services_health
            
            # Проверяем Telegram bot
            if app_state["telegram_bot"]:
                bot_health = {
                    "status": "healthy" if app_state["telegram_bot"].is_running else "stopped"
                }
                health_data["components"]["telegram_bot"] = bot_health
            
            # Проверяем метрики
            if app_state["metrics"]:
                metrics_health = app_state["metrics"].health_check()
                health_data["components"]["metrics"] = metrics_health
            
            # Проверяем error handler
            if app_state["error_handler"]:
                error_handler_health = app_state["error_handler"].health_check()
                health_data["components"]["error_handler"] = error_handler_health
            
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
                content={
                    "status": "error",
                    "timestamp": time.time(),
                    "error": str(e)
                }
            )
    
    # Metrics endpoint
    @app.get("/metrics", tags=["System"])
    async def get_metrics():
        """Prometheus metrics endpoint"""
        try:
            if app_state["metrics"]:
                metrics_data = app_state["metrics"].get_metrics()
                return Response(
                    content=metrics_data,
                    media_type="text/plain; version=0.0.4; charset=utf-8"
                )
            else:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics not available"}
                )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Metrics endpoint failed: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )

    print("✅ Routes configured")


def setup_signal_handlers():
    """Настройка обработчиков сигналов для graceful shutdown"""
    def signal_handler(signum, frame):
        logger = logging.getLogger(__name__)
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        
        # Устанавливаем событие завершения
        if app_state["shutdown_event"]:
            app_state["shutdown_event"].set()
        
        # Для synchronous contexts
        if hasattr(asyncio, '_get_running_loop'):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(shutdown_application())
            except RuntimeError:
                pass
    
    # Регистрируем обработчики для UNIX сигналов
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, signal_handler)


# FastAPI app instance
def create_app() -> FastAPI:
    """Factory function для создания FastAPI приложения"""
    return FastAPI(
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
            500: {"description": "Internal Server Error"}
        }
    )


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
            setup_openapi_documentation(app)
            
            logger.info("✅ App components configured")
        
    except Exception as e:
        logger.error(f"❌ Failed to setup app components: {e}")
        raise


async def main():
    """Основная функция приложения"""
    logger = logging.getLogger(__name__)
    
    try:
        # Определяем режим запуска
        run_mode = os.getenv("RUN_MODE", "both").lower()
        environment = os.getenv("ENVIRONMENT", "development")
        
        logger.info(f"🚀 Starting AntiSpam Bot v2.0 in {run_mode} mode ({environment})")
        
        if run_mode == "telegram":
            # Только Telegram bot
            config = load_config()
            validated_config = validate_production_config(config)
            setup_logging(validated_config)
            
            services = await setup_production_services(validated_config)
            await start_telegram_bot(validated_config, services)
            
            # Ждем завершения
            while not app_state["shutdown_event"].is_set():
                await asyncio.sleep(1)
                
        elif run_mode == "http":
            # Только HTTP API
            setup_app_components()
            
            # Запуск uvicorn сервера
            uvicorn_config = {
                "host": os.getenv("HOST", "0.0.0.0"),
                "port": int(os.getenv("PORT", 8080)),
                "reload": environment == "development",
                "log_level": "info",
                "access_log": True,
                "use_colors": environment == "development",
                "workers": 1 if environment == "development" else int(os.getenv("WORKERS", 4))
            }
            
            logger.info(f"🌐 Starting HTTP server on {uvicorn_config['host']}:{uvicorn_config['port']}")
            await uvicorn.run(app, **uvicorn_config)
            
        else:  # both
            # HTTP + Telegram
            await setup_app_components()
            
            # Запуск в отдельной задаче
            uvicorn_config = {
                "host": os.getenv("HOST", "0.0.0.0"),
                "port": int(os.getenv("PORT", 8080)),
                "reload": False,  # Отключаем reload для production
                "log_level": "info",
                "access_log": True,
                "workers": 1  # Один worker для совместного режима
            }
            
            server_task = asyncio.create_task(
                uvicorn.run(app, **uvicorn_config)
            )
            
            # Ждем завершения
            try:
                await server_task
            except KeyboardInterrupt:
                logger.info("👋 Received shutdown signal")
                server_task.cancel()
                
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass
    
    except KeyboardInterrupt:
        logger.info("👋 Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"❌ Application failed: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    # Запуск приложения
    asyncio.run(main())
