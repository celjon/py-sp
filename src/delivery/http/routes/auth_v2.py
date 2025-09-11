# src/delivery/http/routes/auth_v2.py
"""
Production-ready Authentication Routes v2.0
Интегрирует JWT, rate limiting, analytics и полное управление API ключами
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Depends, status, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, EmailStr, validator

from ....config.dependencies import get_dependencies_for_routes
from ....domain.service.auth.jwt_service import JWTService, TokenPair
from ....domain.service.analytics.usage_analytics import UsageAnalytics
from ....domain.usecase.api.manage_keys import ManageApiKeysUseCase, CreateApiKeyRequest
from ....domain.entity.api_key import ApiKeyPlan, ApiKeyStatus
from ....domain.entity.client_usage import RequestStatus

router = APIRouter()
security = HTTPBasic()

# Получаем dependency providers
deps = get_dependencies_for_routes()

# === PYDANTIC MODELS ===

class TokenRequest(BaseModel):
    """Запрос на получение JWT токена"""
    api_key: str = Field(..., description="API ключ для аутентификации")
    
    class Config:
        schema_extra = {
            "example": {
                "api_key": "antispam_your_api_key_here"
            }
        }


class TokenResponse(BaseModel):
    """Ответ с JWT токенами"""
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int  # секунды
    refresh_expires_in: int  # секунды
    api_key_info: Dict[str, Any]


class RefreshTokenRequest(BaseModel):
    """Запрос на обновление токена"""
    refresh_token: str = Field(..., description="Refresh токен")


class CreateApiKeyRequestV2(BaseModel):
    """Расширенный запрос на создание API ключа"""
    client_name: str = Field(..., min_length=2, max_length=100, description="Название клиента/проекта")
    contact_email: EmailStr = Field(..., description="Email для связи")
    plan: ApiKeyPlan = Field(ApiKeyPlan.FREE, description="Тарифный план")
    
    # Кастомные лимиты
    requests_per_minute: Optional[int] = Field(None, ge=1, le=1000, description="Запросов в минуту")
    requests_per_day: Optional[int] = Field(None, ge=1, le=100000, description="Запросов в день")
    requests_per_month: Optional[int] = Field(None, ge=1, le=5000000, description="Запросов в месяц")
    
    # Безопасность
    allowed_ips: List[str] = Field([], description="Разрешенные IP адреса")
    webhook_url: Optional[str] = Field(None, description="URL для webhook уведомлений")
    
    # Метаданные
    description: Optional[str] = Field(None, max_length=500, description="Описание использования")
    project_url: Optional[str] = Field(None, description="URL проекта")
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650, description="Срок действия в днях")
    
    @validator('allowed_ips')
    def validate_ips(cls, v):
        """Валидация IP адресов"""
        import ipaddress
        for ip in v:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                # Проверяем CIDR нотацию
                try:
                    ipaddress.ip_network(ip, strict=False)
                except ValueError:
                    raise ValueError(f"Invalid IP address or CIDR: {ip}")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "client_name": "My Awesome Bot",
                "contact_email": "developer@company.com",
                "plan": "basic",
                "requests_per_minute": 120,
                "requests_per_day": 10000,
                "allowed_ips": ["192.168.1.100", "10.0.0.0/24"],
                "description": "API ключ для интеграции антиспама в чат-бот",
                "project_url": "https://github.com/mycompany/chatbot"
            }
        }


class ApiKeyResponseV2(BaseModel):
    """Расширенный ответ с информацией об API ключе"""
    id: int
    client_name: str
    contact_email: str
    key_prefix: str
    plan: str
    status: str
    
    # Rate limits
    rate_limits: Dict[str, int]
    
    # Timestamps
    created_at: str
    updated_at: str
    last_used_at: Optional[str]
    expires_at: Optional[str]
    
    # Security
    allowed_ips: List[str]
    webhook_url: Optional[str]
    
    # Usage stats (последние 24 часа)
    usage_stats_24h: Optional[Dict[str, Any]] = None
    
    # Metadata
    description: Optional[str]
    project_url: Optional[str]


class ApiKeyCreatedResponse(ApiKeyResponseV2):
    """Ответ при создании API ключа (содержит полный ключ)"""
    api_key: str
    jwt_tokens: TokenResponse
    setup_guide: Dict[str, Any]
    warning: str = "Store this API key securely. It will not be shown again."


# === UTILITY FUNCTIONS ===

async def verify_admin_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Проверка admin учетных данных"""
    import secrets
    
    # В production получать из переменных окружения
    correct_username = "admin"
    correct_password = "admin_password_change_me"  # TODO: Из env
    
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


# === AUTHENTICATION ENDPOINTS ===

@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Получить JWT токены",
    description="Обменивает API ключ на JWT токены для аутентификации"
)
async def get_jwt_tokens(
    request: TokenRequest,
    jwt_service: JWTService = Depends(deps["get_jwt_service"]),
    api_key_repo = Depends(deps["get_api_key_repo"]),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Получение JWT токенов по API ключу"""
    try:
        start_time = time.time()
        
        # Валидируем API ключ
        from ....domain.entity.api_key import ApiKey
        key_hash = ApiKey.hash_key(request.api_key)
        api_key = await api_key_repo.get_api_key_by_hash(key_hash)
        
        if not api_key or not api_key.is_valid or not api_key.verify_key(request.api_key):
            # Записываем неудачную попытку аутентификации
            await usage_analytics.track_api_request(
                api_key=api_key if api_key else None,
                endpoint="/auth/token",
                method="POST",
                status=RequestStatus.AUTHENTICATION_FAILED,
                processing_time_ms=(time.time() - start_time) * 1000,
                client_ip="unknown"
            )
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key"
            )
        
        # Создаем JWT токены
        token_pair = jwt_service.create_token_pair(
            api_key_id=str(api_key.id),
            client_name=api_key.client_name,
            plan=api_key.plan.value,
            permissions=[]  # TODO: Реализовать систему разрешений
        )
        
        # Обновляем last_used_at
        api_key.last_used_at = datetime.now(timezone.utc)
        await api_key_repo.update_api_key(api_key)
        
        # Записываем успешную аутентификацию
        await usage_analytics.track_api_request(
            api_key=api_key,
            endpoint="/auth/token",
            method="POST",
            status=RequestStatus.SUCCESS,
            processing_time_ms=(time.time() - start_time) * 1000,
            client_ip="unknown"
        )
        
        return TokenResponse(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.access_expires_in,
            refresh_expires_in=token_pair.refresh_expires_in,
            api_key_info={
                "id": api_key.id,
                "client_name": api_key.client_name,
                "plan": api_key.plan.value,
                "rate_limits": api_key.get_rate_limits()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Token generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate tokens"
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновить access токен",
    description="Обновляет access токен используя refresh токен"
)
async def refresh_access_token(
    request: RefreshTokenRequest,
    jwt_service: JWTService = Depends(deps["get_jwt_service"]),
    api_key_repo = Depends(deps["get_api_key_repo"])
):
    """Обновление access токена"""
    try:
        # Обновляем токены
        token_pair = jwt_service.refresh_access_token(request.refresh_token)
        
        if not token_pair:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token"
            )
        
        # Получаем информацию об API ключе
        validation_result = jwt_service.validate_token(token_pair.access_token)
        api_key_id = validation_result.claims.sub
        api_key = await api_key_repo.get_api_key_by_id(int(api_key_id))
        
        return TokenResponse(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.access_expires_in,
            refresh_expires_in=token_pair.refresh_expires_in,
            api_key_info={
                "id": api_key.id if api_key else None,
                "client_name": api_key.client_name if api_key else "Unknown",
                "plan": api_key.plan.value if api_key else "unknown",
                "rate_limits": api_key.get_rate_limits() if api_key else {}
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh token"
        )


@router.post(
    "/revoke",
    summary="Отозвать токен",
    description="Отзывает access или refresh токен"
)
async def revoke_token(
    token: str = Field(..., description="Токен для отзыва"),
    jwt_service: JWTService = Depends(deps["get_jwt_service"])
):
    """Отзыв токена"""
    try:
        success = jwt_service.revoke_token(token)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token or already revoked"
            )
        
        return {"message": "Token revoked successfully", "timestamp": time.time()}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Token revocation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke token"
        )


# === API KEY MANAGEMENT ENDPOINTS ===

@router.post(
    "/keys",
    response_model=ApiKeyCreatedResponse,
    summary="Создать API ключ",
    description="Создает новый API ключ с указанными параметрами и возвращает JWT токены"
)
async def create_api_key_v2(
    request_data: CreateApiKeyRequestV2,
    admin=Depends(verify_admin_credentials),
    manage_keys_usecase: ManageApiKeysUseCase = Depends(deps["get_manage_api_keys_usecase"]),
    jwt_service: JWTService = Depends(deps["get_jwt_service"]),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Создание нового API ключа с полной интеграцией"""
    try:
        # Преобразуем в доменный запрос
        create_request = CreateApiKeyRequest(
            client_name=request_data.client_name,
            contact_email=request_data.contact_email,
            plan=request_data.plan,
            requests_per_minute=request_data.requests_per_minute,
            requests_per_day=request_data.requests_per_day,
            requests_per_month=request_data.requests_per_month,
            allowed_ips=request_data.allowed_ips,
            webhook_url=request_data.webhook_url,
            expires_in_days=request_data.expires_in_days,
            metadata={
                "description": request_data.description,
                "project_url": request_data.project_url,
                "created_by": "admin_api",
                "created_via": "http_api_v2"
            }
        )
        
        # Создаем API ключ
        result = await manage_keys_usecase.create_api_key(create_request)
        api_key = result.api_key
        
        # Создаем JWT токены для нового ключа
        token_pair = jwt_service.create_token_pair(
            api_key_id=str(api_key.id),
            client_name=api_key.client_name,
            plan=api_key.plan.value,
            permissions=[]
        )
        
        # Получаем начальную статистику (пустую)
        usage_stats_24h = await usage_analytics.get_real_time_metrics(api_key.id, 24 * 60)
        
        # Формируем setup guide
        setup_guide = {
            "quick_start": {
                "step_1": "Save your API key securely",
                "step_2": "Use Bearer token authentication",
                "step_3": "Make test request to /api/v1/detect"
            },
            "examples": {
                "curl": f'curl -X POST "https://api.antispam.com/api/v1/detect" -H "Authorization: Bearer {result.raw_key}" -H "Content-Type: application/json" -d \'{{"text": "Test message"}}\'',
                "python": f'''
import requests

headers = {{
    "Authorization": "Bearer {result.raw_key}",
    "Content-Type": "application/json"
}}

response = requests.post(
    "https://api.antispam.com/api/v1/detect",
    headers=headers,
    json={{"text": "Check this message for spam"}}
)

print(response.json())
''',
                "javascript": f'''
const response = await fetch('https://api.antispam.com/api/v1/detect', {{
    method: 'POST',
    headers: {{
        'Authorization': 'Bearer {result.raw_key}',
        'Content-Type': 'application/json'
    }},
    body: JSON.stringify({{ text: 'Check this message for spam' }})
}});

const data = await response.json();
console.log(data);
'''
            },
            "documentation": "https://api.antispam.com/docs",
            "support": "support@antispam.com"
        }
        
        # Записываем создание ключа в аналитику
        await usage_analytics.track_api_request(
            api_key=api_key,
            endpoint="/auth/keys",
            method="POST",
            status=RequestStatus.SUCCESS,
            processing_time_ms=0,
            client_ip="admin"
        )
        
        return ApiKeyCreatedResponse(
            id=api_key.id,
            client_name=api_key.client_name,
            contact_email=api_key.contact_email,
            key_prefix=api_key.key_prefix,
            plan=api_key.plan.value,
            status=api_key.status.value,
            rate_limits=api_key.get_rate_limits(),
            created_at=api_key.created_at.isoformat(),
            updated_at=api_key.updated_at.isoformat(),
            last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
            expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
            allowed_ips=api_key.allowed_ips,
            webhook_url=api_key.webhook_url,
            usage_stats_24h=usage_stats_24h.to_dict(),
            description=request_data.description,
            project_url=request_data.project_url,
            api_key=result.raw_key,
            jwt_tokens=TokenResponse(
                access_token=token_pair.access_token,
                refresh_token=token_pair.refresh_token,
                token_type=token_pair.token_type,
                expires_in=token_pair.access_expires_in,
                refresh_expires_in=token_pair.refresh_expires_in,
                api_key_info={
                    "id": api_key.id,
                    "client_name": api_key.client_name,
                    "plan": api_key.plan.value
                }
            ),
            setup_guide=setup_guide
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Create API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create API key: {str(e)}"
        )


@router.get(
    "/keys",
    response_model=List[ApiKeyResponseV2],
    summary="Список API ключей",
    description="Возвращает список всех API ключей с аналитикой"
)
async def list_api_keys_v2(
    plan: Optional[ApiKeyPlan] = None,
    status: Optional[ApiKeyStatus] = None,
    limit: int = Field(50, ge=1, le=200),
    offset: int = Field(0, ge=0),
    include_usage_stats: bool = Field(True, description="Включить статистику использования"),
    admin=Depends(verify_admin_credentials),
    manage_keys_usecase: ManageApiKeysUseCase = Depends(deps["get_manage_api_keys_usecase"]),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Список API ключей с расширенной информацией"""
    try:
        # Получаем API ключи
        api_keys = await manage_keys_usecase.search_api_keys(
            plan=plan,
            status=status,
            is_active=True if status == ApiKeyStatus.ACTIVE else None,
            limit=limit,
            offset=offset
        )
        
        # Формируем ответ с аналитикой
        response_keys = []
        for api_key in api_keys:
            # Получаем статистику использования если запрошено
            usage_stats_24h = None
            if include_usage_stats:
                try:
                    usage_stats_24h = await usage_analytics.get_real_time_metrics(api_key.id, 24 * 60)
                except Exception as e:
                    print(f"Failed to get usage stats for key {api_key.id}: {e}")
            
            # Формируем ответ
            key_response = ApiKeyResponseV2(
                id=api_key.id,
                client_name=api_key.client_name,
                contact_email=api_key.contact_email,
                key_prefix=api_key.key_prefix,
                plan=api_key.plan.value,
                status=api_key.status.value,
                rate_limits=api_key.get_rate_limits(),
                created_at=api_key.created_at.isoformat(),
                updated_at=api_key.updated_at.isoformat(),
                last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
                expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
                allowed_ips=api_key.allowed_ips,
                webhook_url=api_key.webhook_url,
                usage_stats_24h=usage_stats_24h.to_dict() if usage_stats_24h else None,
                description=api_key.metadata.get("description"),
                project_url=api_key.metadata.get("project_url")
            )
            
            response_keys.append(key_response)
        
        return response_keys
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"List API keys error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list API keys: {str(e)}"
        )


# === ANALYTICS ENDPOINTS ===

@router.get(
    "/analytics/overview",
    summary="Общая аналитика",
    description="Возвращает общую аналитику по всем API ключам"
)
async def get_analytics_overview(
    hours: int = Field(24, ge=1, le=168, description="Период в часах"),
    admin=Depends(verify_admin_credentials),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Общая аналитика использования API"""
    try:
        # Получаем глобальную статистику
        global_stats = await usage_analytics.get_global_statistics(hours)
        
        return {
            "overview": global_stats,
            "period_hours": hours,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        print(f"Analytics overview error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analytics overview: {str(e)}"
        )


@router.get(
    "/analytics/keys/{key_id}",
    summary="Аналитика API ключа",
    description="Детальная аналитика для конкретного API ключа"
)
async def get_key_analytics(
    key_id: int,
    period: str = Field("hour", regex="^(hour|day|week)$"),
    hours_back: int = Field(24, ge=1, le=720),
    admin=Depends(verify_admin_credentials),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Детальная аналитика API ключа"""
    try:
        # Получаем метрики
        metrics = await usage_analytics.get_usage_metrics(
            api_key_id=key_id,
            period=period,
            hours_back=hours_back
        )
        
        # Детектируем аномалии
        anomalies = await usage_analytics.detect_anomalies(
            api_key_id=key_id,
            hours_back=hours_back
        )
        
        return {
            "api_key_id": key_id,
            "period": period,
            "hours_back": hours_back,
            "metrics": [metric.to_dict() for metric in metrics],
            "anomalies": anomalies,
            "summary": {
                "total_periods": len(metrics),
                "total_requests": sum(m.total_requests for m in metrics),
                "avg_success_rate": sum(m.success_rate for m in metrics) / len(metrics) if metrics else 0,
                "anomalies_count": len(anomalies)
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        print(f"Key analytics error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get key analytics: {str(e)}"
        )


# === HEALTH CHECK ===

@router.get(
    "/health",
    summary="Health check аутентификации",
    description="Проверка работоспособности authentication сервисов"
)
async def auth_health_check(
    jwt_service: JWTService = Depends(deps["get_jwt_service"]),
    usage_analytics: UsageAnalytics = Depends(deps["get_usage_analytics"])
):
    """Health check для authentication системы"""
    try:
        # Проверяем каждый компонент
        jwt_health = jwt_service.health_check()
        analytics_health = usage_analytics.health_check()
        
        overall_status = "healthy"
        if (jwt_health.get("status") != "healthy" or 
            analytics_health.get("status") != "healthy"):
            overall_status = "degraded"
        
        return {
            "status": overall_status,
            "timestamp": time.time(),
            "components": {
                "jwt_service": jwt_health,
                "usage_analytics": analytics_health
            },
            "version": "2.0.0"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "timestamp": time.time(),
            "error": str(e)
        }
