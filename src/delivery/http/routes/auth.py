from fastapi import APIRouter, HTTPException, Request, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
import secrets
import time

router = APIRouter()
security = HTTPBasic()

# Pydantic модели для управления API ключами
class CreateApiKeyRequest(BaseModel):
    """Запрос на создание API ключа"""
    client_name: str = Field(..., min_length=2, max_length=100, description="Название клиента")
    contact_email: EmailStr = Field(..., description="Email для связи")
    plan: str = Field("free", description="Тарифный план (free/basic/pro/enterprise)")
    
    # Кастомные лимиты (опционально)
    requests_per_minute: Optional[int] = Field(None, ge=0, description="Запросов в минуту")
    requests_per_day: Optional[int] = Field(None, ge=0, description="Запросов в день")
    requests_per_month: Optional[int] = Field(None, ge=0, description="Запросов в месяц")
    
    # Ограничения безопасности
    allowed_ips: List[str] = Field([], description="Разрешенные IP адреса (пустой список = все)")
    webhook_url: Optional[str] = Field(None, description="URL для webhooks")
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650, description="Срок действия в днях")
    
    # Дополнительные метаданные
    description: Optional[str] = Field(None, max_length=500, description="Описание использования")
    
    class Config:
        schema_extra = {
            "example": {
                "client_name": "My Bot App",
                "contact_email": "developer@example.com",
                "plan": "basic",
                "requests_per_minute": 120,
                "allowed_ips": ["192.168.1.100", "10.0.0.5"],
                "description": "API ключ для интеграции антиспама в чат-бот"
            }
        }


class UpdateApiKeyRequest(BaseModel):
    """Запрос на обновление API ключа"""
    client_name: Optional[str] = Field(None, min_length=2, max_length=100)
    contact_email: Optional[EmailStr] = None
    plan: Optional[str] = None
    requests_per_minute: Optional[int] = Field(None, ge=0)
    requests_per_day: Optional[int] = Field(None, ge=0)
    requests_per_month: Optional[int] = Field(None, ge=0)
    allowed_ips: Optional[List[str]] = None
    webhook_url: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)


class ApiKeyResponse(BaseModel):
    """Ответ с информацией об API ключе"""
    id: int
    client_name: str
    contact_email: str
    key_prefix: str
    plan: str
    status: str
    rate_limits: Dict[str, int]
    created_at: str
    last_used_at: Optional[str]
    expires_at: Optional[str]
    allowed_ips: List[str]
    webhook_url: Optional[str]
    description: Optional[str]


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Ответ при создании API ключа (содержит полный ключ)"""
    api_key: str
    warning: str = "Store this key securely. It will not be shown again."


class ApiKeyListResponse(BaseModel):
    """Список API ключей"""
    api_keys: List[ApiKeyResponse]
    total_count: int
    page: int
    per_page: int


def get_dependencies(request: Request) -> Dict[str, Any]:
    """Получение зависимостей из app state"""
    return request.app.state.dependencies


def verify_admin_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Проверка админских учетных данных для управления API ключами"""
    config = dependencies.get("config")
    
    # В простой реализации используем статичные credentials
    # В production следует использовать более безопасный метод
    correct_username = "admin"
    correct_password = "api_admin_2024"  # Должен быть в переменных окружения
    
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.post(
    "/keys",
    response_model=ApiKeyCreatedResponse,
    summary="Создать API ключ",
    description="Создает новый API ключ для клиента"
)
async def create_api_key(
    request_data: CreateApiKeyRequest,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Создание нового API ключа"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        # Преобразуем план в enum
        from ....domain.entity.api_key import ApiKeyPlan
        try:
            plan_enum = ApiKeyPlan(request_data.plan.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid plan: {request_data.plan}. Available: free, basic, pro, enterprise"
            )
        
        # Создаем доменный запрос
        from ....domain.usecase.api.manage_api_keys import CreateApiKeyRequest as DomainRequest
        
        domain_request = DomainRequest(
            client_name=request_data.client_name,
            contact_email=request_data.contact_email,
            plan=plan_enum,
            requests_per_minute=request_data.requests_per_minute,
            requests_per_day=request_data.requests_per_day,
            requests_per_month=request_data.requests_per_month,
            allowed_ips=request_data.allowed_ips,
            webhook_url=request_data.webhook_url,
            expires_in_days=request_data.expires_in_days,
            metadata={"description": request_data.description} if request_data.description else {}
        )
        
        # Создаем ключ
        result = await manage_keys_usecase.create_api_key(domain_request)
        
        # Формируем ответ
        response_data = result.to_dict(include_key=True)
        return ApiKeyCreatedResponse(**response_data)
        
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
    response_model=ApiKeyListResponse,
    summary="Список API ключей",
    description="Получает список всех API ключей с фильтрами"
)
async def list_api_keys(
    client_name: Optional[str] = None,
    plan: Optional[str] = None,
    status: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    per_page: int = 50,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Получение списка API ключей"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        # Валидируем параметры
        if per_page > 100:
            per_page = 100
        if page < 1:
            page = 1
        
        offset = (page - 1) * per_page
        
        # Преобразуем план и статус в enum если указаны
        plan_enum = None
        status_enum = None
        
        if plan:
            from ....domain.entity.api_key import ApiKeyPlan
            try:
                plan_enum = ApiKeyPlan(plan.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid plan: {plan}"
                )
        
        if status:
            from ....domain.entity.api_key import ApiKeyStatus
            try:
                status_enum = ApiKeyStatus(status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status}"
                )
        
        # Получаем ключи
        api_key_responses = await manage_keys_usecase.list_api_keys(
            client_name=client_name,
            plan=plan_enum,
            status=status_enum,
            is_active=is_active,
            limit=per_page,
            offset=offset
        )
        
        # Преобразуем в response модели
        api_keys = []
        for response in api_key_responses:
            key_data = response.to_dict()
            # Добавляем description из metadata
            key_data["description"] = key_data.get("metadata", {}).get("description")
            api_keys.append(ApiKeyResponse(**key_data))
        
        return ApiKeyListResponse(
            api_keys=api_keys,
            total_count=len(api_keys),  # В реальной реализации нужен отдельный count запрос
            page=page,
            per_page=per_page
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"List API keys error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list API keys: {str(e)}"
        )


@router.get(
    "/keys/{key_id}",
    response_model=ApiKeyResponse,
    summary="Получить API ключ",
    description="Получает информацию об API ключе по ID"
)
async def get_api_key(
    key_id: int,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Получение API ключа по ID"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        # Получаем ключ
        result = await manage_keys_usecase.get_api_key(key_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        # Формируем ответ
        key_data = result.to_dict()
        key_data["description"] = key_data.get("metadata", {}).get("description")
        return ApiKeyResponse(**key_data)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get API key: {str(e)}"
        )


@router.put(
    "/keys/{key_id}",
    response_model=ApiKeyResponse,
    summary="Обновить API ключ",
    description="Обновляет настройки API ключа"
)
async def update_api_key(
    key_id: int,
    request_data: UpdateApiKeyRequest,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Обновление API ключа"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        # Преобразуем план в enum если указан
        plan_enum = None
        if request_data.plan:
            from ....domain.entity.api_key import ApiKeyPlan
            try:
                plan_enum = ApiKeyPlan(request_data.plan.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid plan: {request_data.plan}"
                )
        
        # Обновляем ключ
        result = await manage_keys_usecase.update_api_key(
            api_key_id=key_id,
            client_name=request_data.client_name,
            contact_email=request_data.contact_email,
            plan=plan_enum,
            requests_per_minute=request_data.requests_per_minute,
            requests_per_day=request_data.requests_per_day,
            requests_per_month=request_data.requests_per_month,
            allowed_ips=request_data.allowed_ips,
            webhook_url=request_data.webhook_url,
            metadata={"description": request_data.description} if request_data.description else None
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        # Формируем ответ
        key_data = result.to_dict()
        key_data["description"] = key_data.get("metadata", {}).get("description")
        return ApiKeyResponse(**key_data)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Update API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update API key: {str(e)}"
        )


@router.post(
    "/keys/{key_id}/suspend",
    response_model=ApiKeyResponse,
    summary="Приостановить API ключ",
    description="Приостанавливает API ключ (можно восстановить)"
)
async def suspend_api_key(
    key_id: int,
    reason: Optional[str] = None,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Приостановка API ключа"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        result = await manage_keys_usecase.suspend_api_key(key_id, reason)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        key_data = result.to_dict()
        key_data["description"] = key_data.get("metadata", {}).get("description")
        return ApiKeyResponse(**key_data)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Suspend API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to suspend API key: {str(e)}"
        )


@router.post(
    "/keys/{key_id}/activate",
    response_model=ApiKeyResponse,
    summary="Активировать API ключ",
    description="Активирует приостановленный API ключ"
)
async def activate_api_key(
    key_id: int,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Активация API ключа"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        result = await manage_keys_usecase.activate_api_key(key_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        key_data = result.to_dict()
        key_data["description"] = key_data.get("metadata", {}).get("description")
        return ApiKeyResponse(**key_data)
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Activate API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate API key: {str(e)}"
        )


@router.post(
    "/keys/{key_id}/rotate",
    response_model=ApiKeyCreatedResponse,
    summary="Ротация API ключа",
    description="Создает новый ключ и деактивирует старый"
)
async def rotate_api_key(
    key_id: int,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Ротация API ключа"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        result = await manage_keys_usecase.rotate_api_key(key_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        response_data = result.to_dict(include_key=True)
        return ApiKeyCreatedResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Rotate API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rotate API key: {str(e)}"
        )


@router.delete(
    "/keys/{key_id}",
    summary="Удалить API ключ",
    description="Безвозвратно удаляет API ключ"
)
async def delete_api_key(
    key_id: int,
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Удаление API ключа"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        success = await manage_keys_usecase.delete_api_key(key_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        return {"message": f"API key {key_id} deleted successfully", "timestamp": time.time()}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Delete API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete API key: {str(e)}"
        )


@router.get(
    "/stats",
    summary="Глобальная статистика",
    description="Возвращает глобальную статистику по всем API ключам"
)
async def get_global_stats(
    admin=Depends(verify_admin_credentials),
    dependencies: Dict[str, Any] = Depends(get_dependencies)
):
    """Глобальная статистика API ключей"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        usage_repo = dependencies.get("usage_repository")
        
        if not manage_keys_usecase:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key management service unavailable"
            )
        
        # Получаем статистику ключей
        keys_stats = await manage_keys_usecase.get_global_statistics()
        
        # Получаем статистику использования
        usage_stats = {}
        if usage_repo:
            usage_stats = await usage_repo.get_global_usage_stats(hours=24)
        
        return {
            "api_keys_statistics": keys_stats,
            "usage_statistics": usage_stats,
            "timestamp": time.time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Global stats error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get global stats: {str(e)}"
        )