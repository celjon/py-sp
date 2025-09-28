"""
AntiSpam API Python SDK v2.0
Production-ready клиент для интеграции с AntiSpam Detection API
"""

import asyncio
import time
import json
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
import requests
from urllib.parse import urljoin


class ApiKeyPlan(Enum):
    """Тарифные планы API ключей"""
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class DetectionResult:
    """Результат детекции спама"""
    is_spam: bool
    confidence: float
    primary_reason: str
    reasons: List[str]
    recommended_action: str
    notes: str
    processing_time_ms: float
    detection_id: str
    api_version: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DetectionResult":
        """Создает DetectionResult из словаря"""
        return cls(
            is_spam=data["is_spam"],
            confidence=data["confidence"],
            primary_reason=data["primary_reason"],
            reasons=data["reasons"],
            recommended_action=data["recommended_action"],
            notes=data["notes"],
            processing_time_ms=data["processing_time_ms"],
            detection_id=data["detection_id"],
            api_version=data["api_version"]
        )


@dataclass
class BatchDetectionResult:
    """Результат batch детекции"""
    results: List[DetectionResult]
    summary: Dict[str, Any]
    total_processing_time_ms: float
    batch_id: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchDetectionResult":
        """Создает BatchDetectionResult из словаря"""
        results = [DetectionResult.from_dict(r) for r in data["results"]]
        return cls(
            results=results,
            summary=data["summary"],
            total_processing_time_ms=data["total_processing_time_ms"],
            batch_id=data["batch_id"]
        )


@dataclass
class UsageStats:
    """Статистика использования API"""
    api_key_info: Dict[str, Any]
    usage_stats: Dict[str, Any]
    rate_limits: Dict[str, Any]
    billing_period: Dict[str, Any]
    generated_at: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UsageStats":
        """Создает UsageStats из словаря"""
        return cls(
            api_key_info=data["api_key_info"],
            usage_stats=data["usage_stats"],
            rate_limits=data["rate_limits"],
            billing_period=data["billing_period"],
            generated_at=data["generated_at"]
        )


@dataclass
class ApiKeyInfo:
    """Информация об API ключе"""
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
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApiKeyInfo":
        """Создает ApiKeyInfo из словаря"""
        return cls(
            id=data["id"],
            client_name=data["client_name"],
            contact_email=data["contact_email"],
            key_prefix=data["key_prefix"],
            plan=data["plan"],
            status=data["status"],
            rate_limits=data["rate_limits"],
            created_at=data["created_at"],
            last_used_at=data.get("last_used_at"),
            expires_at=data.get("expires_at")
        )


class AntiSpamError(Exception):
    """Базовый класс ошибок AntiSpam SDK"""
    pass


class AuthenticationError(AntiSpamError):
    """Ошибка аутентификации"""
    pass


class RateLimitError(AntiSpamError):
    """Ошибка превышения rate limit"""
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after


class ValidationError(AntiSpamError):
    """Ошибка валидации данных"""
    pass


class ApiError(AntiSpamError):
    """Общая ошибка API"""
    def __init__(self, message: str, status_code: int = None, error_code: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class AntiSpamClient:
    """
    Production-ready AntiSpam API Client
    
    Features:
    - Асинхронные и синхронные методы
    - Автоматический retry с exponential backoff
    - Обработка rate limiting
    - Детальное логирование
    - Type hints и validation
    - Connection pooling
    - Timeout management
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.antispam.com",
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        enable_logging: bool = False
    ):
        """
        Инициализация клиента
        
        Args:
            api_key: API ключ для аутентификации
            base_url: Базовый URL API
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество повторных попыток
            retry_delay: Задержка между попытками (секунды)
            enable_logging: Включить детальное логирование
        """
        if not api_key:
            raise ValueError("API key is required")
        
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.enable_logging = enable_logging
        
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"antispam-python-sdk/2.0.0",
            "Accept": "application/json"
        }
        
        self._session = None
        self._async_session = None
        
        if self.enable_logging:
            import logging
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = None
    
    def __enter__(self):
        """Context manager для синхронного использования"""
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Закрытие сессии"""
        if self._session:
            self._session.close()
            self._session = None
    
    async def __aenter__(self):
        """Async context manager"""
        self._async_session = aiohttp.ClientSession(
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие async сессии"""
        if self._async_session:
            await self._async_session.close()
            self._async_session = None
    
    
    def detect(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> DetectionResult:
        """
        Синхронная детекция спама
        
        Args:
            text: Текст для проверки
            context: Дополнительный контекст
            **kwargs: Дополнительные параметры
            
        Returns:
            DetectionResult с результатом детекции
            
        Raises:
            ValidationError: Некорректные входные данные
            RateLimitError: Превышен rate limit
            AuthenticationError: Ошибка аутентификации
            ApiError: Общая ошибка API
        """
        self._validate_text(text)
        
        payload = {"text": text}
        if context:
            payload["context"] = context
        payload.update(kwargs)
        
        response_data = self._make_request("POST", "/api/v1/detect", payload)
        return DetectionResult.from_dict(response_data)
    
    def detect_batch(
        self,
        messages: List[Union[str, Dict[str, Any]]],
        **kwargs
    ) -> BatchDetectionResult:
        """
        Синхронная batch детекция
        
        Args:
            messages: Список сообщений (строки или объекты с text и context)
            **kwargs: Дополнительные параметры
            
        Returns:
            BatchDetectionResult с результатами
        """
        if not messages:
            raise ValidationError("Messages list cannot be empty")
        
        if len(messages) > 100:
            raise ValidationError("Maximum 100 messages per batch")
        
        normalized_messages = []
        for msg in messages:
            if isinstance(msg, str):
                normalized_messages.append({"text": msg})
            elif isinstance(msg, dict) and "text" in msg:
                normalized_messages.append(msg)
            else:
                raise ValidationError("Each message must be a string or dict with 'text' field")
        
        payload = {"messages": normalized_messages}
        payload.update(kwargs)
        
        response_data = self._make_request("POST", "/api/v1/detect/batch", payload)
        return BatchDetectionResult.from_dict(response_data)
    
    def get_usage_stats(self, hours: int = 24) -> UsageStats:
        """
        Получение статистики использования
        
        Args:
            hours: Период в часах (1-168)
            
        Returns:
            UsageStats со статистикой
        """
        if not 1 <= hours <= 168:
            raise ValidationError("Hours must be between 1 and 168")
        
        response_data = self._make_request("GET", f"/api/v1/stats?hours={hours}")
        return UsageStats.from_dict(response_data)
    
    def get_api_info(self) -> Dict[str, Any]:
        """Получение информации об API"""
        return self._make_request("GET", "/api/v1/info")
    
    def health_check(self) -> Dict[str, Any]:
        """Health check API"""
        return self._make_request("GET", "/api/v1/health")
    
    
    async def detect_async(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> DetectionResult:
        """Асинхронная детекция спама"""
        self._validate_text(text)
        
        payload = {"text": text}
        if context:
            payload["context"] = context
        payload.update(kwargs)
        
        response_data = await self._make_request_async("POST", "/api/v1/detect", payload)
        return DetectionResult.from_dict(response_data)
    
    async def detect_batch_async(
        self,
        messages: List[Union[str, Dict[str, Any]]],
        **kwargs
    ) -> BatchDetectionResult:
        """Асинхронная batch детекция"""
        if not messages:
            raise ValidationError("Messages list cannot be empty")
        
        if len(messages) > 100:
            raise ValidationError("Maximum 100 messages per batch")
        
        normalized_messages = []
        for msg in messages:
            if isinstance(msg, str):
                normalized_messages.append({"text": msg})
            elif isinstance(msg, dict) and "text" in msg:
                normalized_messages.append(msg)
            else:
                raise ValidationError("Each message must be a string or dict with 'text' field")
        
        payload = {"messages": normalized_messages}
        payload.update(kwargs)
        
        response_data = await self._make_request_async("POST", "/api/v1/detect/batch", payload)
        return BatchDetectionResult.from_dict(response_data)
    
    async def get_usage_stats_async(self, hours: int = 24) -> UsageStats:
        """Асинхронное получение статистики"""
        if not 1 <= hours <= 168:
            raise ValidationError("Hours must be between 1 and 168")
        
        response_data = await self._make_request_async("GET", f"/api/v1/stats?hours={hours}")
        return UsageStats.from_dict(response_data)
    
    async def get_api_info_async(self) -> Dict[str, Any]:
        """Асинхронное получение информации об API"""
        return await self._make_request_async("GET", "/api/v1/info")
    
    async def health_check_async(self) -> Dict[str, Any]:
        """Асинхронный health check"""
        return await self._make_request_async("GET", "/api/v1/health")
    
    
    def _validate_text(self, text: str) -> None:
        """Валидация текста"""
        if not isinstance(text, str):
            raise ValidationError("Text must be a string")
        
        if not text.strip():
            raise ValidationError("Text cannot be empty or only whitespace")
        
        if len(text) > 10000:
            raise ValidationError("Text cannot exceed 10,000 characters")
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Выполняет синхронный HTTP запрос с retry logic"""
        url = urljoin(self.base_url, endpoint)
        session = self._session or requests
        
        for attempt in range(self.max_retries + 1):
            try:
                if self.logger:
                    self.logger.debug(f"Making {method} request to {url}, attempt {attempt + 1}")
                
                if method == "GET":
                    response = session.get(url, headers=self.headers, timeout=self.timeout)
                else:
                    response = session.post(url, headers=self.headers, json=data, timeout=self.timeout)
                
                return self._handle_response(response, attempt)
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** attempt)
                    if self.logger:
                        self.logger.warning(f"Request failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    raise ApiError(f"Request failed after {self.max_retries + 1} attempts: {e}")
    
    async def _make_request_async(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Выполняет асинхронный HTTP запрос с retry logic"""
        if not self._async_session:
            raise RuntimeError("Async session not initialized. Use 'async with' context manager")
        
        url = urljoin(self.base_url, endpoint)
        
        for attempt in range(self.max_retries + 1):
            try:
                if self.logger:
                    self.logger.debug(f"Making async {method} request to {url}, attempt {attempt + 1}")
                
                if method == "GET":
                    async with self._async_session.get(url) as response:
                        return await self._handle_response_async(response, attempt)
                else:
                    async with self._async_session.post(url, json=data) as response:
                        return await self._handle_response_async(response, attempt)
                        
            except (aiohttp.ClientTimeout, aiohttp.ClientError) as e:
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** attempt)
                    if self.logger:
                        self.logger.warning(f"Async request failed: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise ApiError(f"Async request failed after {self.max_retries + 1} attempts: {e}")
    
    def _handle_response(self, response: requests.Response, attempt: int) -> Dict[str, Any]:
        """Обрабатывает синхронный ответ"""
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            raise AuthenticationError("Invalid API key")
        elif response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            if attempt < self.max_retries:
                if self.logger:
                    self.logger.warning(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                raise RateLimitError("Rate limit exceeded", retry_after)
            else:
                raise RateLimitError(f"Rate limit exceeded. Retry after {retry_after} seconds", retry_after)
        elif response.status_code == 422:
            error_detail = response.json().get("detail", "Validation error")
            raise ValidationError(f"Validation failed: {error_detail}")
        else:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", f"HTTP {response.status_code}")
                raise ApiError(error_msg, response.status_code, error_data.get("error_code"))
            except ValueError:
                raise ApiError(f"HTTP {response.status_code}: {response.text}", response.status_code)
    
    async def _handle_response_async(self, response: aiohttp.ClientResponse, attempt: int) -> Dict[str, Any]:
        """Обрабатывает асинхронный ответ"""
        if response.status == 200:
            return await response.json()
        elif response.status == 401:
            raise AuthenticationError("Invalid API key")
        elif response.status == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            if attempt < self.max_retries:
                if self.logger:
                    self.logger.warning(f"Rate limited. Waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                raise RateLimitError("Rate limit exceeded", retry_after)
            else:
                raise RateLimitError(f"Rate limit exceeded. Retry after {retry_after} seconds", retry_after)
        elif response.status == 422:
            error_data = await response.json()
            error_detail = error_data.get("detail", "Validation error")
            raise ValidationError(f"Validation failed: {error_detail}")
        else:
            try:
                error_data = await response.json()
                error_msg = error_data.get("error", f"HTTP {response.status}")
                raise ApiError(error_msg, response.status, error_data.get("error_code"))
            except (ValueError, aiohttp.ContentTypeError):
                text = await response.text()
                raise ApiError(f"HTTP {response.status}: {text}", response.status)



def detect_spam(
    text: str,
    api_key: str,
    context: Optional[Dict[str, Any]] = None,
    base_url: str = "https://api.antispam.com"
) -> DetectionResult:
    """
    Convenience function для быстрой проверки спама
    
    Args:
        text: Текст для проверки
        api_key: API ключ
        context: Дополнительный контекст
        base_url: Базовый URL API
        
    Returns:
        DetectionResult
    """
    with AntiSpamClient(api_key, base_url) as client:
        return client.detect(text, context)


async def detect_spam_async(
    text: str,
    api_key: str,
    context: Optional[Dict[str, Any]] = None,
    base_url: str = "https://api.antispam.com"
) -> DetectionResult:
    """Асинхронная convenience function"""
    async with AntiSpamClient(api_key, base_url) as client:
        return await client.detect_async(text, context)



if __name__ == "__main__":
    import asyncio
    
    API_KEY = "antispam_your_api_key_here"
    
    print("=== Синхронный пример ===")
    with AntiSpamClient(API_KEY, enable_logging=True) as client:
        result = client.detect("Хочешь заработать быстрые деньги? Пиши в ЛС!")
        print(f"Spam: {result.is_spam}, Confidence: {result.confidence:.2f}")
        print(f"Action: {result.recommended_action}")
        
        messages = [
            "Привет, как дела?",
            "СРОЧНО! ЗАРАБОТАЙ МИЛЛИОН!",
            "Спасибо за информацию"
        ]
        batch_result = client.detect_batch(messages)
        print(f"Batch: {batch_result.summary}")
        
        stats = client.get_usage_stats(hours=24)
        print(f"Requests today: {stats.usage_stats.get('total_requests', 0)}")
    
    async def async_example():
        print("\n=== Асинхронный пример ===")
        async with AntiSpamClient(API_KEY) as client:
            result = await client.detect_async("Хочешь заработать?")
            print(f"Async result: {result.is_spam}")
            
            health = await client.health_check_async()
            print(f"API Status: {health.get('status')}")
    
    asyncio.run(async_example())