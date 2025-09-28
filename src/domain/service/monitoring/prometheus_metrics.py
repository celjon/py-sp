"""
Production-ready Prometheus Metrics Service
Детальные метрики для мониторинга производительности и здоровья системы
"""

import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Info,
    CollectorRegistry,
    generate_latest,
    start_http_server,
    CONTENT_TYPE_LATEST,
)

class ApiKeyPlan(Enum):
    FREE = "free"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"

class RequestStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"


class MetricType(Enum):
    """Типы метрик"""

    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"
    INFO = "info"


@dataclass
class MetricConfig:
    """Конфигурация метрики"""

    name: str
    description: str
    labels: List[str]
    buckets: Optional[List[float]] = None


class PrometheusMetrics:
    """
    Production-ready Prometheus Metrics Service

    Features:
    - API performance метрики
    - Business метрики (детекция спама)
    - System health метрики
    - Rate limiting метрики
    - Authentication метрики
    - Custom registry для изоляции
    """

    def __init__(
        self, registry: Optional[CollectorRegistry] = None, enable_default_metrics: bool = True
    ):
        """
        Инициализация metrics service

        Args:
            registry: Custom Prometheus registry
            enable_default_metrics: Включить дефолтные system метрики
        """
        self.registry = registry or CollectorRegistry()
        self.enable_default_metrics = enable_default_metrics

        self._setup_api_metrics()

        self._setup_business_metrics()

        self._setup_system_metrics()

        self._setup_auth_metrics()

        self._setup_rate_limit_metrics()


    def _setup_api_metrics(self):
        """Настройка API метрик"""

        self.http_requests_total = Counter(
            "antispam_http_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status_code", "api_key_plan"],
            registry=self.registry,
        )

        self.http_request_duration = Histogram(
            "antispam_http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint", "api_key_plan"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
            registry=self.registry,
        )

        self.http_request_size_bytes = Histogram(
            "antispam_http_request_size_bytes",
            "HTTP request size in bytes",
            ["endpoint"],
            buckets=[100, 1000, 10000, 100000, 1000000],
            registry=self.registry,
        )

        self.http_response_size_bytes = Histogram(
            "antispam_http_response_size_bytes",
            "HTTP response size in bytes",
            ["endpoint"],
            buckets=[100, 1000, 10000, 100000],
            registry=self.registry,
        )

        self.active_connections = Gauge(
            "antispam_active_connections",
            "Number of active HTTP connections",
            registry=self.registry,
        )

    def _setup_business_metrics(self):
        """Настройка бизнес метрик"""

        self.spam_detections_total = Counter(
            "antispam_detections_total",
            "Total number of spam detections",
            ["result", "detector_type", "confidence_level", "api_key_plan"],
            registry=self.registry,
        )

        self.detection_duration = Histogram(
            "antispam_detection_duration_seconds",
            "Spam detection processing time",
            ["detector_type", "result"],
            buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 5.0],
            registry=self.registry,
        )

        self.detection_confidence = Histogram(
            "antispam_detection_confidence",
            "Confidence score of spam detection",
            ["detector_type", "result"],
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            registry=self.registry,
        )

        self.batch_operations_total = Counter(
            "antispam_batch_operations_total",
            "Total number of batch operations",
            ["batch_size_range", "api_key_plan"],
            registry=self.registry,
        )

        self.batch_processing_duration = Histogram(
            "antispam_batch_processing_duration_seconds",
            "Batch processing time",
            ["batch_size_range"],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
            registry=self.registry,
        )

    def _setup_system_metrics(self):
        """Настройка system метрик"""

        self.system_health = Gauge(
            "antispam_system_health",
            "System health status (1=healthy, 0=unhealthy)",
            ["component"],
            registry=self.registry,
        )

        self.database_connections = Gauge(
            "antispam_database_connections",
            "Number of database connections",
            ["pool_name", "state"],
            registry=self.registry,
        )

        self.cache_operations_total = Counter(
            "antispam_cache_operations_total",
            "Total cache operations",
            ["operation", "result"],
            registry=self.registry,
        )

        self.cache_hit_ratio = Gauge(
            "antispam_cache_hit_ratio", "Cache hit ratio", ["cache_type"], registry=self.registry
        )

        self.memory_usage_bytes = Gauge(
            "antispam_memory_usage_bytes",
            "Memory usage in bytes",
            ["memory_type"],
            registry=self.registry,
        )

        self.background_tasks_total = Counter(
            "antispam_background_tasks_total",
            "Total background tasks executed",
            ["task_type", "status"],
            registry=self.registry,
        )

        self.background_task_duration = Histogram(
            "antispam_background_task_duration_seconds",
            "Background task execution time",
            ["task_type"],
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
            registry=self.registry,
        )

    def _setup_auth_metrics(self):
        """Настройка authentication метрик"""

        self.api_keys_total = Gauge(
            "antispam_api_keys_total",
            "Total number of API keys",
            ["plan", "status"],
            registry=self.registry,
        )

        self.authentication_attempts_total = Counter(
            "antispam_authentication_attempts_total",
            "Total authentication attempts",
            ["method", "result"],
            registry=self.registry,
        )

        self.jwt_tokens_issued_total = Counter(
            "antispam_jwt_tokens_issued_total",
            "Total JWT tokens issued",
            ["token_type"],
            registry=self.registry,
        )

        self.jwt_tokens_validated_total = Counter(
            "antispam_jwt_tokens_validated_total",
            "Total JWT token validations",
            ["result"],
            registry=self.registry,
        )

    def _setup_rate_limit_metrics(self):
        """Настройка rate limiting метрик"""

        self.rate_limit_violations_total = Counter(
            "antispam_rate_limit_violations_total",
            "Total rate limit violations",
            ["limit_type", "api_key_plan"],
            registry=self.registry,
        )

        self.rate_limit_usage = Gauge(
            "antispam_rate_limit_usage",
            "Current rate limit usage",
            ["api_key_id", "limit_type"],
            registry=self.registry,
        )

        self.rate_limit_capacity = Gauge(
            "antispam_rate_limit_capacity",
            "Rate limit capacity",
            ["api_key_plan", "limit_type"],
            registry=self.registry,
        )


    def record_http_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration_seconds: float,
        api_key_plan: str = "unknown",
        request_size_bytes: int = 0,
        response_size_bytes: int = 0,
    ):
        """Записывает HTTP запрос"""
        try:
            normalized_endpoint = self._normalize_endpoint(endpoint)

            self.http_requests_total.labels(
                method=method,
                endpoint=normalized_endpoint,
                status_code=str(status_code),
                api_key_plan=api_key_plan,
            ).inc()

            self.http_request_duration.labels(
                method=method, endpoint=normalized_endpoint, api_key_plan=api_key_plan
            ).observe(duration_seconds)

            if request_size_bytes > 0:
                self.http_request_size_bytes.labels(endpoint=normalized_endpoint).observe(
                    request_size_bytes
                )

            if response_size_bytes > 0:
                self.http_response_size_bytes.labels(endpoint=normalized_endpoint).observe(
                    response_size_bytes
                )

        except Exception as e:
            pass

    def record_active_connection_change(self, delta: int):
        """Изменяет счетчик активных соединений"""
        try:
            if delta > 0:
                self.active_connections.inc(delta)
            elif delta < 0:
                self.active_connections.dec(abs(delta))
        except Exception as e:
            pass


    def record_spam_detection(
        self,
        is_spam: bool,
        confidence: float,
        detector_type: str,
        processing_time_seconds: float,
        api_key_plan: str = "unknown",
    ):
        """Записывает результат детекции спама"""
        try:
            result = "spam" if is_spam else "clean"
            confidence_level = self._get_confidence_level(confidence)

            self.spam_detections_total.labels(
                result=result,
                detector_type=detector_type,
                confidence_level=confidence_level,
                api_key_plan=api_key_plan,
            ).inc()

            self.detection_duration.labels(detector_type=detector_type, result=result).observe(
                processing_time_seconds
            )

            self.detection_confidence.labels(detector_type=detector_type, result=result).observe(
                confidence
            )

        except Exception as e:
            pass

    def record_batch_operation(
        self, batch_size: int, processing_time_seconds: float, api_key_plan: str = "unknown"
    ):
        """Записывает batch операцию"""
        try:
            batch_size_range = self._get_batch_size_range(batch_size)

            self.batch_operations_total.labels(
                batch_size_range=batch_size_range, api_key_plan=api_key_plan
            ).inc()

            self.batch_processing_duration.labels(batch_size_range=batch_size_range).observe(
                processing_time_seconds
            )

        except Exception as e:
            pass


    def set_system_health(self, component: str, is_healthy: bool):
        """Устанавливает статус здоровья компонента"""
        try:
            self.system_health.labels(component=component).set(1 if is_healthy else 0)
        except Exception as e:
            pass

    def set_database_connections(self, pool_name: str, active: int, idle: int):
        """Устанавливает количество database соединений"""
        try:
            self.database_connections.labels(pool_name=pool_name, state="active").set(active)
            self.database_connections.labels(pool_name=pool_name, state="idle").set(idle)
        except Exception as e:
            pass

    def record_cache_operation(self, operation: str, hit: bool):
        """Записывает cache операцию"""
        try:
            result = "hit" if hit else "miss"
            self.cache_operations_total.labels(operation=operation, result=result).inc()
        except Exception as e:
            pass

    def set_cache_hit_ratio(self, cache_type: str, ratio: float):
        """Устанавливает cache hit ratio"""
        try:
            self.cache_hit_ratio.labels(cache_type=cache_type).set(ratio)
        except Exception as e:
            pass

    def set_memory_usage(self, memory_type: str, bytes_used: int):
        """Устанавливает использование памяти"""
        try:
            self.memory_usage_bytes.labels(memory_type=memory_type).set(bytes_used)
        except Exception as e:
            pass

    def record_background_task(self, task_type: str, duration_seconds: float, success: bool):
        """Записывает выполнение background task"""
        try:
            status = "success" if success else "error"

            self.background_tasks_total.labels(task_type=task_type, status=status).inc()

            self.background_task_duration.labels(task_type=task_type).observe(duration_seconds)

        except Exception as e:
            pass


    def set_api_keys_count(self, plan: str, status: str, count: int):
        """Устанавливает количество API ключей"""
        try:
            self.api_keys_total.labels(plan=plan, status=status).set(count)
        except Exception as e:
            pass

    def record_authentication_attempt(self, method: str, success: bool):
        """Записывает попытку аутентификации"""
        try:
            result = "success" if success else "failure"
            self.authentication_attempts_total.labels(method=method, result=result).inc()
        except Exception as e:
            pass

    def record_jwt_token_issued(self, token_type: str):
        """Записывает выдачу JWT токена"""
        try:
            self.jwt_tokens_issued_total.labels(token_type=token_type).inc()
        except Exception as e:
            pass

    def record_jwt_token_validation(self, success: bool):
        """Записывает валидацию JWT токена"""
        try:
            result = "success" if success else "failure"
            self.jwt_tokens_validated_total.labels(result=result).inc()
        except Exception as e:
            pass


    def record_rate_limit_violation(self, limit_type: str, api_key_plan: str):
        """Записывает нарушение rate limit"""
        try:
            self.rate_limit_violations_total.labels(
                limit_type=limit_type, api_key_plan=api_key_plan
            ).inc()
        except Exception as e:
            pass

    def set_rate_limit_usage(self, api_key_id: str, limit_type: str, current_usage: int):
        """Устанавливает текущее использование rate limit"""
        try:
            self.rate_limit_usage.labels(api_key_id=str(api_key_id), limit_type=limit_type).set(
                current_usage
            )
        except Exception as e:
            pass

    def set_rate_limit_capacity(self, api_key_plan: str, limit_type: str, capacity: int):
        """Устанавливает capacity rate limit"""
        try:
            self.rate_limit_capacity.labels(api_key_plan=api_key_plan, limit_type=limit_type).set(
                capacity
            )
        except Exception as e:
            pass


    def _normalize_endpoint(self, endpoint: str) -> str:
        """Нормализует endpoint для метрик"""
        import re

        endpoint = re.sub(r"/\d+", "/{id}", endpoint)

        endpoint = re.sub(r"/[a-f0-9-]{36}", "/{uuid}", endpoint)

        if "?" in endpoint:
            endpoint = endpoint.split("?")[0]

        return endpoint

    def _get_confidence_level(self, confidence: float) -> str:
        """Получает уровень уверенности"""
        if confidence >= 0.9:
            return "very_high"
        elif confidence >= 0.7:
            return "high"
        elif confidence >= 0.5:
            return "medium"
        elif confidence >= 0.3:
            return "low"
        else:
            return "very_low"

    def _get_batch_size_range(self, batch_size: int) -> str:
        """Получает диапазон размера batch"""
        if batch_size <= 10:
            return "1-10"
        elif batch_size <= 25:
            return "11-25"
        elif batch_size <= 50:
            return "26-50"
        elif batch_size <= 100:
            return "51-100"
        else:
            return "100+"


    def get_metrics(self) -> str:
        """Возвращает метрики в формате Prometheus"""
        try:
            return generate_latest(self.registry)
        except Exception as e:
            return ""

    def start_metrics_server(self, port: int = 9090) -> None:
        """Запускает HTTP сервер для метрик"""
        try:
            start_http_server(port, registry=self.registry)
            pass
        except Exception as e:
            pass

    def health_check(self) -> Dict[str, Any]:
        """Health check для metrics service"""
        try:
            metrics_data = self.get_metrics()

            return {
                "status": "healthy",
                "metrics_count": len(self.registry._collector_to_names),
                "metrics_size_bytes": len(metrics_data),
                "registry_type": type(self.registry).__name__,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}




class MetricsMiddleware:
    """Middleware для автоматического сбора HTTP метрик"""

    def __init__(self, metrics: PrometheusMetrics):
        self.metrics = metrics

    async def __call__(self, request, call_next):
        """Middleware logic"""
        start_time = time.time()

        self.metrics.record_active_connection_change(1)

        try:
            response = await call_next(request)

            duration = time.time() - start_time
            api_key_plan = getattr(request.state, "api_key", None)
            if api_key_plan:
                api_key_plan = api_key_plan.plan.value
            else:
                api_key_plan = "unknown"

            self.metrics.record_http_request(
                method=request.method,
                endpoint=str(request.url.path),
                status_code=response.status_code,
                duration_seconds=duration,
                api_key_plan=api_key_plan,
                request_size_bytes=int(request.headers.get("content-length", 0)),
                response_size_bytes=len(getattr(response, "body", b"")),
            )

            return response

        finally:
            self.metrics.record_active_connection_change(-1)


def create_prometheus_metrics(enable_default_metrics: bool = True) -> PrometheusMetrics:
    """
    Factory function для создания Prometheus metrics

    Args:
        enable_default_metrics: Включить дефолтные system метрики

    Returns:
        Настроенный PrometheusMetrics
    """
    return PrometheusMetrics(enable_default_metrics=enable_default_metrics)



if __name__ == "__main__":
    metrics = create_prometheus_metrics()

    metrics.start_metrics_server(9090)

    metrics.record_http_request("POST", "/api/v1/detect", 200, 0.5, "basic")
    metrics.record_spam_detection(True, 0.85, "openai", 1.2, "basic")
    metrics.set_system_health("database", True)
    metrics.set_system_health("redis", True)

    pass
