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
    print("🚀 Starting AntiSpam Bot v2.0...")
    
    try:
        # Startup
        await startup_application()
        print("✅ Application started successfully")
        
        yield
        
    finally:
        # Shutdown
        print("🛑 Shutting down application...")
        await shutdown_application()
        print("✅ Application shutdown complete")


async def startup_application():
    """Application startup logic"""
    try:
        # Загрузка и валидация конфигурации
        config = load_config()
        validated_config = validate_production_config(config)
        
        # Настройка логирования
        setup_logging(validated_config)
        
        # Инициализация production сервисов
        production_services = await setup_production_services(validated_config)
        app_state["production_services"] = production_services
        
        # Инициализация мониторинга
        metrics = create_prometheus_metrics()
        app_state["metrics"] = metrics
        
        # Запуск Prometheus сервера
        if validated_config.get("metrics", {}).get("enabled", True):
            metrics_port = validated_config.get("metrics", {}).get("prometheus_port", 9090)
            metrics.start_metrics_server(metrics_port)
        
        # Инициализация error handler
        error_handler = create_error_handler(
            service_name="antispam-api",
            config=validated_config.get("error_handling", {})
        )
        app_state["error_handler"] = error_handler
        
        # Запуск Telegram бота если нужно
        run_mode = os.getenv("RUN_MODE", "both").lower()
        if run_mode in ["telegram", "both"]:
            await start_telegram_bot(validated_config, production_services)
        
        # Интеграция сервисов с FastAPI
        integrate_with_fastapi_app(app, production_services, validated_config)
        
        # Настройка middleware
        setup_middleware(app, production_services, metrics, error_handler)
        
        # Настройка роутеров
        setup_routes(app)
        
        # Настройка OpenAPI документации
        setup_openapi_documentation(app)
        
        print("🎉 All services initialized successfully!")
        
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def shutdown_application():
    """Application shutdown logic"""
    try:
        # Устанавливаем событие завершения
        app_state["shutdown_event"].set()
        
        # Останавливаем Telegram бота
        if app_state["telegram_bot"]:
            await app_state["telegram_bot"].stop()
            print("✅ Telegram bot stopped")
        
        # Закрываем production сервисы
        if app_state["production_services"]:
            services = app_state["production_services"]
            
            if services.postgres_client:
                await services.postgres_client.disconnect()
                print("✅ PostgreSQL disconnected")
            
            if services.redis_client:
                await services.redis_client.disconnect()
                print("✅ Redis disconnected")
        
    except Exception as e:
        print(f"⚠️ Shutdown error: {e}")


def setup_logging(config: Dict[str, Any]):
    """Настройка системы логирования"""
    log_config = config.get("logging", {})
    
    # Настройка основного логгера
    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO")),
        format=log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_config.get("file", "logs/antispam-bot.log"), encoding='utf-8')
        ] if log_config.get("file") else [logging.StreamHandler(sys.stdout)]
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
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.UnicodeDecoder(),
                    structlog.processors.JSONRenderer()
                ],
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )
            print("✅ Structured logging enabled")
        except ImportError:
            print("⚠️ structlog not available, using standard logging")


async def start_telegram_bot(config: Dict[str, Any], production_services: ProductionServices):
    """Запуск Telegram бота"""
    try:
        if not config.get("bot_token"):
            print("⚠️ Bot token not configured, skipping Telegram bot")
            return
        
        # Создаем бота
        telegram_bot = TelegramBot(
            token=config["bot_token"],
            admin_chat_id=config.get("admin_chat_id"),
            production_services=production_services
        )
        
        # Настраиваем handlers
        setup_handlers(
            telegram_bot,
            spam_detector=None,  # TODO: Inject from production_services
            admin_chat_id=config.get("admin_chat_id")
        )
        
        # Запускаем бота в фоне
        asyncio.create_task(telegram_bot.start())
        app_state["telegram_bot"] = telegram_bot
        
        print("✅ Telegram bot started")
        
    except Exception as e:
        print(f"❌ Failed to start Telegram bot: {e}")
        raise


def setup_middleware(
    app: FastAPI, 
    production_services: ProductionServices,
    metrics: PrometheusMetrics,
    error_handler: ProductionErrorHandler
):
    """Настройка middleware"""
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # В production настроить конкретные домены
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Metrics middleware
    app.add_middleware(MetricsMiddleware, metrics=metrics)
    
    # Global error handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Глобальный обработчик ошибок"""
        return await error_handler.handle_error(exc, request=request)
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Обработчик HTTP ошибок"""
        return await error_handler.handle_error(exc, request=request)
    
    print("✅ Middleware configured")


def setup_routes(app: FastAPI):
    """Настройка маршрутов"""
    
    # API routes
    app.include_router(
        auth_router,
        prefix="/api/v1/auth",
        tags=["Authentication"]
    )
    
    app.include_router(
        public_api_router,
        prefix="/api/v1",
        tags=["Public API"]
    )
    
    # Root endpoint
    @app.get("/", tags=["System"])
    async def root():
        """Root endpoint с информацией о системе"""
        return {
            "service": "AntiSpam Detection API",
            "version": "2.0.0",
            "status": "operational",
            "documentation": "/docs",
            "metrics": "/metrics",
            "health": "/health"
        }
    
    # Health check endpoint
    @app.get("/health", tags=["System"])
    async def health_check():
        """Comprehensive health check"""
        try:
            health_data = {
                "status": "healthy",
                "timestamp": asyncio.get_event_loop().time(),
                "version": "2.0.0",
                "components": {}
            }
            
            # Проверяем production сервисы
            if app_state["production_services"]:
                services_health = app_state["production_services"].health_check()
                health_data["components"]["services"] = services_health
            
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
            return {
                "status": "error",
                "timestamp": asyncio.get_event_loop().time(),
                "error": str(e)
            }
    
    # Metrics endpoint
    @app.get("/metrics", tags=["System"])
    async def get_metrics():
        """Prometheus metrics endpoint"""
        if app_state["metrics"]:
            metrics_data = app_state["metrics"].get_metrics()
            return JSONResponse(
                content=metrics_data.decode('utf-8'),
                media_type="text/plain"
            )
        else:
            return {"error": "Metrics not available"}
    
    print("✅ Routes configured")


# FastAPI app instance
app = FastAPI(
    title="AntiSpam Detection API",
    description="Production-ready API для высокоточной детекции спама",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)


def setup_signal_handlers():
    """Настройка обработчиков сигналов для graceful shutdown"""
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, initiating graceful shutdown...")
        app_state["shutdown_event"].set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def run_telegram_only():
    """Запуск только Telegram бота"""
    print("🤖 Starting Telegram bot only...")
    
    try:
        config = load_config()
        production_services = await setup_production_services(config)
        
        await start_telegram_bot(config, production_services)
        
        # Ждем сигнала завершения
        await app_state["shutdown_event"].wait()
        
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    finally:
        await shutdown_application()


async def run_http_only():
    """Запуск только HTTP API"""
    print("🌐 Starting HTTP API only...")
    
    config = load_config()
    http_config = config.get("http_server", {})
    
    # Настройка uvicorn
    uvicorn_config = uvicorn.Config(
        app,
        host=http_config.get("host", "0.0.0.0"),
        port=http_config.get("port", 8080),
        workers=1,  # В lifespan режиме workers должен быть 1
        log_level=config.get("logging", {}).get("level", "info").lower(),
        access_log=True,
        use_colors=True
    )
    
    server = uvicorn.Server(uvicorn_config)
    
    try:
        await server.serve()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")


async def run_both():
    """Запуск и Telegram бота, и HTTP API"""
    print("🚀 Starting both Telegram bot and HTTP API...")
    
    config = load_config()
    http_config = config.get("http_server", {})
    
    # Настройка uvicorn для combined режима
    uvicorn_config = uvicorn.Config(
        app,
        host=http_config.get("host", "0.0.0.0"),
        port=http_config.get("port", 8080),
        workers=1,
        log_level=config.get("logging", {}).get("level", "info").lower(),
        access_log=True,
        use_colors=True
    )
    
    server = uvicorn.Server(uvicorn_config)
    
    try:
        await server.serve()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")


def check_environment():
    """Проверка окружения перед запуском"""
    print("🔍 Checking environment...")
    
    # Проверка Python версии
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required")
        sys.exit(1)
    
    # Проверка обязательных переменных окружения
    required_env_vars = ["DATABASE_URL"]
    missing_vars = []
    
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        print("   Please check your .env file")
        sys.exit(1)
    
    print("✅ Environment check passed")


async def main():
    """Основная функция приложения"""
    print("=" * 60)
    print("🛡️  ANTISPAM BOT v2.0 - PRODUCTION READY")
    print("🏗️  Modern Architecture: CAS + RUSpam + OpenAI")
    print("=" * 60)
    
    # Проверка окружения
    check_environment()
    
    # Настройка signal handlers
    setup_signal_handlers()
    
    # Определение режима запуска
    run_mode = os.getenv("RUN_MODE", "both").lower()
    
    print(f"🎯 Run mode: {run_mode}")
    
    try:
        if run_mode == "telegram":
            await run_telegram_only()
        elif run_mode == "http":
            await run_http_only()
        elif run_mode == "both":
            await run_both()
        else:
            print(f"❌ Invalid RUN_MODE: {run_mode}")
            print("   Valid options: telegram, http, both")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Application failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        # Запуск приложения
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)