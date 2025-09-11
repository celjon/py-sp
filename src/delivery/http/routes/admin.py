from fastapi import APIRouter, HTTPException, Request, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import secrets
import time
from ....domain.entity.spam_sample import SpamSample, SampleType, SampleSource

router = APIRouter()
security = HTTPBasic()

# Pydantic модели для админ API
class SpamSampleCreate(BaseModel):
    """Модель для создания образца спама"""
    text: str = Field(..., min_length=1, max_length=4096, description="Текст образца")
    type: str = Field(..., description="Тип: 'spam' или 'ham'")
    source: str = Field(default="manual_addition", description="Источник образца")
    chat_id: Optional[int] = Field(None, description="ID чата")
    user_id: Optional[int] = Field(None, description="ID пользователя")
    tags: List[str] = Field(default=[], description="Теги для классификации")
    
    class Config:
        schema_extra = {
            "example": {
                "text": "🔥🔥🔥 ЗАРАБОТОК! Детали в ЛС!",
                "type": "spam",
                "source": "admin_report",
                "tags": ["russian", "emoji", "work_from_home"]
            }
        }

class SpamSampleResponse(BaseModel):
    """Ответ с образцом спама"""
    id: int
    text: str
    type: str
    source: str
    chat_id: Optional[int]
    user_id: Optional[int]
    language: Optional[str]
    confidence: Optional[float]
    tags: List[str]
    created_at: str
    updated_at: str

class SpamSamplesList(BaseModel):
    """Список образцов спама"""
    samples: List[SpamSampleResponse]
    total_count: int
    page: int
    per_page: int

class SystemStatus(BaseModel):
    """Статус системы"""
    status: str
    detectors: Dict[str, Any]
    database: Dict[str, Any]
    redis: Dict[str, Any]
    telegram: Dict[str, Any]
    uptime_seconds: float
    version: str


def get_dependencies(request: Request) -> Dict[str, Any]:
    """Получение зависимостей из app state"""
    return request.app.state.dependencies


def get_config(request: Request):
    """Получение конфигурации"""
    return request.app.state.config


def verify_admin_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
    config = Depends(get_config)
):
    """Проверка админских учетных данных"""
    # Простая проверка через переменные окружения
    # В продакшене следует использовать более безопасный метод
    correct_username = "admin"  # Можно настроить через конфиг
    correct_password = "admin123"  # Должен быть в переменных окружения
    
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/", dependencies=[Depends(verify_admin_credentials)])
async def admin_dashboard():
    """Админская панель - главная страница"""
    return {
        "message": "AntiSpam Bot Admin Panel",
        "version": "2.0.0",
        "endpoints": {
            "system_status": "GET /admin/status",
            "spam_samples": "GET /admin/samples",
            "create_sample": "POST /admin/samples",
            "detector_config": "GET /admin/detectors/config",
            "statistics": "GET /admin/stats"
        },
        "timestamp": time.time()
    }


@router.get("/status", response_model=SystemStatus, dependencies=[Depends(verify_admin_credentials)])
async def get_system_status(
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Получить статус всей системы"""
    try:
        # Проверяем детекторы
        spam_detector = dependencies.get("spam_detector")
        detectors_status = {}
        if spam_detector:
            health = await spam_detector.health_check()
            detectors_status = health.get("detectors", {})
        
        # Проверяем базу данных
        postgres_client = dependencies.get("postgres_client")
        database_status = {"status": "unknown"}
        if postgres_client:
            try:
                # Простая проверка подключения
                async with postgres_client.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                database_status = {"status": "healthy", "connected": True}
            except Exception as e:
                database_status = {"status": "error", "error": str(e)}
        
        # Проверяем Redis
        redis_cache = dependencies.get("redis_cache")
        redis_status = {"status": "unknown"}
        if redis_cache:
            try:
                await redis_cache.set("health_check", "ok", ttl=60)
                result = await redis_cache.get("health_check")
                redis_status = {"status": "healthy", "connected": True}
            except Exception as e:
                redis_status = {"status": "error", "error": str(e)}
        
        # Проверяем Telegram
        telegram_gateway = dependencies.get("telegram_gateway")
        telegram_status = {"status": "unknown"}
        if telegram_gateway and telegram_gateway.bot:
            try:
                me = await telegram_gateway.bot.get_me()
                telegram_status = {
                    "status": "healthy", 
                    "bot_username": me.username,
                    "bot_id": me.id
                }
            except Exception as e:
                telegram_status = {"status": "error", "error": str(e)}
        
        # Определяем общий статус
        overall_status = "healthy"
        if (database_status.get("status") == "error" or 
            redis_status.get("status") == "error" or
            telegram_status.get("status") == "error"):
            overall_status = "degraded"
        
        return SystemStatus(
            status=overall_status,
            detectors=detectors_status,
            database=database_status,
            redis=redis_status,
            telegram=telegram_status,
            uptime_seconds=time.time(),  # Упрощенно
            version="2.0.0"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting system status: {str(e)}"
        )


@router.get("/samples", response_model=SpamSamplesList, dependencies=[Depends(verify_admin_credentials)])
async def get_spam_samples(
    page: int = 1,
    per_page: int = 50,
    sample_type: Optional[str] = None,
    language: Optional[str] = None,
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Получить список образцов спама с пагинацией"""
    try:
        spam_samples_repo = dependencies.get("spam_samples_repository")
        if not spam_samples_repo:
            raise HTTPException(
                status_code=503,
                detail="Spam samples repository not available"
            )
        
        # Получаем образцы по типу
        if sample_type:
            if sample_type not in ["spam", "ham"]:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid sample_type. Must be 'spam' or 'ham'"
                )
            sample_type_enum = SampleType.SPAM if sample_type == "spam" else SampleType.HAM
            samples = await spam_samples_repo.get_samples_by_type(sample_type_enum, limit=per_page)
        elif language:
            samples = await spam_samples_repo.get_samples_by_language(language, limit=per_page)
        else:
            # Получаем недавние образцы
            samples = await spam_samples_repo.get_recent_samples(hours=24*30, limit=per_page)  # За месяц
        
        # Преобразуем в response модели
        sample_responses = []
        for sample in samples:
            sample_responses.append(SpamSampleResponse(
                id=sample.id,
                text=sample.text,
                type=sample.type.value,
                source=sample.source.value,
                chat_id=sample.chat_id,
                user_id=sample.user_id,
                language=sample.language,
                confidence=sample.confidence,
                tags=sample.tags,
                created_at=sample.created_at.isoformat() if sample.created_at else "",
                updated_at=sample.updated_at.isoformat() if sample.updated_at else ""
            ))
        
        # Получаем общее количество
        total_count = await spam_samples_repo.get_sample_count()
        
        return SpamSamplesList(
            samples=sample_responses,
            total_count=total_count,
            page=page,
            per_page=per_page
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting spam samples: {str(e)}"
        )


@router.post("/samples", response_model=SpamSampleResponse, dependencies=[Depends(verify_admin_credentials)])
async def create_spam_sample(
    sample_data: SpamSampleCreate,
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Создать новый образец спама"""
    try:
        spam_samples_repo = dependencies.get("spam_samples_repository")
        if not spam_samples_repo:
            raise HTTPException(
                status_code=503,
                detail="Spam samples repository not available"
            )
        
        # Валидация типа
        if sample_data.type not in ["spam", "ham"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid type. Must be 'spam' or 'ham'"
            )
        
        # Создаем доменную сущность
        sample_type = SampleType.SPAM if sample_data.type == "spam" else SampleType.HAM
        
        # Определяем источник
        try:
            source = SampleSource(sample_data.source)
        except ValueError:
            source = SampleSource.MANUAL_ADDITION
        
        spam_sample = SpamSample(
            text=sample_data.text,
            type=sample_type,
            source=source,
            chat_id=sample_data.chat_id,
            user_id=sample_data.user_id,
            tags=sample_data.tags
        )
        
        # Сохраняем в базе
        saved_sample = await spam_samples_repo.save_sample(spam_sample)
        
        return SpamSampleResponse(
            id=saved_sample.id,
            text=saved_sample.text,
            type=saved_sample.type.value,
            source=saved_sample.source.value,
            chat_id=saved_sample.chat_id,
            user_id=saved_sample.user_id,
            language=saved_sample.language,
            confidence=saved_sample.confidence,
            tags=saved_sample.tags,
            created_at=saved_sample.created_at.isoformat() if saved_sample.created_at else "",
            updated_at=saved_sample.updated_at.isoformat() if saved_sample.updated_at else ""
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error creating spam sample: {str(e)}"
        )


@router.delete("/samples/{sample_id}", dependencies=[Depends(verify_admin_credentials)])
async def delete_spam_sample(
    sample_id: int,
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Удалить образец спама"""
    try:
        spam_samples_repo = dependencies.get("spam_samples_repository")
        if not spam_samples_repo:
            raise HTTPException(
                status_code=503,
                detail="Spam samples repository not available"
            )
        
        # Удаляем образец
        success = await spam_samples_repo.delete_sample(sample_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Spam sample not found"
            )
        
        return {"message": f"Spam sample {sample_id} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting spam sample: {str(e)}"
        )


@router.get("/detectors/config", dependencies=[Depends(verify_admin_credentials)])
async def get_detectors_config(
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Получить конфигурацию детекторов"""
    try:
        spam_detector = dependencies.get("spam_detector")
        if not spam_detector:
            raise HTTPException(
                status_code=503,
                detail="Spam detector not available"
            )
        
        # Получаем доступные детекторы
        available_detectors = await spam_detector.get_available_detectors()
        
        # Получаем конфигурацию эвристического детектора
        heuristic_config = {}
        if hasattr(spam_detector, 'heuristic_detector'):
            heuristic_config = spam_detector.heuristic_detector.get_config()
        
        # Получаем информацию о RUSpam
        ruspam_info = {}
        if hasattr(spam_detector, 'ruspam_detector') and spam_detector.ruspam_detector:
            ruspam_info = {
                "is_available": spam_detector.ruspam_detector.is_available,
                "is_loaded": spam_detector.ruspam_detector.is_loaded,
                "model_name": getattr(spam_detector.ruspam_detector, 'model_name', 'unknown')
            }
        
        return {
            "available_detectors": available_detectors,
            "ensemble_config": spam_detector.config,
            "heuristic_config": heuristic_config,
            "ruspam_info": ruspam_info,
            "timestamp": time.time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting detectors config: {str(e)}"
        )


@router.post("/detectors/test", dependencies=[Depends(verify_admin_credentials)])
async def test_detectors(
    test_text: str = "🔥🔥🔥 ЗАРАБОТОК! Детали в ЛС!",
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Тестировать детекторы на заданном тексте"""
    try:
        check_message_usecase = dependencies.get("check_message_usecase")
        if not check_message_usecase:
            raise HTTPException(
                status_code=503,
                detail="Check message use case not available"
            )
        
        from ....domain.entity.message import Message
        
        # Создаем тестовое сообщение
        message = Message(
            user_id=0,
            chat_id=0,
            text=test_text
        )
        
        # Выполняем детекцию
        result = await check_message_usecase(message)
        
        # Формируем результат
        detector_results = []
        for dr in result.detector_results:
            detector_results.append({
                "detector_name": dr.detector_name,
                "is_spam": dr.is_spam,
                "confidence": dr.confidence,
                "details": dr.details,
                "processing_time_ms": dr.processing_time_ms
            })
        
        return {
            "test_text": test_text,
            "overall_result": {
                "is_spam": result.is_spam,
                "confidence": result.overall_confidence,
                "primary_reason": result.primary_reason.value if result.primary_reason else None,
                "processing_time_ms": result.processing_time_ms
            },
            "detector_results": detector_results,
            "recommendations": {
                "should_ban": result.should_ban,
                "should_delete": result.should_delete,
                "should_restrict": result.should_restrict,
                "should_warn": result.should_warn
            },
            "timestamp": time.time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error testing detectors: {str(e)}"
        )
