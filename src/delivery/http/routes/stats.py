from fastapi import APIRouter, HTTPException, Request, Depends, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import time

router = APIRouter()


# Pydantic модели для статистики
class GlobalStats(BaseModel):
    """Глобальная статистика системы"""

    total_messages: int = Field(..., description="Общее количество сообщений")
    spam_messages: int = Field(..., description="Количество спам сообщений")
    clean_messages: int = Field(..., description="Количество чистых сообщений")
    spam_percentage: float = Field(..., description="Процент спама")
    active_chats: int = Field(..., description="Активные чаты")
    active_users: int = Field(..., description="Активные пользователи")
    spam_users: int = Field(..., description="Пользователи со спамом")
    avg_spam_confidence: float = Field(..., description="Средняя уверенность детекции")
    period_hours: int = Field(..., description="Период в часах")
    generated_at: str = Field(..., description="Время генерации статистики")


class ChatStats(BaseModel):
    """Статистика чата"""

    chat_id: int = Field(..., description="ID чата")
    total_messages: int
    spam_messages: int
    clean_messages: int
    deleted_messages: int
    spam_percentage: float
    active_users: int
    spam_users: int
    clean_users: int
    banned_users: int
    avg_spam_confidence: float
    last_message_time: Optional[str]
    period_hours: int
    generated_at: str


class UserStats(BaseModel):
    """Статистика пользователя"""

    user_id: int = Field(..., description="ID пользователя")
    chat_id: Optional[int] = Field(None, description="ID чата (если указан)")
    total_messages: int
    spam_messages: int
    clean_messages: int
    spam_percentage: float
    active_chats: int
    avg_spam_confidence: float
    max_spam_confidence: float
    first_message: Optional[str]
    last_message: Optional[str]
    is_suspicious: bool = Field(..., description="Является ли пользователь подозрительным")
    period_hours: int
    generated_at: str


class TopSpammer(BaseModel):
    """Топ спаммер"""

    user_id: int
    spam_count: int
    avg_confidence: float


class HourlyDistribution(BaseModel):
    """Почасовое распределение"""

    hour: str
    total: int
    spam: int
    spam_rate: float


class DetailedChatStats(ChatStats):
    """Детальная статистика чата"""

    top_spammers: List[TopSpammer]
    hourly_distribution: List[HourlyDistribution]


class DetectorPerformance(BaseModel):
    """Производительность детектора"""

    detector_name: str
    total_checks: int
    spam_detected: int
    avg_confidence: float
    avg_processing_time_ms: float
    accuracy: Optional[float] = None


class SystemPerformance(BaseModel):
    """Производительность системы"""

    total_requests: int
    avg_response_time_ms: float
    requests_per_minute: float
    detectors: List[DetectorPerformance]
    uptime_seconds: float
    memory_usage_mb: Optional[float] = None


def get_dependencies(request: Request) -> Dict[str, Any]:
    """Получение зависимостей из app state"""
    return request.app.state.dependencies


@router.get("/stats", response_model=GlobalStats)
async def get_global_stats(
    hours: int = Query(24, ge=1, le=168, description="Период в часах (1-168)"),
    dependencies: Dict[str, Any] = Depends(get_dependencies),
):
    """
    Получить глобальную статистику системы

    Возвращает общую статистику по всем чатам за указанный период.
    """
    try:
        message_repo = dependencies.get("message_repository")
        if not message_repo:
            raise HTTPException(status_code=503, detail="Message repository not available")

        # Получаем глобальную статистику
        stats = await message_repo.get_global_stats(hours=hours)

        return GlobalStats(**stats)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting global stats: {str(e)}")


@router.get("/stats/chat/{chat_id}", response_model=DetailedChatStats)
async def get_chat_stats(
    chat_id: int,
    hours: int = Query(24, ge=1, le=168, description="Период в часах (1-168)"),
    dependencies: Dict[str, Any] = Depends(get_dependencies),
):
    """
    Получить детальную статистику чата

    Включает информацию о топ спаммерах и почасовом распределении.
    """
    try:
        message_repo = dependencies.get("message_repository")
        if not message_repo:
            raise HTTPException(status_code=503, detail="Message repository not available")

        # Получаем статистику чата
        stats = await message_repo.get_chat_stats(chat_id=chat_id, hours=hours)

        return DetailedChatStats(**stats)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting chat stats: {str(e)}")


@router.get("/stats/user/{user_id}", response_model=UserStats)
async def get_user_stats(
    user_id: int,
    chat_id: Optional[int] = Query(None, description="ID чата (опционально)"),
    hours: int = Query(168, ge=1, le=168 * 4, description="Период в часах (1-672)"),
    dependencies: Dict[str, Any] = Depends(get_dependencies),
):
    """
    Получить статистику пользователя

    Может быть ограничена конкретным чатом или показать общую статистику.
    """
    try:
        message_repo = dependencies.get("message_repository")
        if not message_repo:
            raise HTTPException(status_code=503, detail="Message repository not available")

        # Получаем статистику пользователя
        stats = await message_repo.get_user_stats(user_id=user_id, chat_id=chat_id, hours=hours)

        return UserStats(**stats)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting user stats: {str(e)}")


@router.get("/stats/performance", response_model=SystemPerformance)
async def get_system_performance(dependencies: Dict[str, Any] = Depends(get_dependencies)):
    """
    Получить статистику производительности системы

    Показывает производительность детекторов и общую нагрузку.
    """
    try:
        # Пока упрощенная версия - в будущем можно добавить реальные метрики
        spam_detector = dependencies.get("spam_detector")

        detector_performance = []
        if spam_detector:
            available_detectors = await spam_detector.get_available_detectors()

            # Генерируем примерные метрики производительности
            for detector_name in available_detectors:
                detector_performance.append(
                    DetectorPerformance(
                        detector_name=detector_name,
                        total_checks=1000,  # Заглушка
                        spam_detected=100,  # Заглушка
                        avg_confidence=0.75,  # Заглушка
                        avg_processing_time_ms=50.0 if detector_name == "Heuristic" else 150.0,
                        accuracy=0.85,  # Заглушка
                    )
                )

        return SystemPerformance(
            total_requests=10000,  # Заглушка
            avg_response_time_ms=125.0,
            requests_per_minute=60.0,
            detectors=detector_performance,
            uptime_seconds=time.time(),  # Упрощено
            memory_usage_mb=256.0,  # Заглушка
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting performance stats: {str(e)}")


@router.get("/stats/summary")
async def get_stats_summary(dependencies: Dict[str, Any] = Depends(get_dependencies)):
    """
    Получить краткую сводку статистики

    Полезно для дашбордов и мониторинга.
    """
    try:
        message_repo = dependencies.get("message_repository")
        if not message_repo:
            raise HTTPException(status_code=503, detail="Message repository not available")

        # Получаем статистику за разные периоды
        stats_1h = await message_repo.get_global_stats(hours=1)
        stats_24h = await message_repo.get_global_stats(hours=24)
        stats_7d = await message_repo.get_global_stats(hours=168)

        # Проверяем состояние детекторов
        spam_detector = dependencies.get("spam_detector")
        detectors_status = "unknown"
        available_detectors = []

        if spam_detector:
            health = await spam_detector.health_check()
            detectors_status = health.get("status", "unknown")
            available_detectors = await spam_detector.get_available_detectors()

        return {
            "summary": {
                "last_hour": {
                    "messages": stats_1h["total_messages"],
                    "spam_rate": stats_1h["spam_percentage"],
                },
                "last_24h": {
                    "messages": stats_24h["total_messages"],
                    "spam_rate": stats_24h["spam_percentage"],
                },
                "last_7d": {
                    "messages": stats_7d["total_messages"],
                    "spam_rate": stats_7d["spam_percentage"],
                },
            },
            "system": {
                "detectors_status": detectors_status,
                "available_detectors": available_detectors,
                "active_chats": stats_24h["active_chats"],
                "active_users": stats_24h["active_users"],
            },
            "trends": {
                "spam_trend": "stable",  # Можно вычислить тренд
                "volume_trend": "increasing",  # Можно вычислить тренд
                "performance": "good",
            },
            "timestamp": time.time(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting stats summary: {str(e)}")


@router.get("/stats/top-spammers")
async def get_top_spammers(
    limit: int = Query(10, ge=1, le=100, description="Количество топ спаммеров"),
    hours: int = Query(24, ge=1, le=168, description="Период в часах"),
    chat_id: Optional[int] = Query(None, description="ID чата (опционально)"),
    dependencies: Dict[str, Any] = Depends(get_dependencies),
):
    """
    Получить список топ спаммеров

    Может быть ограничен конкретным чатом.
    """
    try:
        message_repo = dependencies.get("message_repository")
        if not message_repo:
            raise HTTPException(status_code=503, detail="Message repository not available")

        # Если указан chat_id, получаем статистику чата
        if chat_id:
            stats = await message_repo.get_chat_stats(chat_id=chat_id, hours=hours)
            top_spammers = stats.get("top_spammers", [])
        else:
            # Иначе делаем поиск по всем чатам (упрощенная версия)
            # В реальной реализации нужен отдельный метод
            top_spammers = []

        return {
            "top_spammers": top_spammers[:limit],
            "period_hours": hours,
            "chat_id": chat_id,
            "total_found": len(top_spammers),
            "timestamp": time.time(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting top spammers: {str(e)}")


@router.get("/stats/detector/{detector_name}")
async def get_detector_stats(
    detector_name: str, dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """
    Получить статистику конкретного детектора
    """
    try:
        spam_detector = dependencies.get("spam_detector")
        if not spam_detector:
            raise HTTPException(status_code=503, detail="Spam detector not available")

        # Проверяем что детектор существует
        available_detectors = await spam_detector.get_available_detectors()
        if detector_name not in available_detectors:
            raise HTTPException(status_code=404, detail=f"Detector '{detector_name}' not found")

        # Получаем health check информацию
        health = await spam_detector.health_check()
        detector_health = health.get("detectors", {}).get(detector_name, {})

        # Возвращаем информацию о детекторе
        result = {
            "detector_name": detector_name,
            "status": detector_health.get("status", "unknown"),
            "available": detector_health.get("available", False),
            "timestamp": time.time(),
        }

        # Добавляем специфичную информацию для разных детекторов
        if detector_name == "ruspam" and hasattr(spam_detector, "ruspam_detector"):
            if spam_detector.ruspam_detector:
                result["model_info"] = {
                    "is_available": spam_detector.ruspam_detector.is_available,
                    "is_loaded": spam_detector.ruspam_detector.is_loaded,
                    "model_name": getattr(spam_detector.ruspam_detector, "model_name", "unknown"),
                }

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting detector stats: {str(e)}")
