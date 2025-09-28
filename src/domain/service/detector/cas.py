"""
Production-Ready CAS (Combot Anti-Spam) Detector
Высокопроизводительная проверка пользователей в базе забаненных
"""

import time
import logging
from typing import Dict, Any, Optional

from ...entity.message import Message
from ...entity.detection_result import DetectorResult

logger = logging.getLogger(__name__)


class CASDetector:
    """
    Production-ready детектор спама на основе CAS API

    Features:
    - Кэширование результатов для производительности
    - Comprehensive error handling
    - Performance monitoring
    - Graceful degradation при недоступности CAS
    """

    def __init__(self, cas_gateway, config: Dict[str, Any] = None):
        """
        Args:
            cas_gateway: Шлюз для работы с CAS API
            config: Дополнительная конфигурация
        """
        self.cas_gateway = cas_gateway
        self.config = config or {}

        self.cache_ttl = self.config.get("cache_ttl", 3600)
        self.timeout = self.config.get("timeout", 1.0)

        self.banned_confidence = self.config.get("banned_confidence", 0.95)
        self.not_banned_confidence = self.config.get("not_banned_confidence", 0.05)

        self._total_checks = 0
        self._cache_hits = 0
        self._api_calls = 0
        self._errors = 0
        self._banned_users = 0

        logger.info("[SHIELD] CAS Detector инициализирован")
        logger.info(f"   Cache TTL: {self.cache_ttl}s, Timeout: {self.timeout}s")

    async def detect(self, message: Message, user_context: Dict[str, Any] = None) -> DetectorResult:
        """
        Проверяет пользователя в базе CAS

        Args:
            message: Сообщение для проверки
            user_context: Контекст пользователя

        Returns:
            DetectorResult с результатом проверки
        """
        start_time = time.time()
        self._total_checks += 1

        user_id = message.user_id
        username = getattr(message, "username", None)

        logger.debug(f"[SEARCH] CAS проверка пользователя: {user_id} (@{username})")

        try:
            cas_result = await self.cas_gateway.check_cas(user_id)
            self._api_calls += 1

            processing_time_ms = (time.time() - start_time) * 1000

            if cas_result:
                self._banned_users += 1

                logger.warning(f"[ALERT] CAS BAN: пользователь {user_id} забанен")

                return DetectorResult(
                    detector_name="CAS",
                    is_spam=True,
                    confidence=self.banned_confidence,
                    details="User banned in CAS database",
                    processing_time_ms=processing_time_ms,
                )
            else:
                logger.debug(f"[OK] CAS: пользователь {user_id} чист ({processing_time_ms:.1f}ms)")

                return DetectorResult(
                    detector_name="CAS",
                    is_spam=False,
                    confidence=self.not_banned_confidence,
                    details="User not found in CAS ban database",
                    processing_time_ms=processing_time_ms,
                )

        except Exception as e:
            self._errors += 1
            processing_time_ms = (time.time() - start_time) * 1000

            logger.error(f"[WARN] CAS проверка failed для пользователя {user_id}: {e}")

            return DetectorResult(
                detector_name="CAS",
                is_spam=False,
                confidence=0.0,
                details=f"CAS check failed: {str(e)}",
                error=str(e),
                processing_time_ms=processing_time_ms,
            )

    async def check_multiple_users(self, user_ids: list) -> Dict[int, DetectorResult]:
        """
        Массовая проверка пользователей для оптимизации

        Args:
            user_ids: Список ID пользователей

        Returns:
            Словарь: user_id -> DetectorResult
        """
        results = {}

        try:
            if hasattr(self.cas_gateway, "check_cas_batch"):
                logger.info(f"[SEARCH] CAS batch проверка {len(user_ids)} пользователей")

                batch_results = await self.cas_gateway.check_cas_batch(user_ids)

                for user_id, cas_result in batch_results.items():
                    if cas_result:
                        results[user_id] = DetectorResult(
                            detector_name="CAS",
                            is_spam=True,
                            confidence=self.banned_confidence,
                            details="User banned in CAS",
                        )
                    else:
                        results[user_id] = DetectorResult(
                            detector_name="CAS",
                            is_spam=False,
                            confidence=self.not_banned_confidence,
                            details="User not banned",
                        )
            else:
                logger.info(f"[SEARCH] CAS последовательная проверка {len(user_ids)} пользователей")

                for user_id in user_ids:
                    try:
                        cas_result = await self.cas_gateway.check_cas(user_id)

                        if cas_result:
                            results[user_id] = DetectorResult(
                                detector_name="CAS",
                                is_spam=True,
                                confidence=self.banned_confidence,
                                details="User banned in CAS",
                            )
                        else:
                            results[user_id] = DetectorResult(
                                detector_name="CAS",
                                is_spam=False,
                                confidence=self.not_banned_confidence,
                                details="User not banned",
                            )
                    except Exception as e:
                        logger.error(f"[WARN] CAS ошибка для пользователя {user_id}: {e}")
                        results[user_id] = DetectorResult(
                            detector_name="CAS",
                            is_spam=False,
                            confidence=0.0,
                            details=f"CAS check failed: {str(e)}",
                            error=str(e),
                        )

        except Exception as e:
            logger.error(f"[ERROR] CAS batch проверка failed: {e}")

            for user_id in user_ids:
                results[user_id] = DetectorResult(
                    detector_name="CAS",
                    is_spam=False,
                    confidence=0.0,
                    details=f"Batch check failed: {str(e)}",
                    error=str(e),
                )

        return results

    def get_performance_stats(self) -> Dict[str, Any]:
        """Возвращает статистику производительности"""
        cache_hit_rate = self._cache_hits / self._total_checks if self._total_checks > 0 else 0

        error_rate = self._errors / self._total_checks if self._total_checks > 0 else 0

        ban_rate = self._banned_users / self._total_checks if self._total_checks > 0 else 0

        return {
            "total_checks": self._total_checks,
            "cache_hits": self._cache_hits,
            "api_calls": self._api_calls,
            "errors": self._errors,
            "banned_users": self._banned_users,
            "cache_hit_rate": cache_hit_rate,
            "error_rate": error_rate,
            "ban_rate": ban_rate,
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка состояния CAS detector

        Returns:
            Статус здоровья системы
        """
        try:
            start_time = time.time()

            test_result = await self.cas_gateway.check_cas(1)

            response_time_ms = (time.time() - start_time) * 1000

            return {
                "status": "healthy",
                "api_available": True,
                "response_time_ms": response_time_ms,
                "performance": self.get_performance_stats(),
                "config": {
                    "timeout": self.timeout,
                    "cache_ttl": self.cache_ttl,
                    "banned_confidence": self.banned_confidence,
                },
            }

        except Exception as e:
            logger.error(f"[ERROR] CAS health check failed: {e}")

            return {
                "status": "error",
                "api_available": False,
                "error": str(e),
                "performance": self.get_performance_stats(),
            }

    async def warmup_cache(self, common_user_ids: list = None):
        """
        Прогревает кэш для часто проверяемых пользователей

        Args:
            common_user_ids: Список часто проверяемых пользователей
        """
        if not common_user_ids:
            return

        logger.info(f"[WARM] Прогрев CAS кэша для {len(common_user_ids)} пользователей...")

        try:
            results = await self.check_multiple_users(common_user_ids)

            cache_entries = len([r for r in results.values() if not r.error])
            logger.info(f"[OK] CAS кэш прогрет: {cache_entries} записей")

        except Exception as e:
            logger.error(f"[WARN] Ошибка прогрева CAS кэша: {e}")

    def reset_stats(self):
        """Сбрасывает статистику (для тестирования)"""
        self._total_checks = 0
        self._cache_hits = 0
        self._api_calls = 0
        self._errors = 0
        self._banned_users = 0
        logger.info("[STATS] CAS статистика сброшена")
