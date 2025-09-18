# src/domain/service/billing/billing_service.py
"""
Сервис биллинга для API
Интегрируется с существующей системой аналитики и добавляет расчет стоимости
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from ...entity.api_key import ApiKey
from ...entity.client_usage import ApiUsageRecord, RequestStatus
from ...entity.detection_result import DetectionResult, DetectionReason
from .token_calculator import (
    TokenCalculator,
    BillingResult,
    DetectionMethod,
    TokenUsage,
    BillingConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class BillingRecord:
    """Запись о биллинге для API запроса"""

    api_key_id: int
    request_id: str
    method: DetectionMethod
    cost_kopecks: int
    cost_rubles: float
    token_usage: Optional[TokenUsage] = None
    detection_reason: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        self.cost_rubles = self.cost_kopecks / 100.0


class BillingService:
    """
    Сервис биллинга для API

    Функции:
    - Расчет стоимости запросов
    - Интеграция с системой аналитики
    - Отслеживание расходов по API ключам
    - Поддержка batch запросов
    """

    def __init__(self, token_calculator: TokenCalculator = None):
        self.calculator = token_calculator or TokenCalculator()
        self._billing_records: List[BillingRecord] = []

        logger.info("💰 BillingService инициализирован")

    def calculate_request_cost(
        self,
        api_key: ApiKey,
        detection_result: DetectionResult,
        token_usage: Optional[TokenUsage] = None,
        request_id: str = None,
    ) -> BillingRecord:
        """
        Рассчитывает стоимость API запроса на основе результата детекции

        Args:
            api_key: API ключ клиента
            detection_result: Результат детекции спама
            token_usage: Использование токенов (для OpenAI)
            request_id: ID запроса для отслеживания

        Returns:
            BillingRecord с рассчитанной стоимостью
        """
        try:
            # Определяем метод детекции на основе результата
            method = self._determine_detection_method(detection_result)

            # Рассчитываем стоимость
            billing_result = self.calculator.calculate_cost(
                method=method,
                token_usage=token_usage,
                custom_details=f"API key {api_key.id}, request {request_id}",
            )

            # Создаем запись биллинга
            billing_record = BillingRecord(
                api_key_id=api_key.id,
                request_id=request_id or f"req_{datetime.now().timestamp()}",
                method=method,
                cost_kopecks=billing_result.cost_kopecks,
                token_usage=billing_result.token_usage,
                detection_reason=(
                    detection_result.primary_reason.value
                    if detection_result.primary_reason
                    else None
                ),
            )

            # Сохраняем запись
            self._billing_records.append(billing_record)

            logger.info(
                f"💰 Billing calculated: {billing_record.cost_rubles:.2f} RUB for {method.value} detection"
            )

            return billing_record

        except Exception as e:
            logger.error(f"Error calculating billing: {e}")
            # Возвращаем минимальную стоимость при ошибке
            return BillingRecord(
                api_key_id=api_key.id,
                request_id=request_id or "error",
                method=DetectionMethod.FALLBACK,
                cost_kopecks=self.calculator.config.min_request_cost,
                detection_reason="billing_error",
            )

    def calculate_batch_cost(
        self,
        api_key: ApiKey,
        detection_results: List[DetectionResult],
        token_usages: List[Optional[TokenUsage]] = None,
        batch_id: str = None,
    ) -> BillingRecord:
        """
        Рассчитывает стоимость batch запроса

        Args:
            api_key: API ключ клиента
            detection_results: Список результатов детекции
            token_usages: Список использования токенов
            batch_id: ID batch запроса

        Returns:
            BillingRecord с общей стоимостью
        """
        try:
            billing_results = []

            for i, detection_result in enumerate(detection_results):
                token_usage = token_usages[i] if token_usages and i < len(token_usages) else None
                method = self._determine_detection_method(detection_result)

                billing_result = self.calculator.calculate_cost(
                    method=method,
                    token_usage=token_usage,
                    custom_details=f"Batch {batch_id}, item {i}",
                )
                billing_results.append(billing_result)

            # Рассчитываем общую стоимость
            total_billing = self.calculator.calculate_batch_cost(billing_results)

            # Создаем запись биллинга
            billing_record = BillingRecord(
                api_key_id=api_key.id,
                request_id=batch_id or f"batch_{datetime.now().timestamp()}",
                method=total_billing.method,
                cost_kopecks=total_billing.cost_kopecks,
                token_usage=total_billing.token_usage,
                detection_reason=f"batch_{len(detection_results)}_items",
            )

            self._billing_records.append(billing_record)

            logger.info(
                f"💰 Batch billing calculated: {billing_record.cost_rubles:.2f} RUB for {len(detection_results)} items"
            )

            return billing_record

        except Exception as e:
            logger.error(f"Error calculating batch billing: {e}")
            return BillingRecord(
                api_key_id=api_key.id,
                request_id=batch_id or "batch_error",
                method=DetectionMethod.FALLBACK,
                cost_kopecks=self.calculator.config.min_request_cost * len(detection_results),
                detection_reason="batch_billing_error",
            )

    def _determine_detection_method(self, detection_result: DetectionResult) -> DetectionMethod:
        """
        Определяет метод детекции на основе результата

        Args:
            detection_result: Результат детекции

        Returns:
            DetectionMethod
        """
        if not detection_result.primary_reason:
            return DetectionMethod.FALLBACK

        reason = detection_result.primary_reason

        if reason == DetectionReason.CAS_BANNED:
            return DetectionMethod.CAS
        elif reason in [DetectionReason.RUSPAM_DETECTED, DetectionReason.RUSPAM_CLEAN]:
            return DetectionMethod.RUSPAM
        elif reason in [DetectionReason.OPENAI_DETECTED, DetectionReason.OPENAI_CLEAN]:
            return DetectionMethod.OPENAI
        else:
            return DetectionMethod.FALLBACK

    def get_billing_summary(
        self, api_key_id: int, start_date: datetime = None, end_date: datetime = None
    ) -> Dict[str, Any]:
        """
        Получает сводку по биллингу для API ключа

        Args:
            api_key_id: ID API ключа
            start_date: Начало периода
            end_date: Конец периода

        Returns:
            Словарь с информацией о биллинге
        """
        try:
            # Фильтруем записи по API ключу и периоду
            filtered_records = [
                record for record in self._billing_records if record.api_key_id == api_key_id
            ]

            if start_date:
                filtered_records = [
                    record for record in filtered_records if record.timestamp >= start_date
                ]

            if end_date:
                filtered_records = [
                    record for record in filtered_records if record.timestamp <= end_date
                ]

            # Подсчитываем статистику
            total_cost_kopecks = sum(record.cost_kopecks for record in filtered_records)
            total_requests = len(filtered_records)

            # Разбивка по методам
            method_breakdown = {}
            for record in filtered_records:
                method = record.method.value
                if method not in method_breakdown:
                    method_breakdown[method] = {
                        "count": 0,
                        "total_cost_kopecks": 0,
                        "total_cost_rubles": 0.0,
                    }
                method_breakdown[method]["count"] += 1
                method_breakdown[method]["total_cost_kopecks"] += record.cost_kopecks
                method_breakdown[method]["total_cost_rubles"] += record.cost_rubles

            return {
                "api_key_id": api_key_id,
                "period": {
                    "start": start_date.isoformat() if start_date else None,
                    "end": end_date.isoformat() if end_date else None,
                },
                "summary": {
                    "total_requests": total_requests,
                    "total_cost_kopecks": total_cost_kopecks,
                    "total_cost_rubles": total_cost_kopecks / 100.0,
                    "avg_cost_per_request_rubles": (
                        (total_cost_kopecks / 100.0) / total_requests if total_requests > 0 else 0.0
                    ),
                },
                "method_breakdown": method_breakdown,
                "current_prices": self.calculator.get_current_prices(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Error getting billing summary: {e}")
            return {
                "api_key_id": api_key_id,
                "error": str(e),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

    def update_pricing(self, multiplier: float) -> None:
        """
        Обновляет ценообразование

        Args:
            multiplier: Множитель для изменения цен
        """
        self.calculator.update_price_multiplier(multiplier)
        logger.info(f"💰 Pricing updated with multiplier: {multiplier}")

    def get_current_prices(self) -> Dict[str, Any]:
        """Возвращает текущие цены"""
        return self.calculator.get_current_prices()

    def estimate_cost(
        self, method: DetectionMethod, estimated_tokens: Optional[int] = None
    ) -> BillingResult:
        """
        Оценивает стоимость запроса без его выполнения

        Args:
            method: Метод детекции
            estimated_tokens: Предполагаемое количество токенов (для OpenAI)

        Returns:
            BillingResult с оценкой стоимости
        """
        token_usage = None
        if method == DetectionMethod.OPENAI and estimated_tokens:
            token_usage = TokenUsage(
                input_tokens=estimated_tokens, output_tokens=50  # Предполагаем 50 output токенов
            )

        return self.calculator.calculate_cost(
            method=method, token_usage=token_usage, custom_details="Cost estimation"
        )


# Глобальный экземпляр сервиса биллинга
_default_billing_service = BillingService()


def get_billing_service() -> BillingService:
    """Возвращает глобальный экземпляр сервиса биллинга"""
    return _default_billing_service
