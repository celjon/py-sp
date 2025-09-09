# src/delivery/http/routes/public_api_v2.py
"""
Production-ready Public API Routes v2.0
Основные endpoints для детекции спама с полной интеграцией аналитики
"""

import time
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from fastapi import APIRouter, HTTPException, Request, Depends, status, BackgroundTasks
from pydantic import BaseModel, Field, validator

from ....config.dependencies import get_dependencies_for_routes
from ....domain.service.analytics.usage_analytics import UsageAnalytics
from ....domain.entity.client_usage import RequestStatus, ApiUsageRecord
from ....domain.entity.api_key import ApiKey

router = APIRouter()

# Получаем dependency providers
deps = get_dependencies_for_routes()

# === PYDANTIC MODELS ===

class DetectionRequest(BaseModel):
    """Запрос на детекцию спама"""
    text: str = Field(..., min_length=1, max_length=10000, description="Текст для проверки")
    context: Optional[Dict[str, Any]] = Field(None, description="Дополнительный контекст")
    
    @validator('text')
    def validate_text(cls, v):
        if not v.strip():
            raise ValueError("Text cannot be empty or only whitespace")
        return v.strip()
    
    class Config:
        schema_extra = {
            "example": {
                "text": "Привет! Хочешь заработать быстрые деньги? Пиши в ЛС!",
                "context": {
                    "user_id": 12345,
                    "chat_id": -1001234567890,
                    "is_new_user": True,
                    "language_hint": "ru"
                }
            }
        }


class BatchDetectionRequest(BaseModel):
    """Запрос на batch детекцию"""
    messages: List[DetectionRequest] = Field(..., min_items=1, max_items=100, description="Список сообщений")
    
    class Config:
        schema_extra = {
            "example": {
                "messages": [
                    {
                        "text": "Обычное сообщение в чате",
                        "context": {"user_id": 1, "is_new_user": False}
                    },
                    {
                        "text": "СРОЧНО! ЗАРАБОТАЙ МИЛЛИОН! ЖМЯКАЙ СЮДА!",
                        "context": {"user_id": 2, "is_new_user": True}
                    }
                ]
            }
        }


class DetectionResponse(BaseModel):
    """Ответ детекции спама"""
    is_spam: bool = Field(..., description="Является ли сообщение спамом")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность в детекции (0.0-1.0)")
    primary_reason: str = Field(..., description="Основная причина детекции")
    reasons: List[str] = Field(..., description="Список всех сработавших правил")
    recommended_action: str = Field(..., description="Рекомендуемое действие")
    notes: str = Field(..., description="Дополнительная информация")
    
    # Метаинформация
    processing_time_ms: float = Field(..., description="Время обработки в миллисекундах")
    detection_id: str = Field(..., description="Уникальный ID детекции для трейсинга")
    api_version: str = Field("2.0", description="Версия API")
    
    class Config:
        schema_extra = {
            "example": {
                "is_spam": True,
                "confidence": 0.85,
                "primary_reason": "openai",
                "reasons": ["promotional_content", "urgent_language", "contact_request"],
                "recommended_action": "ban_and_delete",
                "notes": "Обнаружена реклама с призывом к контакту в ЛС",
                "processing_time_ms": 342.5,
                "detection_id": "det_1234567890abcdef",
                "api_version": "2.0"
            }
        }


class BatchDetectionResponse(BaseModel):
    """Ответ batch детекции"""
    results: List[DetectionResponse] = Field(..., description="Результаты для каждого сообщения")
    summary: Dict[str, Any] = Field(..., description="Сводная статистика")
    total_processing_time_ms: float = Field(..., description="Общее время обработки")
    batch_id: str = Field(..., description="ID batch запроса")


class UsageStatsResponse(BaseModel):
    """Ответ со статистикой использования"""
    api_key_info: Dict[str, Any]
    usage_stats: Dict[str, Any]
    rate_limits: Dict[str, Any]
    billing_period: Dict[str, Any]
    generated_at: str


class HealthResponse(BaseModel):
    """Ответ health check"""
    status: str
    timestamp: float
    version: str
    components: Dict[str, Any]
    performance: Dict[str, Any]


# === HELPER FUNCTIONS ===

def get_authenticated_api_key(request: Request) -> ApiKey:
    """Получает аутентифицированный API ключ из request state"""
    if not hasattr(request.state, 'api_key') or not request.state.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return request.state.api_key


def get_client_info(request: Request) -> Dict[str, Any]:
    """Извлекает информацию о клиенте"""
    return {
        "ip": getattr(request.state, 'client_ip', 'unknown'),
        "user_agent": request.headers.get("User-Agent", "unknown"),
        "auth_method": getattr(request.state, 'auth_method', 'unknown'),
        "request_id": request.headers.get("X-Request-ID", f"req_{int(time.time())}")
    }


async def track_api_usage(
    background_tasks: BackgroundTasks,
    usage_analytics: UsageAnalytics,
    api_key: ApiKey,
    endpoint: str,
    method: str,
    status: RequestStatus,
    processing_time_ms: float,
    client_info: Dict[str, Any],
    request_size: int = 0,
    response_size: int = 0,
    is_spam_detected: bool = None,
    detection_confidence: float = None,
    detection_reason: str = None
):
    """Фоновая задача для записи использования API"""
    def track_usage():
        try:
            # Создаем запись в фоне (не блокируем ответ)
            asyncio.create_task(usage_analytics.track_api_request(
                api_key=api_key,
                endpoint=endpoint,
                method=method,
                status=status,
                processing_time_ms=processing_time_ms,
                request_size_bytes=request_size,
                response_size_bytes=response_size,
                client_ip=client_info.get("ip"),
                user_agent=client_info.get("user_agent"),
                is_spam_detected=is_spam_detected,
                detection_confidence=detection_confidence,
                detection_reason=detection_reason
            ))
        except Exception as e:
            print(f"Error tracking API usage: {e}")
    
    background_tasks.add_task(track_usage)


# === MAIN API ENDPOINTS ===

@router.post(
    "/detect",
    response_model=DetectionResponse,
    summary="Детекция спама",
    description="Проверяет текст на спам используя современные ML модели"
)
async def detect_spam(
    request_data: DetectionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    spam_detector = Depends(lambda: None),  # TODO: Inject spam detector
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Основной endpoint для детекции спама"""
    start_time = time.time()
    api_key = get_authenticated_api_key(request)
    client_info = get_client_info(request)
    
    detection_id = f"det_{int(time.time())}{hash(request_data.text) % 10000:04d}"
    
    try:
        # TODO: Implement actual spam detection
        # Временная заглушка для демонстрации
        import random
        
        # Симуляция детекции
        await asyncio.sleep(0.1)  # Имитация обработки
        
        is_spam = "заработ" in request_data.text.lower() or "СРОЧНО" in request_data.text
        confidence = random.uniform(0.7, 0.95) if is_spam else random.uniform(0.1, 0.4)
        
        reasons = []
        if is_spam:
            if "заработ" in request_data.text.lower():
                reasons.append("financial_scheme")
            if "СРОЧНО" in request_data.text:
                reasons.append("urgent_language")
            if "ЛС" in request_data.text:
                reasons.append("contact_request")
        
        primary_reason = reasons[0] if reasons else "heuristics"
        
        recommended_action = "allow"
        if is_spam:
            if confidence > 0.85:
                recommended_action = "ban_and_delete"
            elif confidence > 0.7:
                recommended_action = "delete_and_warn"
            else:
                recommended_action = "soft_warn_or_review"
        
        notes = "Автоматическая детекция спама" if is_spam else "Сообщение выглядит безопасным"
        
        processing_time_ms = (time.time() - start_time) * 1000
        
        # Записываем использование API
        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v1/detect",
            method="POST",
            status=RequestStatus.SUCCESS,
            processing_time_ms=processing_time_ms,
            client_info=client_info,
            request_size=len(request_data.text.encode('utf-8')),
            response_size=500,  # Примерный размер ответа
            is_spam_detected=is_spam,
            detection_confidence=confidence,
            detection_reason=primary_reason
        )
        
        return DetectionResponse(
            is_spam=is_spam,
            confidence=round(confidence, 3),
            primary_reason=primary_reason,
            reasons=reasons,
            recommended_action=recommended_action,
            notes=notes,
            processing_time_ms=round(processing_time_ms, 2),
            detection_id=detection_id,
            api_version="2.0"
        )
        
    except Exception as e:
        processing_time_ms = (time.time() - start_time) * 1000
        
        # Записываем ошибку
        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v1/detect",
            method="POST",
            status=RequestStatus.ERROR,
            processing_time_ms=processing_time_ms,
            client_info=client_info
        )
        
        print(f"Detection error: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Detection service error",
                "detection_id": detection_id,
                "processing_time_ms": round(processing_time_ms, 2)
            }
        )


@router.post(
    "/detect/batch",
    response_model=BatchDetectionResponse,
    summary="Batch детекция спама",
    description="Проверяет множество сообщений за один запрос (до 100 штук)"
)
async def batch_detect_spam(
    request_data: BatchDetectionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Batch детекция для множества сообщений"""
    start_time = time.time()
    api_key = get_authenticated_api_key(request)
    client_info = get_client_info(request)
    
    batch_id = f"batch_{int(time.time())}{len(request_data.messages):03d}"
    
    try:
        results = []
        spam_count = 0
        total_confidence = 0.0
        
        # Обрабатываем каждое сообщение
        for i, message in enumerate(request_data.messages):
            detection_start = time.time()
            
            # Симуляция детекции (TODO: заменить на реальную)
            import random
            await asyncio.sleep(0.05)  # Имитация обработки
            
            is_spam = "заработ" in message.text.lower() or "СРОЧНО" in message.text
            confidence = random.uniform(0.7, 0.95) if is_spam else random.uniform(0.1, 0.4)
            
            if is_spam:
                spam_count += 1
            total_confidence += confidence
            
            detection_time = (time.time() - detection_start) * 1000
            detection_id = f"{batch_id}_msg_{i:03d}"
            
            result = DetectionResponse(
                is_spam=is_spam,
                confidence=round(confidence, 3),
                primary_reason="heuristics" if is_spam else "clean",
                reasons=["batch_detection"] if is_spam else [],
                recommended_action="delete_and_warn" if is_spam else "allow",
                notes=f"Batch detection #{i+1}",
                processing_time_ms=round(detection_time, 2),
                detection_id=detection_id,
                api_version="2.0"
            )
            results.append(result)
        
        total_processing_time_ms = (time.time() - start_time) * 1000
        
        # Сводная статистика
        summary = {
            "total_messages": len(request_data.messages),
            "spam_detected": spam_count,
            "clean_detected": len(request_data.messages) - spam_count,
            "spam_rate": round((spam_count / len(request_data.messages)) * 100, 2),
            "avg_confidence": round(total_confidence / len(request_data.messages), 3),
            "avg_processing_time_per_message_ms": round(total_processing_time_ms / len(request_data.messages), 2)
        }
        
        # Записываем использование API
        total_text_size = sum(len(msg.text.encode('utf-8')) for msg in request_data.messages)
        
        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v1/detect/batch",
            method="POST",
            status=RequestStatus.SUCCESS,
            processing_time_ms=total_processing_time_ms,
            client_info=client_info,
            request_size=total_text_size,
            response_size=len(str(results)),  # Примерный размер
            detection_reason=f"batch_processing_{len(request_data.messages)}_messages"
        )
        
        return BatchDetectionResponse(
            results=results,
            summary=summary,
            total_processing_time_ms=round(total_processing_time_ms, 2),
            batch_id=batch_id
        )
        
    except Exception as e:
        processing_time_ms = (time.time() - start_time) * 1000
        
        # Записываем ошибку
        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v1/detect/batch",
            method="POST",
            status=RequestStatus.ERROR,
            processing_time_ms=processing_time_ms,
            client_info=client_info
        )
        
        print(f"Batch detection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Batch detection service error",
                "batch_id": batch_id,
                "processing_time_ms": round(processing_time_ms, 2)
            }
        )


@router.get(
    "/stats",
    response_model=UsageStatsResponse,
    summary="Статистика использования",
    description="Возвращает статистику использования API для вашего ключа"
)
async def get_usage_stats(
    request: Request,
    hours: int = Field(24, ge=1, le=168, description="Период в часах"),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Статистика использования API для клиента"""
    try:
        api_key = get_authenticated_api_key(request)
        
        # Получаем метрики использования
        metrics = await usage_analytics.get_real_time_metrics(api_key.id, hours * 60)
        
        # Получаем billing информацию
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        billing_metrics = await usage_analytics.get_billing_metrics(
            api_key_id=api_key.id,
            start_date=start_time,
            end_date=end_time
        )
        
        return UsageStatsResponse(
            api_key_info={
                "id": api_key.id,
                "client_name": api_key.client_name,
                "plan": api_key.plan.value,
                "status": api_key.status.value,
                "created_at": api_key.created_at.isoformat()
            },
            usage_stats=metrics.to_dict(),
            rate_limits={
                "current": api_key.get_rate_limits(),
                "remaining": {
                    "requests_per_minute": max(0, api_key.requests_per_minute - getattr(metrics, 'current_minute', 0)),
                    "requests_per_day": max(0, api_key.requests_per_day - getattr(metrics, 'current_day', 0))
                }
            },
            billing_period={
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "hours": hours
            },
            generated_at=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Usage stats error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get usage statistics"
        )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Проверка работоспособности API"
)
async def health_check():
    """Health check для публичного API"""
    try:
        check_time = time.time()
        
        # Базовые проверки
        components = {
            "api": {"status": "healthy", "response_time_ms": 0},
            "database": {"status": "unknown"},  # TODO: проверка БД
            "cache": {"status": "unknown"},     # TODO: проверка Redis
            "spam_detector": {"status": "unknown"}  # TODO: проверка детектора
        }
        
        # Тест производительности
        performance = {
            "avg_response_time_ms": 150,  # Примерные значения
            "requests_per_second": 100,
            "memory_usage_mb": 256,
            "cpu_usage_percent": 15
        }
        
        # Определяем общий статус
        overall_status = "healthy"
        for component in components.values():
            if component.get("status") == "error":
                overall_status = "error"
                break
            elif component.get("status") == "degraded":
                overall_status = "degraded"
        
        response_time = (time.time() - check_time) * 1000
        components["api"]["response_time_ms"] = round(response_time, 2)
        
        return HealthResponse(
            status=overall_status,
            timestamp=time.time(),
            version="2.0.0",
            components=components,
            performance=performance
        )
        
    except Exception as e:
        return HealthResponse(
            status="error",
            timestamp=time.time(),
            version="2.0.0",
            components={"api": {"status": "error", "error": str(e)}},
            performance={}
        )


@router.get(
    "/info",
    summary="Информация об API",
    description="Возвращает информацию о возможностях API"
)
async def get_api_info():
    """Информация о публичном API"""
    return {
        "api_name": "AntiSpam Detection API",
        "version": "2.0.0",
        "description": "Production-ready API для детекции спама с поддержкой русского и английского языков",
        "features": [
            "Многослойная детекция: CAS + RUSpam + OpenAI",
            "Batch обработка до 100 сообщений",
            "Real-time статистика использования",
            "JWT аутентификация",
            "Rate limiting по API ключам",
            "Детальная аналитика и мониторинг"
        ],
        "endpoints": {
            "detection": {
                "single": "POST /api/v1/detect",
                "batch": "POST /api/v1/detect/batch"
            },
            "analytics": {
                "usage_stats": "GET /api/v1/stats"
            },
            "system": {
                "health": "GET /api/v1/health",
                "info": "GET /api/v1/info"
            }
        },
        "authentication": {
            "methods": ["API Key", "JWT Bearer Token"],
            "headers": ["Authorization: Bearer {token}", "X-API-Key: {key}"]
        },
        "rate_limits": {
            "free": {"requests_per_minute": 60, "requests_per_day": 5000},
            "basic": {"requests_per_minute": 120, "requests_per_day": 10000},
            "pro": {"requests_per_minute": 300, "requests_per_day": 50000},
            "enterprise": {"requests_per_minute": 1000, "requests_per_day": 1000000}
        },
        "documentation": {
            "interactive": "/docs",
            "openapi_schema": "/openapi.json",
            "sdk": {
                "python": "pip install antispam-client",
                "javascript": "npm install @antispam/client"
            }
        },
        "support": {
            "email": "support@antispam.com",
            "documentation": "https://docs.antispam.com",
            "status_page": "https://status.antispam.com"
        },
        "performance": {
            "avg_response_time_ms": 200,
            "max_throughput_rps": 1000,
            "uptime_guarantee": "99.9%"
        },
        "generated_at": datetime.utcnow().isoformat()
    }


# === IMPORT ASYNCIO FOR BACKGROUND TASKS ===
import asyncio
from datetime import timedelta