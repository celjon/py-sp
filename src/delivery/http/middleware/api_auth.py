import time
from typing import Dict, Any, Callable
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from ...domain.entity.api_key import ApiKey
from ...domain.entity.client_usage import RateLimitStatus
from ...adapter.repository.api_key_repository import ApiKeyRepository
from ...adapter.repository.usage_repository import UsageRepository


class ApiAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware для аутентификации и авторизации API запросов
    Проверяет API ключи и rate limiting
    """
    
    def __init__(
        self,
        app,
        api_key_repo: ApiKeyRepository,
        usage_repo: UsageRepository,
        protected_paths: list = None
    ):
        super().__init__(app)
        self.api_key_repo = api_key_repo
        self.usage_repo = usage_repo
        
        # Пути, требующие авторизации
        self.protected_paths = protected_paths or [
            "/api/v1/detect",
            "/api/v1/detect/batch",
            "/api/v1/stats",
            "/api/v1/account/"
        ]
        
        # Кэш для API ключей (в production использовать Redis)
        self._key_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 минут
        
        print(f"🔐 API Auth middleware инициализирован для путей: {self.protected_paths}")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Основная логика middleware"""
        
        # Проверяем, нужна ли авторизация для данного пути
        if not self._requires_auth(request.url.path):
            return await call_next(request)
        
        try:
            # Извлекаем API ключ из запроса
            api_key_str = self._extract_api_key(request)
            if not api_key_str:
                return self._unauthorized_response("API key is required")
            
            # Получаем и валидируем API ключ
            api_key = await self._get_and_validate_api_key(api_key_str)
            if not api_key:
                return self._unauthorized_response("Invalid or expired API key")
            
            # Проверяем IP адрес
            client_ip = self._get_client_ip(request)
            if not api_key.check_ip_allowed(client_ip):
                return self._forbidden_response(f"IP address {client_ip} not allowed")
            
            # Проверяем rate limiting
            rate_limit_error = await self._check_rate_limits(api_key, client_ip)
            if rate_limit_error:
                return self._rate_limit_response(rate_limit_error)
            
            # Добавляем информацию об API ключе в request state
            request.state.api_key = api_key
            request.state.client_ip = client_ip
            request.state.authenticated = True
            
            # Продолжаем обработку запроса
            response = await call_next(request)
            
            # Добавляем заголовки с информацией о rate limiting
            await self._add_rate_limit_headers(response, api_key)
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"API Auth middleware error: {e}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Authentication service unavailable"}
            )
    
    def _requires_auth(self, path: str) -> bool:
        """Проверяет, требует ли путь авторизации"""
        return any(path.startswith(protected_path) for protected_path in self.protected_paths)
    
    def _extract_api_key(self, request: Request) -> str:
        """Извлекает API ключ из запроса"""
        # Проверяем Authorization header (Bearer token)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Убираем "Bearer "
        
        # Проверяем X-API-Key header
        api_key_header = request.headers.get("X-API-Key")
        if api_key_header:
            return api_key_header
        
        # Проверяем query parameter
        api_key_param = request.query_params.get("api_key")
        if api_key_param:
            return api_key_param
        
        return None
    
    async def _get_and_validate_api_key(self, api_key_str: str) -> ApiKey:
        """Получает и валидирует API ключ"""
        # Проверяем кэш
        cache_key = f"api_key:{ApiKey.hash_key(api_key_str)}"
        cached = self._key_cache.get(cache_key)
        
        if cached and time.time() - cached["timestamp"] < self._cache_ttl:
            # Восстанавливаем объект из кэша
            if cached["valid"]:
                return cached["api_key"]
            else:
                return None
        
        # Получаем из БД
        key_hash = ApiKey.hash_key(api_key_str)
        api_key = await self.api_key_repo.get_api_key_by_hash(key_hash)
        
        # Валидируем ключ
        is_valid = api_key and api_key.is_valid and api_key.verify_key(api_key_str)
        
        # Кэшируем результат
        self._key_cache[cache_key] = {
            "timestamp": time.time(),
            "valid": is_valid,
            "api_key": api_key if is_valid else None
        }
        
        return api_key if is_valid else None
    
    async def _check_rate_limits(self, api_key: ApiKey, client_ip: str) -> str:
        """Проверяет rate limiting для API ключа"""
        try:
            # Получаем текущий статус rate limiting
            rate_limit_status = await self.usage_repo.get_rate_limit_status(api_key.id)
            
            # Получаем лимиты для ключа
            rate_limits = api_key.get_rate_limits()
            
            # Проверяем лимиты
            limit_error = rate_limit_status.check_limits(rate_limits)
            if limit_error:
                return limit_error
            
            # Инкрементируем счетчики (это будет записано в БД после успешного запроса)
            rate_limit_status.increment_counters()
            
            return None
            
        except Exception as e:
            print(f"Rate limit check error: {e}")
            # В случае ошибки разрешаем запрос
            return None
    
    def _get_client_ip(self, request: Request) -> str:
        """Получает IP адрес клиента"""
        # Проверяем заголовки от reverse proxy
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # Fallback на прямое соединение
        if request.client:
            return request.client.host
        
        return "unknown"
    
    async def _add_rate_limit_headers(self, response: Response, api_key: ApiKey):
        """Добавляет заголовки с информацией о rate limiting"""
        try:
            rate_limits = api_key.get_rate_limits()
            rate_limit_status = await self.usage_repo.get_rate_limit_status(api_key.id)
            remaining = rate_limit_status.get_remaining_requests(rate_limits)
            
            # Добавляем заголовки
            response.headers["X-RateLimit-Limit-Minute"] = str(rate_limits.get("requests_per_minute", -1))
            response.headers["X-RateLimit-Limit-Day"] = str(rate_limits.get("requests_per_day", -1))
            response.headers["X-RateLimit-Remaining-Minute"] = str(remaining.get("minute", -1))
            response.headers["X-RateLimit-Remaining-Day"] = str(remaining.get("day", -1))
            response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)
            
        except Exception as e:
            print(f"Failed to add rate limit headers: {e}")
    
    def _unauthorized_response(self, message: str) -> JSONResponse:
        """Возвращает ответ 401 Unauthorized"""
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "Unauthorized",
                "message": message,
                "timestamp": time.time()
            },
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    def _forbidden_response(self, message: str) -> JSONResponse:
        """Возвращает ответ 403 Forbidden"""
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": "Forbidden",
                "message": message,
                "timestamp": time.time()
            }
        )
    
    def _rate_limit_response(self, message: str) -> JSONResponse:
        """Возвращает ответ 429 Too Many Requests"""
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "Rate limit exceeded",
                "message": message,
                "retry_after": 60,
                "timestamp": time.time()
            },
            headers={"Retry-After": "60"}
        )
    
    def clear_cache(self):
        """Очищает кэш API ключей (для использования в тестах)"""
        self._key_cache.clear()


class ApiKeyExtractorMiddleware(BaseHTTPMiddleware):
    """
    Легковесный middleware для извлечения API ключа из запроса
    Используется когда нужна только информация о ключе без полной авторизации
    """
    
    def __init__(self, app, api_key_repo: ApiKeyRepository):
        super().__init__(app)
        self.api_key_repo = api_key_repo
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Извлекает API ключ и добавляет в request state"""
        
        # Извлекаем API ключ
        api_key_str = self._extract_api_key(request)
        
        if api_key_str:
            try:
                # Получаем API ключ из БД
                key_hash = ApiKey.hash_key(api_key_str)
                api_key = await self.api_key_repo.get_api_key_by_hash(key_hash)
                
                if api_key and api_key.verify_key(api_key_str):
                    request.state.api_key = api_key
                    request.state.authenticated = True
                else:
                    request.state.api_key = None
                    request.state.authenticated = False
            except Exception as e:
                print(f"API key extraction error: {e}")
                request.state.api_key = None
                request.state.authenticated = False
        else:
            request.state.api_key = None
            request.state.authenticated = False
        
        return await call_next(request)
    
    def _extract_api_key(self, request: Request) -> str:
        """Извлекает API ключ из запроса"""
        # Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]
        
        # X-API-Key header
        api_key_header = request.headers.get("X-API-Key")
        if api_key_header:
            return api_key_header
        
        # Query parameter (не рекомендуется для production)
        api_key_param = request.query_params.get("api_key")
        if api_key_param:
            return api_key_param
        
        return None