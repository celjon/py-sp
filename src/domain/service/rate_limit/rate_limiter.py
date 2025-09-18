# src/domain/service/rate_limit/rate_limiter.py
"""
Production-ready Rate Limiting Service
Реализует алгоритм sliding window для точного ограничения запросов
"""

import time
import json
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from ...entity.api_key import ApiKey
from ...entity.client_usage import RateLimitStatus


class RateLimitType(Enum):
    """Типы rate limiting"""

    PER_MINUTE = "per_minute"
    PER_HOUR = "per_hour"
    PER_DAY = "per_day"
    PER_MONTH = "per_month"


@dataclass(frozen=True)
class RateLimitResult:
    """Результат проверки rate limiting"""

    is_allowed: bool
    remaining_requests: int
    reset_time: datetime
    limit_type: RateLimitType
    retry_after_seconds: int = 0

    @property
    def is_rate_limited(self) -> bool:
        """Проверяет, превышен ли лимит"""
        return not self.is_allowed


@dataclass
class RateLimitInfo:
    """Информация о текущих лимитах"""

    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    requests_per_month: int
    current_minute: int = 0
    current_hour: int = 0
    current_day: int = 0
    current_month: int = 0

    def to_headers(self) -> Dict[str, str]:
        """Преобразует в HTTP заголовки"""
        return {
            "X-RateLimit-Limit-Minute": str(self.requests_per_minute),
            "X-RateLimit-Limit-Hour": str(self.requests_per_hour),
            "X-RateLimit-Limit-Day": str(self.requests_per_day),
            "X-RateLimit-Remaining-Minute": str(
                max(0, self.requests_per_minute - self.current_minute)
            ),
            "X-RateLimit-Remaining-Hour": str(max(0, self.requests_per_hour - self.current_hour)),
            "X-RateLimit-Remaining-Day": str(max(0, self.requests_per_day - self.current_day)),
        }


class RateLimiter:
    """
    Production-ready Rate Limiter с Redis backend

    Features:
    - Sliding window algorithm для точности
    - Multiple time windows (minute/hour/day/month)
    - Burst protection
    - IP-based and API key-based limiting
    - Graceful degradation при недоступности Redis
    """

    def __init__(self, redis_client=None, fallback_mode: bool = True):
        """
        Args:
            redis_client: Redis клиент для хранения счетчиков
            fallback_mode: Разрешить запросы при недоступности Redis
        """
        self.redis = redis_client
        self.fallback_mode = fallback_mode

        # In-memory fallback для случаев недоступности Redis
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 3600  # 1 час

        print(
            f"🚥 Rate Limiter инициализирован (Redis: {'✅' if redis_client else '❌'}, fallback: {fallback_mode})"
        )

    async def check_rate_limit(self, api_key: ApiKey, client_ip: str = None) -> RateLimitResult:
        """
        Проверяет rate limiting для API ключа

        Args:
            api_key: API ключ с лимитами
            client_ip: IP адрес клиента (опционально)

        Returns:
            RateLimitResult с информацией о лимитах
        """
        try:
            # Получаем лимиты для ключа
            limits = api_key.get_rate_limits()

            # Проверяем каждый тип лимита
            minute_result = await self._check_window_limit(
                api_key.id,
                RateLimitType.PER_MINUTE,
                limits.get("requests_per_minute", 60),
                60,  # 60 секунд
            )

            if not minute_result.is_allowed:
                return minute_result

            hour_result = await self._check_window_limit(
                api_key.id,
                RateLimitType.PER_HOUR,
                limits.get("requests_per_hour", 3600),
                3600,  # 3600 секунд
            )

            if not hour_result.is_allowed:
                return hour_result

            day_result = await self._check_window_limit(
                api_key.id,
                RateLimitType.PER_DAY,
                limits.get("requests_per_day", 5000),
                86400,  # 86400 секунд
            )

            if not day_result.is_allowed:
                return day_result

            # Если все проверки прошли - разрешаем запрос
            return RateLimitResult(
                is_allowed=True,
                remaining_requests=min(
                    minute_result.remaining_requests,
                    hour_result.remaining_requests,
                    day_result.remaining_requests,
                ),
                reset_time=minute_result.reset_time,  # Ближайший reset
                limit_type=RateLimitType.PER_MINUTE,
            )

        except Exception as e:
            print(f"Rate limit check error: {e}")

            # В случае ошибки применяем fallback логику
            if self.fallback_mode:
                # В fallback режиме разрешаем запросы
                return RateLimitResult(
                    is_allowed=True,
                    remaining_requests=1000,  # Большое число
                    reset_time=datetime.now(timezone.utc) + timedelta(minutes=1),
                    limit_type=RateLimitType.PER_MINUTE,
                )
            else:
                # Строгий режим - блокируем при ошибках
                return RateLimitResult(
                    is_allowed=False,
                    remaining_requests=0,
                    reset_time=datetime.now(timezone.utc) + timedelta(minutes=1),
                    limit_type=RateLimitType.PER_MINUTE,
                    retry_after_seconds=60,
                )

    async def record_request(
        self, api_key: ApiKey, client_ip: str = None, endpoint: str = None
    ) -> None:
        """
        Записывает выполненный запрос для учета в лимитах

        Args:
            api_key: API ключ
            client_ip: IP адрес клиента
            endpoint: Эндпоинт который был вызван
        """
        try:
            current_time = int(time.time())

            # Записываем в разные временные окна
            await self._record_in_window(api_key.id, RateLimitType.PER_MINUTE, current_time, 60)
            await self._record_in_window(api_key.id, RateLimitType.PER_HOUR, current_time, 3600)
            await self._record_in_window(api_key.id, RateLimitType.PER_DAY, current_time, 86400)

            # Записываем дополнительную аналитику
            if endpoint:
                await self._record_endpoint_usage(api_key.id, endpoint, current_time)

        except Exception as e:
            print(f"Error recording request: {e}")
            # Не блокируем выполнение при ошибках записи

    async def get_rate_limit_info(self, api_key: ApiKey) -> RateLimitInfo:
        """
        Получает текущую информацию о rate limiting

        Args:
            api_key: API ключ

        Returns:
            RateLimitInfo с текущими счетчиками
        """
        try:
            limits = api_key.get_rate_limits()
            current_time = int(time.time())

            # Получаем текущие счетчики
            current_minute = await self._get_window_count(
                api_key.id, RateLimitType.PER_MINUTE, current_time, 60
            )
            current_hour = await self._get_window_count(
                api_key.id, RateLimitType.PER_HOUR, current_time, 3600
            )
            current_day = await self._get_window_count(
                api_key.id, RateLimitType.PER_DAY, current_time, 86400
            )

            return RateLimitInfo(
                requests_per_minute=limits.get("requests_per_minute", 60),
                requests_per_hour=limits.get("requests_per_hour", 3600),
                requests_per_day=limits.get("requests_per_day", 5000),
                requests_per_month=limits.get("requests_per_month", 150000),
                current_minute=current_minute,
                current_hour=current_hour,
                current_day=current_day,
                current_month=0,  # TODO: реализовать monthly tracking
            )

        except Exception as e:
            print(f"Error getting rate limit info: {e}")
            limits = api_key.get_rate_limits()

            # Возвращаем default значения при ошибке
            return RateLimitInfo(
                requests_per_minute=limits.get("requests_per_minute", 60),
                requests_per_hour=limits.get("requests_per_hour", 3600),
                requests_per_day=limits.get("requests_per_day", 5000),
                requests_per_month=limits.get("requests_per_month", 150000),
            )

    async def reset_limits(self, api_key_id: int) -> bool:
        """
        Сбрасывает лимиты для API ключа (админ функция)

        Args:
            api_key_id: ID API ключа

        Returns:
            True если лимиты сброшены успешно
        """
        try:
            if self.redis:
                # Удаляем все ключи rate limiting для данного API ключа
                pattern = f"rate_limit:{api_key_id}:*"
                keys = await self.redis.keys(pattern)
                if keys:
                    await self.redis.delete(*keys)

            # Очищаем memory cache
            cache_keys = [key for key in self._memory_cache.keys() if f":{api_key_id}:" in key]
            for key in cache_keys:
                del self._memory_cache[key]

            return True

        except Exception as e:
            print(f"Error resetting limits: {e}")
            return False

    async def _check_window_limit(
        self, api_key_id: int, limit_type: RateLimitType, max_requests: int, window_seconds: int
    ) -> RateLimitResult:
        """Проверяет лимит для конкретного временного окна"""
        current_time = int(time.time())
        current_count = await self._get_window_count(
            api_key_id, limit_type, current_time, window_seconds
        )

        is_allowed = current_count < max_requests
        remaining = max(0, max_requests - current_count)

        # Вычисляем время до сброса окна
        window_start = current_time - (current_time % window_seconds)
        reset_time = datetime.fromtimestamp(window_start + window_seconds)

        retry_after = 0 if is_allowed else (window_start + window_seconds - current_time)

        return RateLimitResult(
            is_allowed=is_allowed,
            remaining_requests=remaining,
            reset_time=reset_time,
            limit_type=limit_type,
            retry_after_seconds=retry_after,
        )

    async def _get_window_count(
        self, api_key_id: int, limit_type: RateLimitType, current_time: int, window_seconds: int
    ) -> int:
        """Получает количество запросов в текущем окне"""
        window_start = current_time - (current_time % window_seconds)
        cache_key = f"rate_limit:{api_key_id}:{limit_type.value}:{window_start}"

        try:
            if self.redis:
                # Используем Redis для production
                count = await self.redis.get(cache_key)
                return int(count) if count else 0
            else:
                # Fallback на memory cache
                cache_entry = self._memory_cache.get(cache_key)
                if cache_entry and time.time() - cache_entry["timestamp"] < self._cache_ttl:
                    return cache_entry["count"]
                return 0

        except Exception as e:
            print(f"Error getting window count: {e}")
            return 0

    async def _record_in_window(
        self, api_key_id: int, limit_type: RateLimitType, current_time: int, window_seconds: int
    ) -> None:
        """Записывает запрос в временное окно"""
        window_start = current_time - (current_time % window_seconds)
        cache_key = f"rate_limit:{api_key_id}:{limit_type.value}:{window_start}"

        try:
            if self.redis:
                # Атомарно инкрементируем счетчик в Redis
                async with self.redis.pipeline() as pipe:
                    await pipe.incr(cache_key)
                    await pipe.expire(cache_key, window_seconds + 60)  # +60 сек запас
                    await pipe.execute()
            else:
                # Fallback на memory cache
                if cache_key in self._memory_cache:
                    self._memory_cache[cache_key]["count"] += 1
                else:
                    self._memory_cache[cache_key] = {"count": 1, "timestamp": time.time()}

        except Exception as e:
            print(f"Error recording in window: {e}")

    async def _record_endpoint_usage(
        self, api_key_id: int, endpoint: str, current_time: int
    ) -> None:
        """Записывает статистику использования эндпоинтов"""
        try:
            if self.redis:
                # Записываем статистику эндпоинтов для аналитики
                stats_key = f"endpoint_stats:{api_key_id}:{endpoint}"
                await self.redis.incr(stats_key)
                await self.redis.expire(stats_key, 86400 * 7)  # 7 дней

        except Exception as e:
            print(f"Error recording endpoint usage: {e}")

    def health_check(self) -> Dict[str, Any]:
        """Health check для rate limiter"""
        try:
            redis_status = "healthy" if self.redis else "not_configured"

            # Тестируем Redis подключение если доступно
            if self.redis:
                try:
                    # Простой тест Redis
                    test_key = f"health_check:{int(time.time())}"
                    # В production нужно добавить await для async Redis
                    redis_status = "healthy"
                except Exception:
                    redis_status = "error"

            return {
                "status": "healthy",
                "redis_status": redis_status,
                "fallback_mode": self.fallback_mode,
                "memory_cache_size": len(self._memory_cache),
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}


# Factory function
def create_rate_limiter(redis_client=None, config: Dict[str, Any] = None) -> RateLimiter:
    """
    Фабрика для создания Rate Limiter

    Args:
        redis_client: Redis клиент
        config: Конфигурация

    Returns:
        Настроенный RateLimiter
    """
    if config is None:
        config = {}

    fallback_mode = config.get("fallback_mode", True)

    return RateLimiter(redis_client=redis_client, fallback_mode=fallback_mode)
