import time
import asyncio
from typing import Dict, Callable, Any
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware для HTTP API
    Ограничивает количество запросов от одного IP адреса
    """

    def __init__(
        self,
        app,
        calls: int = 100,
        period: int = 60,
        cleanup_interval: int = 300,
    ):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.cleanup_interval = cleanup_interval

        self.requests: Dict[str, list] = {}
        self.last_cleanup = time.time()


    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Основная логика middleware"""

        client_ip = self._get_client_ip(request)

        if not await self._check_rate_limit(client_ip, request.url.path):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Максимум {self.calls} запросов в {self.period} секунд",
                    "retry_after": self.period,
                    "timestamp": time.time(),
                },
                headers={"Retry-After": str(self.period)},
            )

        await self._record_request(client_ip, request.url.path)

        await self._cleanup_old_requests()

        response = await call_next(request)

        remaining = await self._get_remaining_requests(client_ip)
        response.headers["X-RateLimit-Limit"] = str(self.calls)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + self.period)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Получает IP адрес клиента с учетом прокси"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        if request.client:
            return request.client.host

        return "unknown"

    async def _check_rate_limit(self, client_ip: str, path: str) -> bool:
        """Проверяет, не превышен ли rate limit для данного IP"""
        current_time = time.time()
        cutoff_time = current_time - self.period

        client_requests = self.requests.get(client_ip, [])

        recent_requests = [
            (timestamp, req_path)
            for timestamp, req_path in client_requests
            if timestamp > cutoff_time
        ]

        self.requests[client_ip] = recent_requests

        return len(recent_requests) < self.calls

    async def _record_request(self, client_ip: str, path: str):
        """Записывает новый запрос"""
        current_time = time.time()

        if client_ip not in self.requests:
            self.requests[client_ip] = []

        self.requests[client_ip].append((current_time, path))

    async def _get_remaining_requests(self, client_ip: str) -> int:
        """Возвращает количество оставшихся запросов для IP"""
        current_time = time.time()
        cutoff_time = current_time - self.period

        client_requests = self.requests.get(client_ip, [])
        recent_requests = [timestamp for timestamp, _ in client_requests if timestamp > cutoff_time]

        return max(0, self.calls - len(recent_requests))

    async def _cleanup_old_requests(self):
        """Периодически очищает старые записи для экономии памяти"""
        current_time = time.time()

        if current_time - self.last_cleanup < self.cleanup_interval:
            return

        self.last_cleanup = current_time
        cutoff_time = current_time - self.period * 2

        for ip in list(self.requests.keys()):
            recent_requests = [
                (timestamp, path)
                for timestamp, path in self.requests[ip]
                if timestamp > cutoff_time
            ]

            if recent_requests:
                self.requests[ip] = recent_requests
            else:
                del self.requests[ip]



class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """
    Middleware для whitelist IP адресов
    Используется в production для ограничения доступа к админ API
    """

    def __init__(self, app, whitelist: list = None, admin_paths: list = None):
        super().__init__(app)
        self.whitelist = set(whitelist or [])
        self.admin_paths = admin_paths or ["/api/v1/admin"]

        if self.whitelist:
            pass

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Проверяет IP адрес для админских путей"""

        if not self.whitelist:
            return await call_next(request)

        path = request.url.path
        is_admin_path = any(path.startswith(admin_path) for admin_path in self.admin_paths)

        if not is_admin_path:
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        if client_ip not in self.whitelist:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Access denied",
                    "message": f"IP адрес {client_ip} не разрешен для доступа к админ API",
                    "timestamp": time.time(),
                },
            )

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """Получает IP адрес клиента (копия из RateLimitMiddleware)"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        if request.client:
            return request.client.host

        return "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для логирования HTTP запросов
    Полезно для отладки и мониторинга
    """

    def __init__(self, app, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Логирует входящие запросы и ответы"""
        start_time = time.time()

        client_ip = self._get_client_ip(request)
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        user_agent = request.headers.get("User-Agent", "Unknown")

        pass

        try:
            response = await call_next(request)

            processing_time = (time.time() - start_time) * 1000

            status_emoji = (
                "✅" if response.status_code < 400 else "⚠️" if response.status_code < 500 else "❌"
            )

            response.headers["X-Processing-Time"] = f"{processing_time:.1f}ms"

            return response

        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            pass
            raise

    def _get_client_ip(self, request: Request) -> str:
        """Получает IP адрес клиента"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        if request.client:
            return request.client.host

        return "unknown"
