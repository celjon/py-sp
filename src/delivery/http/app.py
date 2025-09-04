from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import time
from typing import Dict, Any, Optional
import asyncio

from ...config.config import load_config
from .routers import spam_check, admin, stats
from .middlewares.rate_limit import RateLimitMiddleware
from .middlewares.auth import get_current_user


def create_app(dependencies: Dict[str, Any] = None) -> FastAPI:
    """Создание FastAPI приложения"""
    
    config = load_config()
    
    app = FastAPI(
        title="AntiSpam Bot API",
        description="Многослойная система детекции спама для Telegram",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
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
    
    # Rate limiting middleware
    app.add_middleware(RateLimitMiddleware)
    
    # Включаем роутеры
    app.include_router(spam_check.router, prefix="/api/v1", tags=["spam-detection"])
    app.include_router(stats.router, prefix="/api/v1", tags=["statistics"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    
    # Health check endpoint
    @app.get("/health")
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
                    "detectors": health.get("detectors", {}),
                    "api": "operational"
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
    @app.get("/metrics")
    async def metrics():
        """Метрики в формате Prometheus"""
        try:
            dependencies = app.state.dependencies
            message_repo = dependencies.get("message_repository")
            
            if not message_repo:
                raise HTTPException(status_code=503, detail="Database not available")
            
            # Получаем статистику за последние 24 часа
            global_stats = await message_repo.get_global_stats(hours=24)
            
            metrics_text = f"""# HELP spam_messages_total Total number of spam messages detected
# TYPE spam_messages_total counter
spam_messages_total {global_stats['spam_messages']}

# HELP clean_messages_total Total number of clean messages processed  
# TYPE clean_messages_total counter
clean_messages_total {global_stats['clean_messages']}

# HELP spam_detection_rate Spam detection rate (0-1)
# TYPE spam_detection_rate gauge
spam_detection_rate {global_stats['spam_percentage'] / 100}

# HELP active_chats_total Number of active chats
# TYPE active_chats_total gauge
active_chats_total {global_stats['active_chats']}

# HELP active_users_total Number of active users
# TYPE active_users_total gauge
active_users_total {global_stats['active_users']}
"""
            
            return JSONResponse(
                content=metrics_text,
                media_type="text/plain"
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Metrics error: {str(e)}")
    
    # Root endpoint
    @app.get("/")
    async def root():
        """Корневой endpoint"""
        return {
            "name": "AntiSpam Bot API",
            "version": "2.0.0",
            "description": "Многослойная система детекции спама",
            "docs": "/docs",
            "health": "/health",
            "metrics": "/metrics",
            "endpoints": {
                "check_spam": "POST /api/v1/check",
                "statistics": "GET /api/v1/stats",
                "admin": "GET /api/v1/admin/"
            }
        }
    
    # Error handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "timestamp": time.time(),
                "path": str(request.url)
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "timestamp": time.time(),
                "path": str(request.url)
            }
        )
    
    return app


# Global app instance для импорта
app = None

def get_app() -> FastAPI:
    """Получить экземпляр приложения"""
    global app
    if app is None:
        app = create_app()
    return app