from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
import time
import sys

router = APIRouter()

# Pydantic модели для API
class DetectionContext(BaseModel):
    """Контекст для детекции спама"""
    user_id: Optional[int] = Field(None, description="ID пользователя Telegram")
    chat_id: Optional[int] = Field(None, description="ID чата Telegram") 
    is_new_user: bool = Field(False, description="Является ли пользователь новым")
    is_admin_or_owner: bool = Field(False, description="Является ли пользователь админом")
    language: Optional[str] = Field(None, description="Язык сообщения (ru/en/auto)")
    previous_warnings: int = Field(0, description="Количество предыдущих предупреждений")
    
    class Config:
        schema_extra = {
            "example": {
                "user_id": 12345,
                "chat_id": -1001234567,
                "is_new_user": True,
                "is_admin_or_owner": False,
                "language": "ru",
                "previous_warnings": 0
            }
        }


class DetectionRequest(BaseModel):
    """Запрос на детекцию спама"""
    text: str = Field(..., min_length=1, max_length=4096, description="Текст для проверки")
    context: Optional[DetectionContext] = Field(None, description="Контекст сообщения")
    
    @validator('text')
    def validate_text(cls, v):
        if not v or not v.strip():
            raise ValueError('Text cannot be empty')
        return v.strip()
    
    class Config:
        schema_extra = {
            "example": {
                "text": "🔥🔥🔥 Заработок! Детали в ЛС!",
                "context": {
                    "user_id": 12345,
                    "is_new_user": True,
                    "language": "ru"
                }
            }
        }


class BatchDetectionRequest(BaseModel):
    """Запрос на batch детекцию спама"""
    messages: List[DetectionRequest] = Field(..., min_items=1, max_items=100, description="Список сообщений для проверки")
    
    class Config:
        schema_extra = {
            "example": {
                "messages": [
                    {
                        "text": "🔥🔥🔥 Заработок! Детали в ЛС!",
                        "context": {"is_new_user": True}
                    },
                    {
                        "text": "Привет, как дела?",
                        "context": {"is_new_user": False}
                    }
                ]
            }
        }


class DetectionResponse(BaseModel):
    """Ответ на детекцию спама"""
    is_spam: bool = Field(..., description="Является ли сообщение спамом")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность детекции (0.0-1.0)")
    reason: str = Field(..., description="Основная причина детекции")
    action: str = Field(..., description="Рекомендуемое действие")
    processing_time_ms: float = Field(..., description="Время обработки в миллисекундах")
    details: Optional[str] = Field(None, description="Дополнительные детали")
    detected_patterns: Optional[List[str]] = Field(None, description="Обнаруженные паттерны спама")
    
    class Config:
        schema_extra = {
            "example": {
                "is_spam": True,
                "confidence": 0.87,
                "reason": "heuristics",
                "action": "ban_and_delete", 
                "processing_time_ms": 125.5,
                "details": "too many emojis; spam patterns detected",
                "detected_patterns": ["excessive_emojis", "spam_phrases"]
            }
        }


class BatchDetectionResponse(BaseModel):
    """Ответ на batch детекцию"""
    results: List[DetectionResponse] = Field(..., description="Результаты детекции")
    total_processed: int = Field(..., description="Количество обработанных сообщений")
    total_processing_time_ms: float = Field(..., description="Общее время обработки")
    
    class Config:
        schema_extra = {
            "example": {
                "results": [
                    {"is_spam": True, "confidence": 0.87, "reason": "heuristics", "action": "ban_and_delete", "processing_time_ms": 125.5},
                    {"is_spam": False, "confidence": 0.15, "reason": "heuristics", "action": "allow", "processing_time_ms": 45.2}
                ],
                "total_processed": 2,
                "total_processing_time_ms": 170.7
            }
        }


class ApiErrorResponse(BaseModel):
    """Стандартный ответ с ошибкой"""
    error: str = Field(..., description="Тип ошибки")
    message: str = Field(..., description="Описание ошибки")
    timestamp: float = Field(..., description="Временная метка")
    request_id: Optional[str] = Field(None, description="ID запроса для отладки")


def get_dependencies(request: Request) -> Dict[str, Any]:
    """Получение зависимостей из app state"""
    return request.app.state.dependencies


def get_api_key(request: Request):
    """Получение API ключа из middleware"""
    if not hasattr(request.state, 'api_key') or not request.state.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required"
        )
    return request.state.api_key


def get_client_info(request: Request) -> Dict[str, str]:
    """Получение информации о клиенте"""
    return {
        "ip": getattr(request.state, 'client_ip', 'unknown'),
        "user_agent": request.headers.get("User-Agent", "unknown")
    }


@router.post(
    "/detect",
    response_model=DetectionResponse,
    summary="Детекция спама",
    description="Проверяет текст на спам с помощью многослойной системы детекции"
)
async def detect_spam(
    detection_request: DetectionRequest,
    request: Request,
    api_key=Depends(get_api_key),
    client_info=Depends(get_client_info),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Основной endpoint для детекции спама"""
    try:
        # Получаем use case
        detect_spam_usecase = dependencies.get("detect_spam_usecase")
        if not detect_spam_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Spam detection service unavailable"
            )
        
        # Подготавливаем запрос
        from ....domain.usecase.api.detect_spam import DetectionRequest as DomainRequest
        
        domain_request = DomainRequest(
            text=detection_request.text,
            context=detection_request.context.dict() if detection_request.context else {},
            client_ip=client_info["ip"],
            user_agent=client_info["user_agent"],
            request_size_bytes=len(str(detection_request.dict()))
        )
        
        # Выполняем детекцию
        result = await detect_spam_usecase.execute(api_key, domain_request)
        
        # Возвращаем ответ
        return DetectionResponse(**result.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Detection API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Detection failed: {str(e)}"
        )


@router.post(
    "/detect/batch",
    response_model=BatchDetectionResponse,
    summary="Batch детекция спама", 
    description="Проверяет несколько сообщений одновременно (до 100 сообщений)"
)
async def detect_spam_batch(
    batch_request: BatchDetectionRequest,
    request: Request,
    api_key=Depends(get_api_key),
    client_info=Depends(get_client_info),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Batch endpoint для детекции спама"""
    try:
        # Получаем use case
        batch_detect_usecase = dependencies.get("batch_detect_usecase")
        if not batch_detect_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Batch detection service unavailable"
            )
        
        # Подготавливаем запросы
        from ....domain.usecase.api.detect_spam import DetectionRequest as DomainRequest
        
        domain_requests = []
        for msg in batch_request.messages:
            domain_request = DomainRequest(
                text=msg.text,
                context=msg.context.dict() if msg.context else {},
                client_ip=client_info["ip"],
                user_agent=client_info["user_agent"],
                request_size_bytes=len(str(msg.dict()))
            )
            domain_requests.append(domain_request)
        
        # Выполняем batch детекцию
        start_time = time.time()
        results = await batch_detect_usecase.execute(api_key, domain_requests)
        total_time = (time.time() - start_time) * 1000
        
        # Формируем ответ
        response_results = [DetectionResponse(**result.to_dict()) for result in results]
        
        return BatchDetectionResponse(
            results=response_results,
            total_processed=len(results),
            total_processing_time_ms=round(total_time, 2)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Batch detection API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch detection failed: {str(e)}"
        )


@router.get(
    "/detectors",
    summary="Список детекторов",
    description="Возвращает информацию о доступных детекторах спама"
)
async def get_detectors(
    api_key=Depends(get_api_key),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Информация о доступных детекторах"""
    try:
        spam_detector = dependencies.get("spam_detector")
        if not spam_detector:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Spam detector service unavailable"
            )
        
        # Получаем информацию о детекторах
        available_detectors = await spam_detector.get_available_detectors()
        health_info = await spam_detector.health_check()
        
        return {
            "available_detectors": available_detectors,
            "detector_status": health_info.get("detectors", {}),
            "overall_status": health_info.get("status", "unknown"),
            "timestamp": time.time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Detectors info API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get detectors info: {str(e)}"
        )


@router.get(
    "/stats",
    summary="Статистика использования",
    description="Возвращает статистику использования API для текущего ключа"
)
async def get_usage_stats(
    hours: int = 24,
    api_key=Depends(get_api_key),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Статистика использования API ключа"""
    try:
        usage_repo = dependencies.get("usage_repository")
        if not usage_repo:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Usage statistics service unavailable"
            )
        
        # Получаем статистику
        from ....domain.entity.client_usage import UsagePeriod
        from datetime import datetime, timedelta
        
        start_time = datetime.utcnow() - timedelta(hours=hours)
        usage_stats = await usage_repo.get_usage_stats(
            api_key_id=api_key.id,
            period=UsagePeriod.HOUR,
            start_time=start_time
        )
        
        # Получаем дополнительную статистику
        hourly_stats = await usage_repo.get_hourly_usage_stats(api_key.id, days=7)
        top_endpoints = await usage_repo.get_top_endpoints(api_key.id, hours=hours)
        
        return {
            "api_key_info": {
                "id": api_key.id,
                "client_name": api_key.client_name,
                "plan": api_key.plan.value,
                "rate_limits": api_key.get_rate_limits()
            },
            "usage_stats": usage_stats.to_dict(),
            "hourly_breakdown": hourly_stats[:24],  # Последние 24 часа
            "top_endpoints": top_endpoints,
            "period_hours": hours,
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Usage stats API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get usage stats: {str(e)}"
        )


@router.get(
    "/health",
    summary="Health check",
    description="Проверка состояния API"
)
async def health_check(
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Health check для публичного API"""
    try:
        spam_detector = dependencies.get("spam_detector")
        postgres_client = dependencies.get("postgres_client")
        redis_cache = dependencies.get("redis_cache")
        
        health_status = {
            "status": "healthy",
            "timestamp": time.time(),
            "version": "2.0.0",
            "services": {}
        }
        
        # Проверяем детектор спама
        if spam_detector:
            detector_health = await spam_detector.health_check()
            health_status["services"]["spam_detector"] = {
                "status": detector_health.get("status", "unknown"),
                "detectors": list(detector_health.get("detectors", {}).keys())
            }
        
        # Проверяем PostgreSQL
        if postgres_client:
            try:
                async with postgres_client.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                health_status["services"]["database"] = {"status": "healthy"}
            except Exception as e:
                health_status["services"]["database"] = {"status": "unhealthy", "error": str(e)}
                health_status["status"] = "degraded"
        
        # Проверяем Redis
        if redis_cache:
            try:
                await redis_cache.set("health_check", "ok", ttl=60)
                health_status["services"]["cache"] = {"status": "healthy"}
            except Exception as e:
                health_status["services"]["cache"] = {"status": "unhealthy", "error": str(e)}
                health_status["status"] = "degraded"
        
        return health_status
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": time.time(),
            "error": str(e)
        }


# Error handlers
@router.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Обработчик HTTP ошибок"""
    return {
        "error": exc.detail,
        "status_code": exc.status_code,
        "timestamp": time.time(),
        "path": str(request.url.path)
    }


@router.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Обработчик общих ошибок"""
    print(f"Unhandled API error: {exc}")
    return {
        "error": "Internal server error",
        "message": "An unexpected error occurred",
        "timestamp": time.time(),
        "path": str(request.url.path)
    }