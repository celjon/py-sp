# src/delivery/http/routes/public_api_v2.py
"""
Production-ready Public API Routes v2.0 - РЕАЛЬНАЯ детекция спама
Основные endpoints для детекции спама с полной интеграцией ensemble detector
"""

import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Union
from fastapi import APIRouter, HTTPException, Request, Depends, status, BackgroundTasks, Query
from pydantic import BaseModel, Field, validator
import logging

from ....config.dependencies import get_dependencies_for_routes
from ....domain.analytics.usage_analytics import UsageAnalytics
from ....domain.usecase.spam_detection.check_message import CheckMessageUseCase
from ....domain.entity.message import Message
from ....domain.entity.client_usage import RequestStatus, ApiUsageRecord
from ....domain.entity.api_key import ApiKey
from ....domain.service.billing.billing_service import BillingService, get_billing_service
from ....domain.service.billing.token_calculator import TokenUsage

logger = logging.getLogger(__name__)
router = APIRouter()

# Получаем dependency providers
deps = get_dependencies_for_routes()

# === PYDANTIC MODELS ===


class DetectionRequest(BaseModel):
    """Запрос на детекцию спама"""

    text: str = Field(..., min_length=1, max_length=10000, description="Текст для проверки")
    context: Optional[Dict[str, Any]] = Field(None, description="Дополнительный контекст")

    @validator("text")
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
                    "language_hint": "ru",
                },
            }
        }


class BatchDetectionRequest(BaseModel):
    """Запрос на batch детекцию"""

    messages: List[DetectionRequest] = Field(
        ..., min_items=1, max_items=100, description="Список сообщений"
    )

    class Config:
        schema_extra = {
            "example": {
                "messages": [
                    {
                        "text": "Обычное сообщение в чате",
                        "context": {"user_id": 1, "is_new_user": False},
                    },
                    {
                        "text": "СРОЧНО! ЗАРАБОТАЙ МИЛЛИОН! ЖМЯКАЙ СЮДА!",
                        "context": {"user_id": 2, "is_new_user": True},
                    },
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
                "primary_reason": "openai_detected",
                "reasons": ["promotional_content", "urgent_language", "contact_request"],
                "recommended_action": "ban_and_delete",
                "notes": "Обнаружена реклама с призывом к контакту в ЛС",
                "processing_time_ms": 342.5,
                "detection_id": "det_1234567890abcdef",
                "api_version": "2.0",
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


class BillingResponse(BaseModel):
    """Ответ с информацией о биллинге"""

    api_key_info: Dict[str, Any]
    billing_summary: Dict[str, Any]
    current_prices: Dict[str, Any]
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
    """Получает аутентифицированный API ключ из request"""
    api_key = getattr(request.state, "api_key", None)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")
    return api_key


def get_client_info(request: Request) -> Dict[str, Any]:
    """Извлекает информацию о клиенте"""
    client_host = getattr(request.client, "host", "unknown") if request.client else "unknown"

    return {
        "ip": client_host,
        "user_agent": request.headers.get("User-Agent", "unknown"),
        "method": request.method,
        "endpoint": str(request.url.path),
        "timestamp": time.time(),
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
    detection_reason: str = None,
):
    """Записывает использование API в фоновом режиме"""

    def track_usage():
        try:
            usage_record = ApiUsageRecord(
                api_key_id=api_key.id,
                endpoint=endpoint,
                method=method,
                status=status,
                processing_time_ms=processing_time_ms,
                request_size_bytes=request_size,
                response_size_bytes=response_size,
                client_ip=client_info["ip"],
                user_agent=client_info["user_agent"],
                detection_reason=detection_reason,
                timestamp=datetime.now(timezone.utc),
            )

            # Добавляем в background task
            background_tasks.add_task(usage_analytics.record_api_usage, usage_record)
        except Exception as e:
            logger.error(f"Failed to track API usage: {e}")

    track_usage()


async def track_billing(
    background_tasks: BackgroundTasks,
    billing_service: BillingService,
    api_key: ApiKey,
    detection_result,
    request_id: str = None,
):
    """Записывает биллинг в фоновом режиме"""

    def track_billing_cost():
        try:
            # Извлекаем информацию о токенах из результата детекции
            token_usage = None
            for detector_result in detection_result.detector_results:
                if detector_result.detector_name == "OpenAI" and detector_result.token_usage:
                    token_usage = TokenUsage(
                        input_tokens=detector_result.token_usage.get("input_tokens", 0),
                        output_tokens=detector_result.token_usage.get("output_tokens", 0),
                    )
                    break

            # Рассчитываем стоимость
            billing_record = billing_service.calculate_request_cost(
                api_key=api_key,
                detection_result=detection_result,
                token_usage=token_usage,
                request_id=request_id,
            )

            logger.info(
                f"💰 Billing tracked: {billing_record.cost_rubles:.2f} RUB for API key {api_key.id}"
            )

        except Exception as e:
            logger.error(f"Failed to track billing: {e}")

    track_billing_cost()


# === API ENDPOINTS ===


@router.post(
    "/detect",
    response_model=DetectionResponse,
    summary="Детекция спама",
    description="Проверяет сообщение на спам с помощью ensemble детектора (CAS + RUSpam + OpenAI)",
)
async def detect_spam(
    request_data: DetectionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"]),
    check_message_usecase: CheckMessageUseCase = Depends(deps["get_check_message_usecase"]),
    billing_service: BillingService = Depends(get_billing_service),
):
    """
    РЕАЛЬНАЯ детекция спама через production ensemble detector
    """
    start_time = time.time()
    api_key = get_authenticated_api_key(request)
    client_info = get_client_info(request)

    detection_id = f"det_{uuid.uuid4().hex[:16]}"

    logger.info(
        f"🔍 Detection request {detection_id}: '{request_data.text[:50]}{'...' if len(request_data.text) > 50 else ''}'"
    )

    try:
        # Создаем domain объект Message
        message = Message(
            id=None,  # API message
            text=request_data.text,
            user_id=request_data.context.get("user_id") if request_data.context else None,
            chat_id=request_data.context.get("chat_id") if request_data.context else None,
            timestamp=datetime.now(timezone.utc),
        )

        # Подготавливаем контекст пользователя
        user_context = request_data.context or {}
        user_context.update(
            {
                "api_request": True,
                "client_ip": client_info["ip"],
                "api_key_plan": api_key.plan.value,
            }
        )

        # ВЫПОЛНЯЕМ РЕАЛЬНУЮ ДЕТЕКЦИЮ через CheckMessageUseCase
        detection_result = await check_message_usecase.execute(message)

        processing_time_ms = (time.time() - start_time) * 1000

        # Логируем результат
        result_emoji = "🚨" if detection_result.is_spam else "✅"
        logger.info(
            f"{result_emoji} Detection {detection_id}: spam={detection_result.is_spam}, confidence={detection_result.overall_confidence:.3f}, время={processing_time_ms:.1f}ms"
        )

        # Записываем использование API
        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v2/detect",
            method="POST",
            status=RequestStatus.SUCCESS,
            processing_time_ms=processing_time_ms,
            client_info=client_info,
            request_size=len(request_data.text.encode("utf-8")),
            response_size=0,  # Будет обновлено после сериализации
            detection_reason=(
                detection_result.primary_reason.value
                if detection_result.primary_reason
                else "unknown"
            ),
        )

        # Записываем биллинг
        await track_billing(
            background_tasks=background_tasks,
            billing_service=billing_service,
            api_key=api_key,
            detection_result=detection_result,
            request_id=detection_id,
        )

        # Формируем ответ API
        reasons = []
        if detection_result.detector_results:
            for detector_result in detection_result.detector_results:
                if detector_result.is_spam and detector_result.details:
                    reasons.append(detector_result.details)

        return DetectionResponse(
            is_spam=detection_result.is_spam,
            confidence=round(detection_result.overall_confidence, 3),
            primary_reason=(
                detection_result.primary_reason.value
                if detection_result.primary_reason
                else "unknown"
            ),
            reasons=reasons,
            recommended_action=detection_result.recommended_action,
            notes=detection_result.notes,
            processing_time_ms=round(processing_time_ms, 2),
            detection_id=detection_id,
            api_version="2.0",
        )

    except Exception as e:
        processing_time_ms = (time.time() - start_time) * 1000

        # Записываем ошибку
        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v2/detect",
            method="POST",
            status=RequestStatus.ERROR,
            processing_time_ms=processing_time_ms,
            client_info=client_info,
        )

        logger.error(f"Detection error {detection_id}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Detection service error",
                "detection_id": detection_id,
                "processing_time_ms": round(processing_time_ms, 2),
            },
        )


@router.post(
    "/detect/batch",
    response_model=BatchDetectionResponse,
    summary="Batch детекция спама",
    description="Проверяет множество сообщений за один запрос (до 100 штук) используя РЕАЛЬНУЮ детекцию",
)
async def batch_detect_spam(
    request_data: BatchDetectionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"]),
    check_message_usecase: CheckMessageUseCase = Depends(deps["get_check_message_usecase"]),
):
    """РЕАЛЬНАЯ batch детекция через production ensemble detector"""
    start_time = time.time()
    api_key = get_authenticated_api_key(request)
    client_info = get_client_info(request)

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"

    logger.info(f"🔍 Batch detection {batch_id}: {len(request_data.messages)} сообщений")

    try:
        results = []
        spam_count = 0
        total_confidence = 0.0
        detection_times = []

        # Обрабатываем каждое сообщение РЕАЛЬНОЙ детекцией
        for i, message_req in enumerate(request_data.messages):
            detection_start = time.time()

            try:
                # Создаем domain объект Message
                message = Message(
                    id=None,  # API message
                    text=message_req.text,
                    user_id=message_req.context.get("user_id") if message_req.context else None,
                    chat_id=message_req.context.get("chat_id") if message_req.context else None,
                    timestamp=datetime.now(timezone.utc),
                )

                # Подготавливаем контекст
                user_context = message_req.context or {}
                user_context.update(
                    {
                        "api_request": True,
                        "batch_request": True,
                        "batch_id": batch_id,
                        "message_index": i,
                        "client_ip": client_info["ip"],
                        "api_key_plan": api_key.plan.value,
                    }
                )

                # ВЫПОЛНЯЕМ РЕАЛЬНУЮ ДЕТЕКЦИЮ
                detection_result = await check_message_usecase.execute(message)

                detection_time_ms = (time.time() - detection_start) * 1000
                detection_times.append(detection_time_ms)

                # Формируем результат
                if detection_result.is_spam:
                    spam_count += 1

                total_confidence += detection_result.overall_confidence

                detection_id = f"{batch_id}_msg_{i:03d}"

                # Собираем reasons из detector results
                reasons = []
                if detection_result.detector_results:
                    for detector_result in detection_result.detector_results:
                        if detector_result.is_spam and detector_result.details:
                            reasons.append(detector_result.details)

                result = DetectionResponse(
                    is_spam=detection_result.is_spam,
                    confidence=round(detection_result.overall_confidence, 3),
                    primary_reason=(
                        detection_result.primary_reason.value
                        if detection_result.primary_reason
                        else "unknown"
                    ),
                    reasons=reasons,
                    recommended_action=detection_result.recommended_action,
                    notes=detection_result.notes,
                    processing_time_ms=round(detection_time_ms, 2),
                    detection_id=detection_id,
                    api_version="2.0",
                )
                results.append(result)

                # Логируем каждый результат
                result_emoji = "🚨" if detection_result.is_spam else "✅"
                logger.debug(
                    f"{result_emoji} Batch msg {i}: spam={detection_result.is_spam}, conf={detection_result.overall_confidence:.3f}"
                )

            except Exception as e:
                # Обработка ошибки отдельного сообщения
                logger.error(f"❌ Batch message {i} error: {e}")

                detection_time_ms = (time.time() - detection_start) * 1000
                detection_times.append(detection_time_ms)

                # Fallback результат
                result = DetectionResponse(
                    is_spam=False,
                    confidence=0.0,
                    primary_reason="detection_error",
                    reasons=[f"Error: {str(e)}"],
                    recommended_action="allow",
                    notes=f"Ошибка детекции сообщения #{i}: {str(e)}",
                    processing_time_ms=round(detection_time_ms, 2),
                    detection_id=f"{batch_id}_msg_{i:03d}_error",
                    api_version="2.0",
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
            "avg_processing_time_per_message_ms": round(
                sum(detection_times) / len(detection_times), 2
            ),
            "max_processing_time_ms": round(max(detection_times) if detection_times else 0, 2),
            "min_processing_time_ms": round(min(detection_times) if detection_times else 0, 2),
        }

        # Записываем использование API
        total_text_size = sum(len(msg.text.encode("utf-8")) for msg in request_data.messages)

        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v2/detect/batch",
            method="POST",
            status=RequestStatus.SUCCESS,
            processing_time_ms=total_processing_time_ms,
            client_info=client_info,
            request_size=total_text_size,
            response_size=len(str(results)),  # Примерный размер
            detection_reason=f"batch_processing_{len(request_data.messages)}_messages",
        )

        logger.info(
            f"✅ Batch detection {batch_id} завершен: {spam_count}/{len(request_data.messages)} спам, время={total_processing_time_ms:.1f}ms"
        )

        return BatchDetectionResponse(
            results=results,
            summary=summary,
            total_processing_time_ms=round(total_processing_time_ms, 2),
            batch_id=batch_id,
        )

    except Exception as e:
        processing_time_ms = (time.time() - start_time) * 1000

        # Записываем ошибку
        await track_api_usage(
            background_tasks=background_tasks,
            usage_analytics=usage_analytics,
            api_key=api_key,
            endpoint="/api/v2/detect/batch",
            method="POST",
            status=RequestStatus.ERROR,
            processing_time_ms=processing_time_ms,
            client_info=client_info,
        )

        logger.error(f"Batch detection error {batch_id}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Batch detection service error",
                "batch_id": batch_id,
                "processing_time_ms": round(processing_time_ms, 2),
            },
        )


@router.get(
    "/stats",
    response_model=UsageStatsResponse,
    summary="Статистика использования",
    description="Возвращает статистику использования API для вашего ключа",
)
async def get_usage_stats(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Период в часах"),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"]),
):
    """Статистика использования API для клиента"""
    try:
        api_key = get_authenticated_api_key(request)

        logger.info(f"📊 Запрос статистики для API key {api_key.id} за {hours} часов")

        # Получаем метрики использования
        try:
            metrics = await usage_analytics.get_real_time_metrics(api_key.id, hours * 60)
        except Exception as e:
            logger.error(f"Failed to get real-time metrics: {e}")
            # Fallback метрики
            metrics = {
                "total_requests": 0,
                "spam_detected": 0,
                "avg_processing_time_ms": 0,
                "error_rate": 0,
            }

        # Получаем billing информацию
        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours)
            billing_metrics = await usage_analytics.get_billing_metrics(
                api_key_id=api_key.id, start_date=start_time, end_date=end_time
            )
        except Exception as e:
            logger.error(f"Failed to get billing metrics: {e}")
            # Fallback billing
            billing_metrics = {
                "period_start": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
                "period_end": datetime.now(timezone.utc).isoformat(),
                "total_cost": 0.0,
                "total_requests": 0,
            }

        return UsageStatsResponse(
            api_key_info={
                "id": str(api_key.id),
                "client_name": api_key.client_name,
                "plan": api_key.plan.value,
                "status": api_key.status.value,
                "created_at": api_key.created_at.isoformat(),
                "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            },
            usage_stats=metrics if isinstance(metrics, dict) else metrics.to_dict(),
            rate_limits={
                "current": api_key.get_rate_limits(),
                "remaining": api_key.get_remaining_limits(),
                "reset_time": api_key.get_reset_time(),
            },
            billing_period=billing_metrics,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stats endpoint error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get usage stats: {str(e)}",
        )


@router.get(
    "/billing",
    response_model=BillingResponse,
    summary="Информация о биллинге",
    description="Возвращает информацию о биллинге и текущих ценах для вашего API ключа",
)
async def get_billing_info(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Период в часах"),
    billing_service: BillingService = Depends(get_billing_service),
):
    """Получает информацию о биллинге для API ключа"""
    try:
        api_key = get_authenticated_api_key(request)

        logger.info(f"💰 Запрос биллинга для API key {api_key.id} за {hours} часов")

        # Получаем сводку по биллингу
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        billing_summary = billing_service.get_billing_summary(
            api_key_id=api_key.id, start_date=start_time, end_date=end_time
        )

        # Получаем текущие цены
        current_prices = billing_service.get_current_prices()

        return BillingResponse(
            api_key_info={
                "id": str(api_key.id),
                "client_name": api_key.client_name,
                "plan": api_key.plan.value,
                "status": api_key.status.value,
                "created_at": api_key.created_at.isoformat(),
                "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            },
            billing_summary=billing_summary,
            current_prices=current_prices,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Billing endpoint error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get billing info: {str(e)}",
        )


@router.get(
    "/detectors",
    summary="Информация о детекторах",
    description="Возвращает статус доступных детекторов спама",
)
async def get_detectors_info(ensemble_detector=Depends(deps["get_ensemble_detector"])):
    """Информация о доступных детекторах"""
    try:
        # Получаем health check всех детекторов
        health = await ensemble_detector.health_check()

        # Получаем список доступных детекторов
        available_detectors = await ensemble_detector.get_available_detectors()

        # Получаем performance stats
        performance_stats = await ensemble_detector.get_performance_stats()

        return {
            "api_version": "2.0",
            "architecture": "modern",
            "detectors": {
                "available": available_detectors,
                "details": health.get("detectors", {}),
                "status": health.get("status", "unknown"),
            },
            "performance": {
                "stats": performance_stats,
                "config": {
                    "max_processing_time": ensemble_detector.max_processing_time,
                    "spam_threshold": ensemble_detector.spam_threshold,
                    "auto_ban_threshold": ensemble_detector.auto_ban_threshold,
                },
            },
            "features": [
                "CAS banned users database",
                "RUSpam BERT model for Russian",
                "OpenAI LLM contextual analysis",
                "Early exit optimization",
                "Circuit breaker pattern",
                "Performance monitoring",
            ],
            "languages_supported": ["ru", "en", "mixed"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Detectors info error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get detectors info: {str(e)}",
        )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Проверка состояния API и всех компонентов",
)
async def health_check(ensemble_detector=Depends(deps["get_ensemble_detector"])):
    """Production health check endpoint"""
    try:
        # Проверяем ensemble detector
        detector_health = await ensemble_detector.health_check()

        # Проверяем performance stats
        performance_stats = await ensemble_detector.get_performance_stats()

        return HealthResponse(
            status=detector_health.get("status", "unknown"),
            timestamp=time.time(),
            version="2.0.0",
            components={"ensemble_detector": detector_health, "api": {"status": "healthy"}},
            performance=performance_stats,
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="error",
            timestamp=time.time(),
            version="2.0.0",
            components={
                "ensemble_detector": {"status": "error", "error": str(e)},
                "api": {"status": "degraded"},
            },
            performance={},
        )


@router.get(
    "/info", summary="Информация об API", description="Возвращает информацию о возможностях API"
)
async def get_api_info():
    """Информация о публичном API"""
    return {
        "api_name": "AntiSpam Detection API",
        "version": "2.0.0",
        "description": "Production-ready API для высокоточной детекции спама в Telegram",
        "architecture": "CAS + RUSpam + OpenAI (NO legacy heuristics)",
        "features": [
            "🛡️ CAS - мгновенная проверка базы забаненных",
            "🤖 RUSpam - BERT модель для русского языка",
            "🧠 OpenAI - LLM контекстуальный анализ",
            "⚡ Early exit optimization для производительности",
            "🔄 Circuit breaker pattern для reliability",
            "📊 Real-time метрики и мониторинг",
            "🔐 JWT аутентификация с refresh tokens",
            "🚦 Rate limiting по API ключам",
            "📈 Детальная аналитика использования",
        ],
        "endpoints": {
            "detection": {"single": "POST /api/v1/detect", "batch": "POST /api/v1/detect/batch"},
            "analytics": {
                "usage_stats": "GET /api/v1/stats",
                "detectors_info": "GET /api/v1/detectors",
            },
            "system": {"health": "GET /api/v1/health", "info": "GET /api/v1/info"},
        },
        "authentication": {
            "methods": ["API Key", "JWT Bearer Token"],
            "headers": ["Authorization: Bearer {token}", "X-API-Key: {key}"],
        },
        "rate_limits": {
            "free": {"requests_per_minute": 60, "requests_per_day": 5000},
            "basic": {"requests_per_minute": 120, "requests_per_day": 10000},
            "pro": {"requests_per_minute": 300, "requests_per_day": 50000},
            "enterprise": {"requests_per_minute": 1000, "requests_per_day": 1000000},
        },
        "performance": {
            "target_response_time_ms": 200,
            "max_throughput_rps": 1000,
            "timeout_limit_ms": 2000,
            "batch_limit": 100,
        },
        "languages": {
            "primary": "Russian (ru)",
            "secondary": "English (en)",
            "supported": ["ru", "en", "mixed"],
        },
        "documentation": {
            "interactive": "/docs",
            "openapi_schema": "/openapi.json",
            "python_sdk": "pip install antispam-client",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
