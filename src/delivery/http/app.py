from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import time
from typing import Dict, Any, Optional
import asyncio

from ...config.config import load_config
from .routes import auth_v2 as auth, admin, stats  
from .routes import public_api_v2 as public_api
from .middlewares.rate_limit import RateLimitMiddleware
from .middlewares.api_auth import ApiAuthMiddleware


def create_app(dependencies: Dict[str, Any] = None) -> FastAPI:
    """Создание FastAPI приложения с публичным API"""
    
    config = load_config()
    
    app = FastAPI(
        title="AntiSpam Bot API",
        description="""
        🚫 **Многослойная система детекции спама для Telegram**
        
        ## 🎯 Возможности
        
        ### Публичный API
        - `/api/v1/detect` - Детекция спама для одного сообщения
        - `/api/v1/detect/batch` - Batch детекция до 100 сообщений  
        - `/api/v1/stats` - Статистика использования вашего API ключа
        - `/api/v1/detectors` - Информация о доступных детекторах
        
        ### Управление API ключами  
        - `/api/v1/auth/keys` - Создание и управление API ключами
        - `/api/v1/auth/stats` - Глобальная статистика использования
        
        ### Админ панель
        - `/api/v1/admin/` - Управление образцами спама
        - `/api/v1/admin/status` - Статус системы
        
        ## 🔐 Аутентификация
        
        Для доступа к API требуется API ключ. Передавайте его в заголовке:
        ```
        Authorization: Bearer YOUR_API_KEY
        ```
        
        ## 📊 Rate Limiting
        
        - **Free план**: 10 запросов/мин, 1K запросов/день
        - **Basic план**: 60 запросов/мин, 10K запросов/день  
        - **Pro план**: 300 запросов/мин, 50K запросов/день
        - **Enterprise план**: Без лимитов
        
        ## 🔍 Детекторы спама
        
        1. **Эвристики** (1-5ms) - быстрые проверки emoji, caps, ссылок
        2. **CAS** (10-50ms) - база известных спамеров Combot
        3. **RUSpam** (100-500ms) - BERT модель для русского языка
        4. **ML Classifier** (100-500ms) - sklearn классификатор
        5. **OpenAI** (1-3s) - анализ сложных случаев
        
        ## 📈 Пример использования
        
        ```python
        import requests
        
        headers = {"Authorization": "Bearer YOUR_API_KEY"}
        data = {
            "text": "🔥🔥🔥 Заработок! Детали в ЛС!",
            "context": {"is_new_user": True}
        }
        
        response = requests.post(
            "https://api.antispam.example.com/api/v1/detect",
            json=data,
            headers=headers
        )
        
        result = response.json()
        print(f"Спам: {result['is_spam']}, уверенность: {result['confidence']}")
        ```
        """,
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=[
            {
                "name": "spam-detection",
                "description": "🔍 Детекция спама - основной функционал API"
            },
            {
                "name": "auth",
                "description": "🔐 Управление API ключами и аутентификация"
            },
            {
                "name": "statistics", 
                "description": "📊 Статистика использования и производительности"
            },
            {
                "name": "admin",
                "description": "🛡️ Административные функции (требует админских прав)"
            }
        ]
    )
    
    # Сохраняем зависимости в app state
    app.state.dependencies = dependencies or {}
    app.state.config = config
    
    # Настройка CORS (только для development)
    if config.http_server.get("cors_enabled", False):
        allowed_origins = config.http_server.get("cors_origins", ["*"])
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["*"],
        )
        print(f"🌐 CORS enabled for origins: {allowed_origins}")
    
    # API Authentication middleware для публичных endpoints
    api_key_repo = dependencies.get("api_key_repository") if dependencies else None
    usage_repo = dependencies.get("usage_repository") if dependencies else None
    
    if api_key_repo and usage_repo:
        app.add_middleware(
            ApiAuthMiddleware,
            api_key_repo=api_key_repo,
            usage_repo=usage_repo,
            protected_paths=[
                "/api/v1/detect",
                "/api/v1/detect/batch", 
                "/api/v1/stats",
                "/api/v1/detectors"
            ]
        )
        print("🔐 API Authentication middleware добавлен")
    
    # Rate limiting middleware
    app.add_middleware(RateLimitMiddleware)
    print("🚦 Rate limiting middleware добавлен")
    
    # Включаем роутеры
    app.include_router(
        public_api.router, 
        prefix="/api/v1", 
        tags=["spam-detection"]
    )
    app.include_router(
        auth.router, 
        prefix="/api/v1/auth", 
        tags=["auth"]
    )
    app.include_router(
        stats.router, 
        prefix="/api/v1", 
        tags=["statistics"]
    )
    app.include_router(
        admin.router, 
        prefix="/api/v1/admin", 
        tags=["admin"]
    )
    
    print("✅ Все API routes подключены")
    
    # Health check endpoint
    @app.get("/health", tags=["monitoring"])
    async def health_check():
        """Проверка состояния API"""
        try:
            dependencies = app.state.dependencies
            spam_detector = dependencies.get("spam_detector")
            
            if spam_detector:
                health = await spam_detector.health_check()
                return {
                    "status": "healthy",
                    "timestamp": time.time(),
                    "version": "2.0.0",
                    "api": {
                        "public_endpoints": 4,
                        "admin_endpoints": 8,
                        "auth_endpoints": 6
                    },
                    "detectors": health.get("detectors", {}),
                    "services": "operational"
                }
            else:
                return {
                    "status": "degraded", 
                    "timestamp": time.time(),
                    "version": "2.0.0",
                    "message": "Spam detector not available"
                }
        except Exception as e:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "timestamp": time.time(),
                    "error": str(e)
                }
            )
    
    # Metrics endpoint (Prometheus format)
    @app.get("/metrics", tags=["monitoring"])
    async def metrics():
        """Метрики в формате Prometheus"""
        try:
            dependencies = app.state.dependencies
            message_repo = dependencies.get("message_repository")
            usage_repo = dependencies.get("usage_repository")
            
            if not usage_repo:
                raise HTTPException(status_code=503, detail="Metrics service not available")
            
            # Получаем глобальную статистику API
            api_stats = await usage_repo.get_global_usage_stats(hours=24)
            
            # Получаем статистику Telegram (если доступна)
            telegram_stats = {}
            if message_repo:
                telegram_stats = await message_repo.get_global_stats(hours=24)
            
            metrics_text = f"""# HELP api_requests_total Total number of API requests
# TYPE api_requests_total counter
api_requests_total {api_stats.get('total_requests', 0)}

# HELP api_requests_successful Successful API requests
# TYPE api_requests_successful counter  
api_requests_successful {api_stats.get('successful_requests', 0)}

# HELP api_spam_detected_total Total spam detected via API
# TYPE api_spam_detected_total counter
api_spam_detected_total {api_stats.get('spam_detected', 0)}

# HELP api_active_keys Number of active API keys
# TYPE api_active_keys gauge
api_active_keys {api_stats.get('active_api_keys', 0)}

# HELP api_avg_processing_time_ms Average processing time in milliseconds
# TYPE api_avg_processing_time_ms gauge
api_avg_processing_time_ms {api_stats.get('avg_processing_time_ms', 0)}

# HELP telegram_spam_messages_total Total spam messages from Telegram
# TYPE telegram_spam_messages_total counter
telegram_spam_messages_total {telegram_stats.get('spam_messages', 0)}

# HELP telegram_clean_messages_total Total clean messages from Telegram  
# TYPE telegram_clean_messages_total counter
telegram_clean_messages_total {telegram_stats.get('clean_messages', 0)}
"""
            
            return JSONResponse(
                content=metrics_text,
                media_type="text/plain"
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Metrics error: {str(e)}")
    
    # Root endpoint with API info
    @app.get("/", tags=["info"])
    async def root():
        """Корневой endpoint с информацией об API"""
        return {
            "name": "AntiSpam Bot API",
            "version": "2.0.0",
            "description": "Многослойная система детекции спама с публичным API",
            "docs": "/docs",
            "health": "/health",
            "metrics": "/metrics",
            "api": {
                "public": {
                    "base_url": "/api/v1",
                    "endpoints": {
                        "detect_spam": "POST /api/v1/detect",
                        "batch_detect": "POST /api/v1/detect/batch",
                        "usage_stats": "GET /api/v1/stats",
                        "detectors_info": "GET /api/v1/detectors"
                    }
                },
                "auth": {
                    "base_url": "/api/v1/auth",
                    "endpoints": {
                        "create_key": "POST /api/v1/auth/keys",
                        "list_keys": "GET /api/v1/auth/keys", 
                        "global_stats": "GET /api/v1/auth/stats"
                    }
                },
                "admin": {
                    "base_url": "/api/v1/admin",
                    "authentication": "Basic Auth required"
                }
            },
            "features": [
                "Многослойная детекция спама",
                "Поддержка русского и английского языков", 
                "Rate limiting по API ключам",
                "Real-time статистика использования",
                "Batch обработка до 100 сообщений",
                "Webhook уведомления",
                "IP whitelist для безопасности"
            ],
            "contact": {
                "docs": "/docs",
                "support": "admin@antispam.example.com"
            }
        }
    
    # OpenAPI customization
    @app.get("/openapi.json", include_in_schema=False)
    async def custom_openapi():
        """Кастомизированная OpenAPI схема"""
        from fastapi.openapi.utils import get_openapi
        
        if app.openapi_schema:
            return app.openapi_schema
        
        openapi_schema = get_openapi(
            title="AntiSpam Bot API",
            version="2.0.0",
            description=app.description,
            routes=app.routes,
        )
        
        # Добавляем примеры аутентификации
        openapi_schema["components"]["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "API Key"
            },
            "BasicAuth": {
                "type": "http", 
                "scheme": "basic"
            }
        }
        
        # Добавляем security для всех endpoints
        for path, methods in openapi_schema["paths"].items():
            for method, details in methods.items():
                if path.startswith("/api/v1/detect") or path.startswith("/api/v1/stats"):
                    details["security"] = [{"ApiKeyAuth": []}]
                elif path.startswith("/api/v1/auth"):
                    details["security"] = [{"BasicAuth": []}]
                elif path.startswith("/api/v1/admin"):
                    details["security"] = [{"BasicAuth": []}]
        
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    
    # Error handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "timestamp": time.time(),
                "path": str(request.url.path),
                "method": request.method
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc):
        print(f"Unhandled API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": "An unexpected error occurred",
                "timestamp": time.time(),
                "path": str(request.url.path)
            }
        )
    
    # Startup event
    @app.on_event("startup")
    async def startup_event():
        print("🚀 FastAPI приложение запущено")
        print("📚 Документация: http://localhost:8080/docs")
        print("🔍 ReDoc: http://localhost:8080/redoc")
        print("📊 Health: http://localhost:8080/health")
        print("📈 Metrics: http://localhost:8080/metrics")
    
    # Shutdown event
    @app.on_event("shutdown")
    async def shutdown_event():
        print("⏹️ FastAPI приложение остановлено")
    
    return app


# Global app instance для импорта
app = None

def get_app() -> FastAPI:
    """Получить экземпляр приложения"""
    global app
    if app is None:
        app = create_app()
    return app
