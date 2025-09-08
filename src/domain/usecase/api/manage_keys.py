from typing import Protocol, List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from ...entity.api_key import ApiKey, ApiKeyStatus, ApiKeyPlan
from ...entity.client_usage import ApiUsageStats, UsagePeriod


@dataclass
class CreateApiKeyRequest:
    """Запрос на создание API ключа"""
    client_name: str
    contact_email: str
    plan: ApiKeyPlan = ApiKeyPlan.FREE
    
    # Кастомные лимиты (опционально)
    requests_per_minute: Optional[int] = None
    requests_per_day: Optional[int] = None
    requests_per_month: Optional[int] = None
    
    # Ограничения безопасности
    allowed_ips: List[str] = None
    webhook_url: Optional[str] = None
    expires_in_days: Optional[int] = None
    
    # Дополнительные метаданные
    metadata: Dict[str, Any] = None


@dataclass
class ApiKeyResponse:
    """Ответ с информацией об API ключе"""
    api_key: ApiKey
    raw_key: Optional[str] = None  # Только при создании
    
    def to_dict(self, include_key: bool = False) -> Dict[str, Any]:
        """Преобразует в словарь для JSON ответа"""
        result = self.api_key.to_public_dict()
        
        if include_key and self.raw_key:
            result["api_key"] = self.raw_key
            result["warning"] = "Store this key securely. It will not be shown again."
        
        return result


class ApiKeyRepository(Protocol):
    """Протокол репозитория API ключей"""
    async def create_api_key(self, api_key: ApiKey) -> ApiKey: ...
    async def get_api_key_by_id(self, api_key_id: int) -> Optional[ApiKey]: ...
    async def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]: ...
    async def get_api_keys_by_client(self, client_name: str) -> List[ApiKey]: ...
    async def update_api_key(self, api_key: ApiKey) -> ApiKey: ...
    async def delete_api_key(self, api_key_id: int) -> bool: ...
    async def get_keys_statistics(self) -> dict: ...
    async def search_api_keys(
        self, 
        client_name: Optional[str] = None,
        plan: Optional[ApiKeyPlan] = None,
        status: Optional[ApiKeyStatus] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ApiKey]: ...


class UsageRepository(Protocol):
    """Протокол репозитория для статистики использования"""
    async def get_usage_stats(
        self, 
        api_key_id: int, 
        period: UsagePeriod,
        start_time: datetime,
        end_time: Optional[datetime] = None
    ) -> ApiUsageStats: ...


class ManageApiKeysUseCase:
    """Use case для управления API ключами"""
    
    def __init__(
        self,
        api_key_repo: ApiKeyRepository,
        usage_repo: Optional[UsageRepository] = None
    ):
        self.api_key_repo = api_key_repo
        self.usage_repo = usage_repo
    
    async def create_api_key(self, request: CreateApiKeyRequest) -> ApiKeyResponse:
        """
        Создает новый API ключ
        
        Args:
            request: Запрос на создание ключа
            
        Returns:
            Ответ с созданным ключом
        """
        # Валидируем запрос
        self._validate_create_request(request)
        
        # Генерируем новый API ключ
        raw_key = ApiKey.generate_key()
        
        # Создаем доменную сущность
        api_key = ApiKey(
            client_name=request.client_name,
            contact_email=request.contact_email,
            plan=request.plan,
            allowed_ips=request.allowed_ips or [],
            webhook_url=request.webhook_url,
            metadata=request.metadata or {}
        )
        
        # Устанавливаем кастомные лимиты если указаны
        if request.requests_per_minute is not None:
            api_key.requests_per_minute = request.requests_per_minute
        if request.requests_per_day is not None:
            api_key.requests_per_day = request.requests_per_day
        if request.requests_per_month is not None:
            api_key.requests_per_month = request.requests_per_month
        
        # Устанавливаем срок истечения
        if request.expires_in_days:
            api_key.expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)
        
        # Хешируем и сохраняем ключ
        api_key.set_key(raw_key)
        
        # Сохраняем в БД
        created_key = await self.api_key_repo.create_api_key(api_key)
        
        return ApiKeyResponse(api_key=created_key, raw_key=raw_key)
    
    async def get_api_key(self, api_key_id: int) -> Optional[ApiKeyResponse]:
        """Получает API ключ по ID"""
        api_key = await self.api_key_repo.get_api_key_by_id(api_key_id)
        
        if not api_key:
            return None
        
        return ApiKeyResponse(api_key=api_key)
    
    async def list_api_keys(
        self,
        client_name: Optional[str] = None,
        plan: Optional[ApiKeyPlan] = None,
        status: Optional[ApiKeyStatus] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ApiKeyResponse]:
        """Получает список API ключей с фильтрами"""
        api_keys = await self.api_key_repo.search_api_keys(
            client_name=client_name,
            plan=plan,
            status=status,
            is_active=is_active,
            limit=limit,
            offset=offset
        )
        
        return [ApiKeyResponse(api_key=key) for key in api_keys]
    
    async def update_api_key(
        self,
        api_key_id: int,
        client_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        plan: Optional[ApiKeyPlan] = None,
        requests_per_minute: Optional[int] = None,
        requests_per_day: Optional[int] = None,
        requests_per_month: Optional[int] = None,
        allowed_ips: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ApiKeyResponse]:
        """Обновляет API ключ"""
        # Получаем существующий ключ
        api_key = await self.api_key_repo.get_api_key_by_id(api_key_id)
        if not api_key:
            return None
        
        # Обновляем поля если они указаны
        if client_name is not None:
            api_key.client_name = client_name
        if contact_email is not None:
            api_key.contact_email = contact_email
        if plan is not None:
            api_key.plan = plan
        if requests_per_minute is not None:
            api_key.requests_per_minute = requests_per_minute
        if requests_per_day is not None:
            api_key.requests_per_day = requests_per_day
        if requests_per_month is not None:
            api_key.requests_per_month = requests_per_month
        if allowed_ips is not None:
            api_key.allowed_ips = allowed_ips
        if webhook_url is not None:
            api_key.webhook_url = webhook_url
        if metadata is not None:
            api_key.metadata.update(metadata)
        
        # Сохраняем изменения
        updated_key = await self.api_key_repo.update_api_key(api_key)
        
        return ApiKeyResponse(api_key=updated_key)
    
    async def suspend_api_key(self, api_key_id: int, reason: str = None) -> Optional[ApiKeyResponse]:
        """Приостанавливает API ключ"""
        api_key = await self.api_key_repo.get_api_key_by_id(api_key_id)
        if not api_key:
            return None
        
        api_key.suspend(reason)
        updated_key = await self.api_key_repo.update_api_key(api_key)
        
        return ApiKeyResponse(api_key=updated_key)
    
    async def revoke_api_key(self, api_key_id: int, reason: str = None) -> Optional[ApiKeyResponse]:
        """Отзывает API ключ"""
        api_key = await self.api_key_repo.get_api_key_by_id(api_key_id)
        if not api_key:
            return None
        
        api_key.revoke(reason)
        updated_key = await self.api_key_repo.update_api_key(api_key)
        
        return ApiKeyResponse(api_key=updated_key)
    
    async def activate_api_key(self, api_key_id: int) -> Optional[ApiKeyResponse]:
        """Активирует приостановленный API ключ"""
        api_key = await self.api_key_repo.get_api_key_by_id(api_key_id)
        if not api_key:
            return None
        
        # Можно активировать только приостановленные ключи
        if api_key.status != ApiKeyStatus.SUSPENDED:
            raise ValueError("Can only activate suspended API keys")
        
        api_key.status = ApiKeyStatus.ACTIVE
        api_key.updated_at = datetime.utcnow()
        
        updated_key = await self.api_key_repo.update_api_key(api_key)
        
        return ApiKeyResponse(api_key=updated_key)
    
    async def delete_api_key(self, api_key_id: int) -> bool:
        """Удаляет API ключ (soft delete)"""
        return await self.api_key_repo.delete_api_key(api_key_id)
    
    async def get_api_key_usage_stats(
        self,
        api_key_id: int,
        period: UsagePeriod = UsagePeriod.DAY,
        days: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Получает статистику использования API ключа"""
        if not self.usage_repo:
            return None
        
        # Проверяем что ключ существует
        api_key = await self.api_key_repo.get_api_key_by_id(api_key_id)
        if not api_key:
            return None
        
        # Получаем статистику
        start_time = datetime.utcnow() - timedelta(days=days)
        usage_stats = await self.usage_repo.get_usage_stats(
            api_key_id=api_key_id,
            period=period,
            start_time=start_time
        )
        
        result = usage_stats.to_dict()
        result["api_key_info"] = {
            "id": api_key.id,
            "client_name": api_key.client_name,
            "plan": api_key.plan.value,
            "status": api_key.status.value
        }
        
        return result
    
    async def get_global_statistics(self) -> Dict[str, Any]:
        """Получает глобальную статистику по всем API ключам"""
        stats = await self.api_key_repo.get_keys_statistics()
        
        return {
            "api_keys": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def rotate_api_key(self, api_key_id: int) -> Optional[ApiKeyResponse]:
        """
        Создает новый ключ для существующего клиента и деактивирует старый
        """
        # Получаем старый ключ
        old_key = await self.api_key_repo.get_api_key_by_id(api_key_id)
        if not old_key:
            return None
        
        # Создаем новый ключ с теми же настройками
        create_request = CreateApiKeyRequest(
            client_name=old_key.client_name,
            contact_email=old_key.contact_email,
            plan=old_key.plan,
            requests_per_minute=old_key.requests_per_minute,
            requests_per_day=old_key.requests_per_day,
            requests_per_month=old_key.requests_per_month,
            allowed_ips=old_key.allowed_ips,
            webhook_url=old_key.webhook_url,
            metadata=old_key.metadata.copy()
        )
        
        # Создаем новый ключ
        new_key_response = await self.create_api_key(create_request)
        
        # Деактивируем старый ключ
        old_key.revoke("Key rotated")
        await self.api_key_repo.update_api_key(old_key)
        
        # Добавляем информацию о ротации в метаданные
        new_key_response.api_key.metadata["rotated_from"] = api_key_id
        new_key_response.api_key.metadata["rotation_date"] = datetime.utcnow().isoformat()
        await self.api_key_repo.update_api_key(new_key_response.api_key)
        
        return new_key_response
    
    def _validate_create_request(self, request: CreateApiKeyRequest):
        """Валидирует запрос на создание API ключа"""
        if not request.client_name or len(request.client_name.strip()) < 2:
            raise ValueError("Client name must be at least 2 characters long")
        
        if not request.contact_email or "@" not in request.contact_email:
            raise ValueError("Valid contact email is required")
        
        # Валидируем лимиты
        if request.requests_per_minute is not None and request.requests_per_minute < 0:
            raise ValueError("Requests per minute must be non-negative")
        
        if request.requests_per_day is not None and request.requests_per_day < 0:
            raise ValueError("Requests per day must be non-negative")
        
        if request.requests_per_month is not None and request.requests_per_month < 0:
            raise ValueError("Requests per month must be non-negative")
        
        # Валидируем IP адреса
        if request.allowed_ips:
            for ip in request.allowed_ips:
                if not self._is_valid_ip(ip):
                    raise ValueError(f"Invalid IP address: {ip}")
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Простая валидация IP адреса"""
        try:
            import ipaddress
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False