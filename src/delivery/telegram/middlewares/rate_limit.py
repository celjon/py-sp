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
        calls: int = 100,  # Максимум запросов
        period: int = 60,  # Период в секундах
        cleanup_interval: int = 300,  # Интервал очистки старых записей
    ):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.cleanup_interval = cleanup_interval

        # Хранилище для запросов: {ip: [(timestamp, path), ...]}
        self.requests: Dict[str, list] = {}
        self.last_cleanup = time.time()

        print(f"🚦 Rate limiting: {calls} запросов в {period} секунд")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Основная логика middleware"""

        # Получаем IP адрес клиента
        client_ip = self._get_client_ip(request)

        # Проверяем rate limit
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

        # Записываем запрос
        await self._record_request(client_ip, request.url.path)

        # Периодически очищаем старые записи
        await self._cleanup_old_requests()

        # Продолжаем обработку запроса
        response = await call_next(request)

        # Добавляем заголовки с информацией о rate limit
        remaining = await self._get_remaining_requests(client_ip)
        response.headers["X-RateLimit-Limit"] = str(self.calls)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + self.period)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Получает IP адрес клиента с учетом прокси"""
        # Проверяем заголовки от reverse proxy
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Берем первый IP из списка (реальный клиент)
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # Fallback на прямое соединение
        if request.client:
            return request.client.host

        return "unknown"

    async def _check_rate_limit(self, client_ip: str, path: str) -> bool:
        """Проверяет, не превышен ли rate limit для данного IP"""
        current_time = time.time()
        cutoff_time = current_time - self.period

        # Получаем запросы для данного IP
        client_requests = self.requests.get(client_ip, [])

        # Фильтруем только недавние запросы
        recent_requests = [
            (timestamp, req_path)
            for timestamp, req_path in client_requests
            if timestamp > cutoff_time
        ]

        # Обновляем записи для IP
        self.requests[client_ip] = recent_requests

        # Проверяем лимит
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

        # Очищаем только раз в cleanup_interval секунд
        if current_time - self.last_cleanup < self.cleanup_interval:
            return

        self.last_cleanup = current_time
        cutoff_time = current_time - self.period * 2  # Удаляем записи старше 2x периода

        # Очищаем старые записи для всех IP
        for ip in list(self.requests.keys()):
            # Фильтруем недавние запросы
            recent_requests = [
                (timestamp, path)
                for timestamp, path in self.requests[ip]
                if timestamp > cutoff_time
            ]

            if recent_requests:
                self.requests[ip] = recent_requests
            else:
                # Удаляем IP если нет недавних запросов
                del self.requests[ip]

        print(f"🧹 Rate limit cleanup: отслеживается {len(self.requests)} IP адресов")


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
            print(f"🛡️ IP whitelist активен для путей: {self.admin_paths}")
            print(f"   Разрешенные IP: {', '.join(self.whitelist)}")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Проверяет IP адрес для админских путей"""

        # Если whitelist пустой, пропускаем проверку
        if not self.whitelist:
            return await call_next(request)

        # Проверяем только админские пути
        path = request.url.path
        is_admin_path = any(path.startswith(admin_path) for admin_path in self.admin_paths)

        if not is_admin_path:
            return await call_next(request)

        # Получаем IP клиента
        client_ip = self._get_client_ip(request)

        # Проверяем whitelist
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

        # Информация о запросе
        client_ip = self._get_client_ip(request)
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        user_agent = request.headers.get("User-Agent", "Unknown")

        # Логируем входящий запрос
        print(f"📝 {method} {path}{('?' + query) if query else ''} from {client_ip}")

        # Обрабатываем запрос
        try:
            response = await call_next(request)

            # Вычисляем время обработки
            processing_time = (time.time() - start_time) * 1000

            # Логируем ответ
            status_emoji = (
                "✅" if response.status_code < 400 else "⚠️" if response.status_code < 500 else "❌"
            )
            print(
                f"{status_emoji} {response.status_code} | {processing_time:.1f}ms | {method} {path}"
            )

            # Добавляем заголовок с временем обработки
            response.headers["X-Processing-Time"] = f"{processing_time:.1f}ms"

            return response

        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            print(f"❌ 500 | {processing_time:.1f}ms | {method} {path} | Error: {str(e)}")
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
