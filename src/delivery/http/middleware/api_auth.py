# src/delivery/http/middleware/api_auth.py
"""
Production-ready API Authentication Middleware
Интегрирует JWT аутентификацию, API ключи и rate limiting
"""

import time
import traceback
from typing import Dict, Any, Callable, Optional
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ....domain.entity.api_key import ApiKey
from ....domain.service.auth.jwt_service import JWTService, TokenType
from ....domain.service.rate_limit.rate_limiter import RateLimiter


class ApiAuthMiddleware(BaseHTTPMiddleware):
    """
    Production-ready API Authentication Middleware
    
    Features:
    - JWT token validation
    - API key authentication  
    - Rate limiting per API key
    - IP whitelisting
    - Detailed error responses
    - Performance monitoring
    """
    
    def __init__(
        self,
        app,
        jwt_service: JWTService,
        rate_limiter: RateLimiter,
        api_key_repo,  # Repository для получения API ключей
        protected_paths: list = None,
        require_auth_header: bool = True
    ):
        super().__init__(app)
        self.jwt_service = jwt_service
        self.rate_limiter = rate_limiter
        self.api_key_repo = api_key_repo
        self.require_auth_header = require_auth_header
        
        # Пути, требующие авторизации
        self.protected_paths = protected_paths or [
            "/api/v1/detect",
            "/api/v1/detect/batch", 
            "/api/v1/stats",
            "/api/v1/account"
        ]
        
        # Пути, которые НЕ требуют авторизации
        self.public_paths = [
            "/docs",
            "/openapi.json",
            "/health",
            "/",
            "/api/v1/info",
            "/api/v1/detectors"
        ]
        
        # Кэш для API ключей (в production использовать Redis)
        self._api_key_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 минут
        
        print(f"🔐 API Auth Middleware инициализирован")
        print(f"   Protected paths: {len(self.protected_paths)}")
        print(f"   Public paths: {len(self.public_paths)}")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Основная логика middleware"""
        start_time = time.time()
        
        try:
            # Проверяем, нужна ли авторизация для данного пути
            if not self._requires_auth(request.url.path):
                return await call_next(request)
            
            # Извлекаем и валидируем авторизационные данные
            auth_result = await self._authenticate_request(request)
            
            if not auth_result["success"]:
                return self._create_error_response(
                    status_code=auth_result["status_code"],
                    error=auth_result["error"],
                    details=auth_result.get("details")
                )
            
            api_key = auth_result["api_key"]
            client_ip = self._get_client_ip(request)
            
            # Проверяем IP whitelist
            if not self._check_ip_allowed(api_key, client_ip):
                return self._create_error_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error="IP address not allowed",
                    details=f"IP {client_ip} is not in the whitelist for this API key"
                )
            
            # Проверяем rate limiting
            rate_limit_result = await self.rate_limiter.check_rate_limit(api_key, client_ip)
            
            if rate_limit_result.is_rate_limited:
                return self._create_rate_limit_response(rate_limit_result)
            
            # Добавляем информацию об API ключе в request state
            request.state.api_key = api_key
            request.state.client_ip = client_ip
            request.state.authenticated = True
            request.state.auth_method = auth_result["auth_method"]
            
            # Продолжаем обработку запроса
            response = await call_next(request)
            
            # Записываем успешный запрос в rate limiter
            await self.rate_limiter.record_request(
                api_key=api_key,
                client_ip=client_ip,
                endpoint=request.url.path
            )
            
            # Добавляем заголовки с информацией о rate limiting
            await self._add_rate_limit_headers(response, api_key)
            
            # Добавляем заголовки производительности
            processing_time = (time.time() - start_time) * 1000
            response.headers["X-Processing-Time"] = f"{processing_time:.2f}ms"
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"API Auth middleware error: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            
            return self._create_error_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error="Authentication service unavailable",
                details="Internal authentication error"
            )
    
    def _requires_auth(self, path: str) -> bool:
        """Проверяет, требует ли путь авторизации"""
        # Сначала проверяем публичные пути
        for public_path in self.public_paths:
            if path.startswith(public_path):
                return False
        
        # Затем проверяем защищенные пути
        for protected_path in self.protected_paths:
            if path.startswith(protected_path):
                return True
        
        # По умолчанию требуем авторизацию для неизвестных путей
        return True
    
    async def _authenticate_request(self, request: Request) -> Dict[str, Any]:
        """
        Аутентифицирует запрос
        
        Returns:
            Dict с результатом аутентификации
        """
        try:
            # Метод 1: JWT Bearer token
            jwt_token = self._extract_jwt_token(request)
            if jwt_token:
                jwt_result = await self._authenticate_with_jwt(jwt_token)
                if jwt_result["success"]:
                    return jwt_result
            
            # Метод 2: API ключ
            api_key_str = self._extract_api_key(request)
            if api_key_str:
                api_key_result = await self._authenticate_with_api_key(api_key_str)
                if api_key_result["success"]:
                    return api_key_result
            
            # Нет валидных методов аутентификации
            return {
                "success": False,
                "status_code": status.HTTP_401_UNAUTHORIZED,
                "error": "Authentication required",
                "details": "Provide either JWT Bearer token or API key"
            }
            
        except Exception as e:
            print(f"Authentication error: {e}")
            return {
                "success": False,
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error": "Authentication service error",
                "details": str(e)
            }
    
    async def _authenticate_with_jwt(self, jwt_token: str) -> Dict[str, Any]:
        """Аутентификация через JWT токен"""
        try:
            # Валидируем JWT токен
            validation_result = self.jwt_service.validate_token(jwt_token, TokenType.ACCESS)
            
            if not validation_result.is_valid:
                return {
                    "success": False,
                    "status_code": status.HTTP_401_UNAUTHORIZED,
                    "error": "Invalid JWT token",
                    "details": validation_result.error
                }
            
            # Получаем API ключ из claims
            api_key_id = validation_result.claims.sub
            api_key = await self._get_api_key_by_id(int(api_key_id))
            
            if not api_key or not api_key.is_valid:
                return {
                    "success": False,
                    "status_code": status.HTTP_401_UNAUTHORIZED,
                    "error": "API key not found or inactive",
                    "details": "The API key associated with this JWT token is not valid"
                }
            
            return {
                "success": True,
                "api_key": api_key,
                "auth_method": "jwt",
                "jwt_claims": validation_result.claims
            }
            
        except Exception as e:
            return {
                "success": False,
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error": "JWT validation error",
                "details": str(e)
            }
    
    async def _authenticate_with_api_key(self, api_key_str: str) -> Dict[str, Any]:
        """Аутентификация через API ключ"""
        try:
            # Получаем и валидируем API ключ
            api_key = await self._get_and_validate_api_key(api_key_str)
            
            if not api_key:
                return {
                    "success": False,
                    "status_code": status.HTTP_401_UNAUTHORIZED,
                    "error": "Invalid API key",
                    "details": "The provided API key is not valid or has expired"
                }
            
            return {
                "success": True,
                "api_key": api_key,
                "auth_method": "api_key"
            }
            
        except Exception as e:
            return {
                "success": False,
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error": "API key validation error",
                "details": str(e)
            }
    
    def _extract_jwt_token(self, request: Request) -> Optional[str]:
        """Извлекает JWT токен из Authorization header"""
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Убираем "Bearer "
            # Проверяем, что это JWT (не API ключ)
            if not token.startswith("antispam_"):
                return token
        return None
    
    def _extract_api_key(self, request: Request) -> Optional[str]:
        """Извлекает API ключ из запроса"""
        # Проверяем Authorization header (Bearer token для API ключей)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # Проверяем, что это API ключ (начинается с антиспам префикса)
            if token.startswith("antispam_"):
                return token
        
        # Проверяем X-API-Key header
        api_key_header = request.headers.get("X-API-Key")
        if api_key_header:
            return api_key_header
        
        # Проверяем query parameter (не рекомендуется для production)
        api_key_param = request.query_params.get("api_key")
        if api_key_param:
            return api_key_param
        
        return None
    
    async def _get_and_validate_api_key(self, api_key_str: str) -> Optional[ApiKey]:
        """Получает и валидирует API ключ"""
        # Проверяем кэш
        cache_key = f"api_key:{ApiKey.hash_key(api_key_str)}"
        cached = self._api_key_cache.get(cache_key)
        
        if cached and time.time() - cached["timestamp"] < self._cache_ttl:
            if cached["valid"]:
                return cached["api_key"]
            else:
                return None
        
        try:
            # Получаем из БД
            key_hash = ApiKey.hash_key(api_key_str)
            api_key = await self.api_key_repo.get_api_key_by_hash(key_hash)
            
            # Валидируем ключ
            is_valid = api_key and api_key.is_valid and api_key.verify_key(api_key_str)
            
            # Кэшируем результат
            self._api_key_cache[cache_key] = {
                "timestamp": time.time(),
                "valid": is_valid,
                "api_key": api_key if is_valid else None
            }
            
            return api_key if is_valid else None
            
        except Exception as e:
            print(f"Error validating API key: {e}")
            return None
    
    async def _get_api_key_by_id(self, api_key_id: int) -> Optional[ApiKey]:
        """Получает API ключ по ID"""
        try:
            return await self.api_key_repo.get_api_key_by_id(api_key_id)
        except Exception as e:
            print(f"Error getting API key by ID: {e}")
            return None
    
    def _check_ip_allowed(self, api_key: ApiKey, client_ip: str) -> bool:
        """Проверяет, разрешен ли IP адрес для данного API ключа"""
        try:
            # Если список разрешенных IP пустой - разрешаем все
            if not api_key.allowed_ips:
                return True
            
            # Проверяем точное совпадение IP
            if client_ip in api_key.allowed_ips:
                return True
            
            # TODO: Добавить поддержку CIDR нотации для подсетей
            # if self._check_cidr_match(client_ip, api_key.allowed_ips):
            #     return True
            
            return False
            
        except Exception as e:
            print(f"Error checking IP whitelist: {e}")
            # В случае ошибки разрешаем доступ
            return True
    
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
    
    async def _add_rate_limit_headers(self, response: Response, api_key: ApiKey) -> None:
        """Добавляет заголовки с информацией о rate limiting"""
        try:
            rate_limit_info = await self.rate_limiter.get_rate_limit_info(api_key)
            headers = rate_limit_info.to_headers()
            
            for header_name, header_value in headers.items():
                response.headers[header_name] = header_value
                
        except Exception as e:
            print(f"Error adding rate limit headers: {e}")
            # Не блокируем ответ из-за ошибок с заголовками
    
    def _create_error_response(
        self,
        status_code: int,
        error: str,
        details: str = None
    ) -> JSONResponse:
        """Создает стандартизированный ответ об ошибке"""
        content = {
            "error": error,
            "timestamp": time.time(),
            "status_code": status_code
        }
        
        if details:
            content["details"] = details
        
        return JSONResponse(
            status_code=status_code,
            content=content,
            headers={
                "X-Error-Type": "authentication_error",
                "X-Error-Code": str(status_code)
            }
        )
    
    def _create_rate_limit_response(self, rate_limit_result) -> JSONResponse:
        """Создает ответ о превышении rate limit"""
        content = {
            "error": "Rate limit exceeded",
            "limit_type": rate_limit_result.limit_type.value,
            "retry_after_seconds": rate_limit_result.retry_after_seconds,
            "reset_time": rate_limit_result.reset_time.isoformat(),
            "timestamp": time.time()
        }
        
        headers = {
            "Retry-After": str(rate_limit_result.retry_after_seconds),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(rate_limit_result.reset_time.timestamp())),
            "X-Error-Type": "rate_limit_error"
        }
        
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=content,
            headers=headers
        )
    
    def health_check(self) -> Dict[str, Any]:
        """Health check для middleware"""
        try:
            jwt_health = self.jwt_service.health_check()
            rate_limiter_health = self.rate_limiter.health_check()
            
            return {
                "status": "healthy",
                "protected_paths": len(self.protected_paths),
                "public_paths": len(self.public_paths),
                "cache_size": len(self._api_key_cache),
                "jwt_service": jwt_health,
                "rate_limiter": rate_limiter_health
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


# Factory function для создания middleware
def create_api_auth_middleware(
    jwt_service: JWTService,
    rate_limiter: RateLimiter,
    api_key_repo,
    config: Dict[str, Any] = None
):
    """
    Фабрика для создания API Auth Middleware
    
    Args:
        jwt_service: JWT сервис
        rate_limiter: Rate limiter сервис
        api_key_repo: Репозиторий API ключей
        config: Конфигурация
        
    Returns:
        Функция middleware
    """
    if config is None:
        config = {}
    
    protected_paths = config.get("protected_paths", [
        "/api/v1/detect",
        "/api/v1/detect/batch",
        "/api/v1/stats",
        "/api/v1/account"
    ])
    
    def middleware_factory(app):
        return ApiAuthMiddleware(
            app=app,
            jwt_service=jwt_service,
            rate_limiter=rate_limiter,
            api_key_repo=api_key_repo,
            protected_paths=protected_paths,
            require_auth_header=config.get("require_auth_header", True)
        )
    
    return middleware_factory