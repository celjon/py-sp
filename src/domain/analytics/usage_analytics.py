# src/domain/service/analytics/usage_analytics.py
"""
Production-ready Usage Analytics Service
Детальная аналитика использования API для billing и мониторинга
"""

import time
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from ..entity.api_key import ApiKey
from ..entity.client_usage import ApiUsageRecord, ApiUsageStats, RequestStatus


class AnalyticsEvent(Enum):
    """Типы аналитических событий"""

    API_REQUEST = "api_request"
    SPAM_DETECTION = "spam_detection"
    RATE_LIMIT_HIT = "rate_limit_hit"
    ERROR_OCCURRED = "error_occurred"
    AUTHENTICATION_FAILED = "auth_failed"


@dataclass(frozen=True)
class UsageMetrics:
    """Метрики использования для периода"""

    api_key_id: int
    period: str  # "hour", "day", "week", "month"
    timestamp: datetime

    # Базовые метрики
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # Spam detection метрики
    spam_detected: int = 0
    clean_detected: int = 0
    avg_confidence: float = 0.0

    # Производительность
    avg_response_time_ms: float = 0.0
    p95_response_time_ms: float = 0.0
    max_response_time_ms: float = 0.0

    # Объем данных
    total_bytes_processed: int = 0

    # Rate limiting
    rate_limit_hits: int = 0

    # Популярные эндпоинты
    top_endpoints: Dict[str, int] = None

    def __post_init__(self):
        if self.top_endpoints is None:
            object.__setattr__(self, "top_endpoints", {})

    @property
    def success_rate(self) -> float:
        """Процент успешных запросов"""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def error_rate(self) -> float:
        """Процент ошибок"""
        if self.total_requests == 0:
            return 0.0
        return (self.failed_requests / self.total_requests) * 100

    @property
    def spam_detection_rate(self) -> float:
        """Процент обнаруженного спама"""
        total_detections = self.spam_detected + self.clean_detected
        if total_detections == 0:
            return 0.0
        return (self.spam_detected / total_detections) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь для JSON"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["success_rate"] = round(self.success_rate, 2)
        data["error_rate"] = round(self.error_rate, 2)
        data["spam_detection_rate"] = round(self.spam_detection_rate, 2)
        return data


@dataclass
class AlertRule:
    """Правило для алертов"""

    name: str
    condition: str  # "error_rate > 10", "response_time > 2000", etc.
    threshold: float
    metric: str
    period_minutes: int = 5
    enabled: bool = True

    def check_violation(self, metrics: UsageMetrics) -> bool:
        """Проверяет нарушение правила"""
        try:
            metric_value = getattr(metrics, self.metric, 0)

            if self.condition.startswith(">"):
                return metric_value > self.threshold
            elif self.condition.startswith("<"):
                return metric_value < self.threshold
            elif self.condition.startswith(">="):
                return metric_value >= self.threshold
            elif self.condition.startswith("<="):
                return metric_value <= self.threshold

            return False
        except Exception:
            return False


class UsageAnalytics:
    """
    Production-ready Usage Analytics Service

    Features:
    - Real-time метрики использования API
    - Детальная аналитика по клиентам
    - Автоматические алерты
    - Billing метрики
    - Performance мониторинг
    - Fraud detection базовый
    """

    def __init__(
        self, usage_repo, redis_client=None, enable_real_time: bool = True  # UsageRepository
    ):
        self.usage_repo = usage_repo
        self.redis = redis_client
        self.enable_real_time = enable_real_time

        # Real-time метрики кэш (в production используйте Redis)
        self._metrics_cache: Dict[str, UsageMetrics] = {}
        self._cache_ttl = 300  # 5 минут

        # Алерты
        self._alert_rules: List[AlertRule] = []
        self._setup_default_alert_rules()

        # Счетчики для мониторинга
        self._processed_events = 0
        self._last_cleanup = time.time()

        print(f"📊 Usage Analytics инициализирован (real-time: {enable_real_time})")

    async def track_api_request(
        self,
        api_key: ApiKey,
        endpoint: str,
        method: str,
        status: RequestStatus,
        processing_time_ms: float,
        request_size_bytes: int = 0,
        response_size_bytes: int = 0,
        client_ip: str = None,
        user_agent: str = None,
        is_spam_detected: bool = None,
        detection_confidence: float = None,
        detection_reason: str = None,
    ) -> None:
        """
        Отслеживает API запрос для аналитики

        Args:
            api_key: API ключ клиента
            endpoint: Вызванный эндпоинт
            method: HTTP метод
            status: Статус запроса
            processing_time_ms: Время обработки в миллисекундах
            request_size_bytes: Размер запроса
            response_size_bytes: Размер ответа
            client_ip: IP адрес клиента
            user_agent: User-Agent
            is_spam_detected: Был ли обнаружен спам
            detection_confidence: Уверенность детекции
            detection_reason: Причина детекции
        """
        try:
            # Создаем запись использования
            usage_record = ApiUsageRecord(
                api_key_id=api_key.id,
                endpoint=endpoint,
                method=method,
                status=status,
                client_ip=client_ip or "unknown",
                user_agent=user_agent or "unknown",
                request_size_bytes=request_size_bytes,
                response_size_bytes=response_size_bytes,
                processing_time_ms=processing_time_ms,
                is_spam_detected=is_spam_detected,
                detection_confidence=detection_confidence,
                detection_reason=detection_reason,
                timestamp=datetime.now(timezone.utc),
            )

            # Сохраняем в БД
            await self.usage_repo.record_api_usage(usage_record)

            # Обновляем real-time метрики
            if self.enable_real_time:
                await self._update_real_time_metrics(usage_record)

            # Проверяем алерты
            await self._check_alert_rules(api_key.id, usage_record)

            self._processed_events += 1

        except Exception as e:
            print(f"Error tracking API request: {e}")
            # Не блокируем основной поток при ошибках аналитики

    async def get_usage_metrics(
        self, api_key_id: int, period: str = "hour", hours_back: int = 24
    ) -> List[UsageMetrics]:
        """
        Получает метрики использования за период

        Args:
            api_key_id: ID API ключа
            period: Период группировки ("hour", "day", "week")
            hours_back: Количество часов назад

        Returns:
            Список метрик по периодам
        """
        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours_back)

            # Получаем агрегированные данные из БД
            raw_metrics = await self.usage_repo.get_aggregated_usage(
                api_key_id=api_key_id, start_time=start_time, end_time=end_time, period=period
            )

            # Преобразуем в UsageMetrics
            metrics = []
            for raw_metric in raw_metrics:
                metric = UsageMetrics(
                    api_key_id=api_key_id,
                    period=period,
                    timestamp=raw_metric["period_start"],
                    total_requests=raw_metric["total_requests"],
                    successful_requests=raw_metric["successful_requests"],
                    failed_requests=raw_metric["failed_requests"],
                    spam_detected=raw_metric["spam_detected"],
                    clean_detected=raw_metric["clean_detected"],
                    avg_confidence=raw_metric["avg_confidence"],
                    avg_response_time_ms=raw_metric["avg_response_time_ms"],
                    p95_response_time_ms=raw_metric.get("p95_response_time_ms", 0),
                    max_response_time_ms=raw_metric["max_response_time_ms"],
                    total_bytes_processed=raw_metric["total_bytes_processed"],
                    rate_limit_hits=raw_metric.get("rate_limit_hits", 0),
                    top_endpoints=raw_metric.get("top_endpoints", {}),
                )
                metrics.append(metric)

            return metrics

        except Exception as e:
            print(f"Error getting usage metrics: {e}")
            return []

    async def get_real_time_metrics(self, api_key_id: int, last_minutes: int = 5) -> UsageMetrics:
        """
        Получает real-time метрики за последние N минут

        Args:
            api_key_id: ID API ключа
            last_minutes: Количество минут

        Returns:
            Текущие метрики
        """
        try:
            cache_key = f"realtime_metrics:{api_key_id}:{last_minutes}"

            # Проверяем кэш
            cached_metric = self._metrics_cache.get(cache_key)
            if cached_metric and self._is_cache_valid(cached_metric.timestamp):
                return cached_metric

            # Получаем из БД
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(minutes=last_minutes)

            raw_data = await self.usage_repo.get_usage_stats(
                api_key_id=api_key_id,
                period=None,  # Real-time
                start_time=start_time,
                end_time=end_time,
            )

            # Преобразуем в метрики
            metric = UsageMetrics(
                api_key_id=api_key_id,
                period="realtime",
                timestamp=end_time,
                total_requests=raw_data.total_requests,
                successful_requests=raw_data.successful_requests,
                failed_requests=raw_data.error_requests,
                spam_detected=raw_data.spam_detected,
                clean_detected=raw_data.clean_detected,
                avg_confidence=raw_data.avg_confidence,
                avg_response_time_ms=raw_data.avg_processing_time_ms,
                max_response_time_ms=raw_data.max_processing_time_ms,
                total_bytes_processed=int(raw_data.total_data_processed_bytes),
            )

            # Кэшируем
            self._metrics_cache[cache_key] = metric

            return metric

        except Exception as e:
            print(f"Error getting real-time metrics: {e}")
            # Возвращаем пустую метрику
            return UsageMetrics(
                api_key_id=api_key_id, period="realtime", timestamp=datetime.now(timezone.utc)
            )

    async def get_billing_metrics(
        self, api_key_id: int, start_date: datetime, end_date: datetime
    ) -> Dict[str, Any]:
        """
        Получает метрики для биллинга

        Args:
            api_key_id: ID API ключа
            start_date: Начало периода
            end_date: Конец периода

        Returns:
            Billing метрики
        """
        try:
            # Получаем детальную статистику
            usage_stats = await self.usage_repo.get_usage_stats(
                api_key_id=api_key_id, period=None, start_time=start_date, end_time=end_date
            )

            # Получаем breakdown по дням
            daily_metrics = await self.get_usage_metrics(
                api_key_id=api_key_id,
                period="day",
                hours_back=int((end_date - start_date).total_seconds() / 3600),
            )

            # Получаем топ эндпоинты
            top_endpoints = await self.usage_repo.get_top_endpoints(
                api_key_id=api_key_id, hours=int((end_date - start_date).total_seconds() / 3600)
            )

            # Вычисляем billing метрики
            billing_data = {
                "api_key_id": api_key_id,
                "billing_period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "days": (end_date - start_date).days,
                },
                "usage_summary": {
                    "total_requests": usage_stats.total_requests,
                    "successful_requests": usage_stats.successful_requests,
                    "error_requests": usage_stats.error_requests,
                    "success_rate": round(usage_stats.success_rate, 2),
                    "total_data_processed_mb": round(
                        usage_stats.total_data_processed_bytes / 1024 / 1024, 2
                    ),
                },
                "spam_detection": {
                    "spam_detected": usage_stats.spam_detected,
                    "clean_detected": usage_stats.clean_detected,
                    "detection_rate": round(usage_stats.spam_detection_rate, 2),
                    "avg_confidence": round(usage_stats.avg_confidence, 3),
                },
                "performance": {
                    "avg_response_time_ms": round(usage_stats.avg_processing_time_ms, 2),
                    "max_response_time_ms": round(usage_stats.max_processing_time_ms, 2),
                },
                "daily_breakdown": [metric.to_dict() for metric in daily_metrics],
                "top_endpoints": top_endpoints[:10],  # Топ 10
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

            return billing_data

        except Exception as e:
            print(f"Error getting billing metrics: {e}")
            return {"error": "Failed to generate billing metrics", "api_key_id": api_key_id}

    async def detect_anomalies(self, api_key_id: int, hours_back: int = 24) -> List[Dict[str, Any]]:
        """
        Детектирует аномалии в использовании API

        Args:
            api_key_id: ID API ключа
            hours_back: Период для анализа

        Returns:
            Список обнаруженных аномалий
        """
        try:
            anomalies = []

            # Получаем метрики за период
            metrics = await self.get_usage_metrics(
                api_key_id=api_key_id, period="hour", hours_back=hours_back
            )

            if len(metrics) < 3:  # Нужно минимум 3 точки для анализа
                return anomalies

            # Анализируем трафик
            request_counts = [m.total_requests for m in metrics[-24:]]  # Последние 24 часа
            avg_requests = sum(request_counts) / len(request_counts)

            # Детектируем спайки трафика
            for metric in metrics[-6:]:  # Последние 6 часов
                if metric.total_requests > avg_requests * 3:  # 3x от среднего
                    anomalies.append(
                        {
                            "type": "traffic_spike",
                            "severity": "high",
                            "timestamp": metric.timestamp.isoformat(),
                            "description": f"Traffic spike: {metric.total_requests} requests (avg: {avg_requests:.0f})",
                            "metric": "total_requests",
                            "value": metric.total_requests,
                            "threshold": avg_requests * 3,
                        }
                    )

            # Детектируем высокий error rate
            for metric in metrics[-6:]:
                if metric.error_rate > 20:  # Больше 20% ошибок
                    anomalies.append(
                        {
                            "type": "high_error_rate",
                            "severity": "high",
                            "timestamp": metric.timestamp.isoformat(),
                            "description": f"High error rate: {metric.error_rate:.1f}%",
                            "metric": "error_rate",
                            "value": metric.error_rate,
                            "threshold": 20,
                        }
                    )

            # Детектируем медленные ответы
            response_times = [m.avg_response_time_ms for m in metrics if m.avg_response_time_ms > 0]
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)

                for metric in metrics[-6:]:
                    if metric.avg_response_time_ms > avg_response_time * 2:  # 2x от среднего
                        anomalies.append(
                            {
                                "type": "slow_responses",
                                "severity": "medium",
                                "timestamp": metric.timestamp.isoformat(),
                                "description": f"Slow responses: {metric.avg_response_time_ms:.0f}ms (avg: {avg_response_time:.0f}ms)",
                                "metric": "avg_response_time_ms",
                                "value": metric.avg_response_time_ms,
                                "threshold": avg_response_time * 2,
                            }
                        )

            return anomalies

        except Exception as e:
            print(f"Error detecting anomalies: {e}")
            return []

    async def get_global_statistics(self, hours_back: int = 24) -> Dict[str, Any]:
        """
        Получает глобальную статистику по всем API ключам

        Args:
            hours_back: Период для анализа

        Returns:
            Глобальная статистика
        """
        try:
            global_stats = await self.usage_repo.get_global_usage_stats(hours_back)

            # Добавляем дополнительную аналитику
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours_back)

            return {
                "period": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                    "hours": hours_back,
                },
                "global_metrics": global_stats,
                "system_health": {
                    "processed_events": self._processed_events,
                    "cache_size": len(self._metrics_cache),
                    "real_time_enabled": self.enable_real_time,
                    "alert_rules_count": len(self._alert_rules),
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            print(f"Error getting global statistics: {e}")
            return {"error": "Failed to get global statistics"}

    async def _update_real_time_metrics(self, usage_record: ApiUsageRecord) -> None:
        """Обновляет real-time метрики"""
        try:
            if not self.redis:
                return

            # Обновляем счетчики в Redis для real-time дашборда
            timestamp = int(usage_record.timestamp.timestamp())
            minute_key = f"realtime:{usage_record.api_key_id}:{timestamp // 60}"

            # Используем Redis pipeline для атомарности
            async with self.redis.pipeline() as pipe:
                await pipe.hincrby(minute_key, "total_requests", 1)

                if usage_record.status == RequestStatus.SUCCESS:
                    await pipe.hincrby(minute_key, "successful_requests", 1)
                else:
                    await pipe.hincrby(minute_key, "failed_requests", 1)

                if usage_record.is_spam_detected is not None:
                    if usage_record.is_spam_detected:
                        await pipe.hincrby(minute_key, "spam_detected", 1)
                    else:
                        await pipe.hincrby(minute_key, "clean_detected", 1)

                await pipe.expire(minute_key, 3600)  # TTL 1 час
                await pipe.execute()

        except Exception as e:
            print(f"Error updating real-time metrics: {e}")

    async def _check_alert_rules(self, api_key_id: int, usage_record: ApiUsageRecord) -> None:
        """Проверяет правила алертов"""
        try:
            # Получаем текущие метрики
            current_metrics = await self.get_real_time_metrics(api_key_id, 5)

            # Проверяем каждое правило
            for rule in self._alert_rules:
                if not rule.enabled:
                    continue

                if rule.check_violation(current_metrics):
                    await self._trigger_alert(rule, api_key_id, current_metrics)

        except Exception as e:
            print(f"Error checking alert rules: {e}")

    async def _trigger_alert(self, rule: AlertRule, api_key_id: int, metrics: UsageMetrics) -> None:
        """Активирует алерт"""
        try:
            alert_data = {
                "rule_name": rule.name,
                "api_key_id": api_key_id,
                "metric": rule.metric,
                "threshold": rule.threshold,
                "current_value": getattr(metrics, rule.metric, 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": "high" if rule.metric in ["error_rate", "response_time"] else "medium",
            }

            # В production здесь отправка в Slack, email, PagerDuty и т.д.
            print(f"🚨 ALERT: {rule.name} - API Key {api_key_id}")
            print(f"   {rule.metric}: {alert_data['current_value']} > {rule.threshold}")

            # Сохраняем алерт в БД для истории
            if self.redis:
                alert_key = f"alerts:{api_key_id}:{int(time.time())}"
                await self.redis.setex(alert_key, 86400, json.dumps(alert_data))

        except Exception as e:
            print(f"Error triggering alert: {e}")

    def _setup_default_alert_rules(self) -> None:
        """Настраивает дефолтные правила алертов"""
        self._alert_rules = [
            AlertRule(
                name="High Error Rate",
                condition="error_rate > 20",
                threshold=20,
                metric="error_rate",
                period_minutes=5,
            ),
            AlertRule(
                name="Slow Response Time",
                condition="avg_response_time_ms > 2000",
                threshold=2000,
                metric="avg_response_time_ms",
                period_minutes=5,
            ),
            AlertRule(
                name="Traffic Spike",
                condition="total_requests > 1000",
                threshold=1000,
                metric="total_requests",
                period_minutes=5,
            ),
        ]

    def _is_cache_valid(self, timestamp: datetime) -> bool:
        """Проверяет валидность кэша"""
        return (datetime.now(timezone.utc) - timestamp).total_seconds() < self._cache_ttl

    def health_check(self) -> Dict[str, Any]:
        """Health check для analytics сервиса"""
        try:
            return {
                "status": "healthy",
                "processed_events": self._processed_events,
                "cache_size": len(self._metrics_cache),
                "alert_rules": len(self._alert_rules),
                "real_time_enabled": self.enable_real_time,
                "last_cleanup": self._last_cleanup,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# Factory function
def create_usage_analytics(
    usage_repo, redis_client=None, config: Dict[str, Any] = None
) -> UsageAnalytics:
    """
    Фабрика для создания Usage Analytics

    Args:
        usage_repo: Repository для usage данных
        redis_client: Redis клиент
        config: Конфигурация

    Returns:
        Настроенный UsageAnalytics
    """
    if config is None:
        config = {}

    enable_real_time = config.get("enable_real_time", True)

    return UsageAnalytics(
        usage_repo=usage_repo, redis_client=redis_client, enable_real_time=enable_real_time
    )
