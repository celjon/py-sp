# src/domain/service/billing/token_calculator.py
"""
Универсальная система подсчета стоимости за токены
Поддерживает фиксированную стоимость для CAS/RUSpam и оплату за токены для OpenAI
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class DetectionMethod(Enum):
    """Методы детекции спама"""

    CAS = "cas"
    RUSPAM = "ruspam"
    OPENAI = "openai"
    FALLBACK = "fallback"


@dataclass
class BillingConfig:
    """Конфигурация биллинга"""

    # Фиксированные цены (в копейках)
    cas_fixed_price: int = 1  # 1 копейка за CAS проверку
    ruspam_fixed_price: int = 2  # 2 копейки за RUSpam проверку

    # Цены за токены OpenAI (в копейках за 1000 токенов)
    openai_input_token_price: int = 15  # 15 копеек за 1000 input токенов
    openai_output_token_price: int = 60  # 60 копеек за 1000 output токенов

    # Множитель стоимости (для увеличения цен в 2 раза)
    price_multiplier: float = 1.0

    # Минимальная стоимость запроса (в копейках)
    min_request_cost: int = 1

    # Максимальная стоимость запроса (в копейках)
    max_request_cost: int = 10000  # 100 рублей


@dataclass
class TokenUsage:
    """Информация об использовании токенов"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self):
        self.total_tokens = self.input_tokens + self.output_tokens


@dataclass
class BillingResult:
    """Результат расчета стоимости"""

    method: DetectionMethod
    cost_kopecks: int
    cost_rubles: float
    token_usage: Optional[TokenUsage] = None
    details: str = ""

    def __post_init__(self):
        self.cost_rubles = self.cost_kopecks / 100.0


class TokenCalculator:
    """
    Универсальный калькулятор стоимости за токены

    Логика:
    1. CAS/RUSpam - фиксированная стоимость
    2. OpenAI - стоимость за токены
    3. Поддержка множителя для изменения цен
    """

    def __init__(self, config: BillingConfig = None):
        self.config = config or BillingConfig()
        logger.info(
            f"💰 TokenCalculator инициализирован с множителем {self.config.price_multiplier}"
        )

    def calculate_cost(
        self,
        method: DetectionMethod,
        token_usage: Optional[TokenUsage] = None,
        custom_details: str = "",
    ) -> BillingResult:
        """
        Рассчитывает стоимость запроса

        Args:
            method: Метод детекции
            token_usage: Использование токенов (для OpenAI)
            custom_details: Дополнительные детали

        Returns:
            BillingResult с рассчитанной стоимостью
        """
        try:
            if method == DetectionMethod.CAS:
                return self._calculate_cas_cost(custom_details)
            elif method == DetectionMethod.RUSPAM:
                return self._calculate_ruspam_cost(custom_details)
            elif method == DetectionMethod.OPENAI:
                if not token_usage:
                    raise ValueError("Token usage required for OpenAI billing")
                return self._calculate_openai_cost(token_usage, custom_details)
            else:
                # Fallback - минимальная стоимость
                return self._calculate_fallback_cost(custom_details)

        except Exception as e:
            logger.error(f"Error calculating cost for {method}: {e}")
            return self._calculate_fallback_cost(f"Error: {str(e)}")

    def _calculate_cas_cost(self, details: str) -> BillingResult:
        """Рассчитывает стоимость CAS проверки"""
        base_cost = self.config.cas_fixed_price
        final_cost = int(base_cost * self.config.price_multiplier)
        final_cost = max(final_cost, self.config.min_request_cost)
        final_cost = min(final_cost, self.config.max_request_cost)

        return BillingResult(
            method=DetectionMethod.CAS,
            cost_kopecks=final_cost,
            details=f"CAS fixed price: {base_cost} kopecks × {self.config.price_multiplier} = {final_cost} kopecks",
        )

    def _calculate_ruspam_cost(self, details: str) -> BillingResult:
        """Рассчитывает стоимость RUSpam проверки"""
        base_cost = self.config.ruspam_fixed_price
        final_cost = int(base_cost * self.config.price_multiplier)
        final_cost = max(final_cost, self.config.min_request_cost)
        final_cost = min(final_cost, self.config.max_request_cost)

        return BillingResult(
            method=DetectionMethod.RUSPAM,
            cost_kopecks=final_cost,
            details=f"RUSpam fixed price: {base_cost} kopecks × {self.config.price_multiplier} = {final_cost} kopecks",
        )

    def _calculate_openai_cost(self, token_usage: TokenUsage, details: str) -> BillingResult:
        """Рассчитывает стоимость OpenAI запроса по токенам"""
        # Стоимость за input токены
        input_cost = (token_usage.input_tokens / 1000.0) * self.config.openai_input_token_price

        # Стоимость за output токены
        output_cost = (token_usage.output_tokens / 1000.0) * self.config.openai_output_token_price

        # Общая стоимость
        total_cost = input_cost + output_cost

        # Применяем множитель
        final_cost = int(total_cost * self.config.price_multiplier)

        # Ограничиваем минимальной и максимальной стоимостью
        final_cost = max(final_cost, self.config.min_request_cost)
        final_cost = min(final_cost, self.config.max_request_cost)

        return BillingResult(
            method=DetectionMethod.OPENAI,
            cost_kopecks=final_cost,
            token_usage=token_usage,
            details=f"OpenAI tokens: {token_usage.input_tokens} input + {token_usage.output_tokens} output = {token_usage.total_tokens} total. Cost: {total_cost:.2f} kopecks × {self.config.price_multiplier} = {final_cost} kopecks",
        )

    def _calculate_fallback_cost(self, details: str) -> BillingResult:
        """Рассчитывает стоимость fallback запроса"""
        base_cost = self.config.min_request_cost
        final_cost = int(base_cost * self.config.price_multiplier)

        return BillingResult(
            method=DetectionMethod.FALLBACK,
            cost_kopecks=final_cost,
            details=f"Fallback cost: {base_cost} kopecks × {self.config.price_multiplier} = {final_cost} kopecks. {details}",
        )

    def update_price_multiplier(self, multiplier: float) -> None:
        """
        Обновляет множитель стоимости

        Args:
            multiplier: Новый множитель (например, 2.0 для удвоения цен)
        """
        if multiplier <= 0:
            raise ValueError("Price multiplier must be positive")

        old_multiplier = self.config.price_multiplier
        self.config.price_multiplier = multiplier

        logger.info(f"💰 Price multiplier updated: {old_multiplier} → {multiplier}")

    def get_current_prices(self) -> Dict[str, Any]:
        """Возвращает текущие цены"""
        return {
            "cas_fixed_price_kopecks": int(
                self.config.cas_fixed_price * self.config.price_multiplier
            ),
            "ruspam_fixed_price_kopecks": int(
                self.config.ruspam_fixed_price * self.config.price_multiplier
            ),
            "openai_input_price_per_1k_tokens_kopecks": int(
                self.config.openai_input_token_price * self.config.price_multiplier
            ),
            "openai_output_price_per_1k_tokens_kopecks": int(
                self.config.openai_output_token_price * self.config.price_multiplier
            ),
            "price_multiplier": self.config.price_multiplier,
            "min_request_cost_kopecks": int(
                self.config.min_request_cost * self.config.price_multiplier
            ),
            "max_request_cost_kopecks": int(
                self.config.max_request_cost * self.config.price_multiplier
            ),
        }

    def estimate_openai_cost(
        self, estimated_input_tokens: int, estimated_output_tokens: int = 50
    ) -> BillingResult:
        """
        Оценивает стоимость OpenAI запроса без реального выполнения

        Args:
            estimated_input_tokens: Предполагаемое количество input токенов
            estimated_output_tokens: Предполагаемое количество output токенов

        Returns:
            BillingResult с оценкой стоимости
        """
        token_usage = TokenUsage(
            input_tokens=estimated_input_tokens, output_tokens=estimated_output_tokens
        )

        return self._calculate_openai_cost(token_usage, "Estimated cost")

    def calculate_batch_cost(self, results: list[BillingResult]) -> BillingResult:
        """
        Рассчитывает общую стоимость для batch запроса

        Args:
            results: Список результатов расчета стоимости

        Returns:
            BillingResult с общей стоимостью
        """
        total_cost = sum(result.cost_kopecks for result in results)
        total_tokens = sum(
            result.token_usage.total_tokens for result in results if result.token_usage
        )

        # Определяем основной метод (самый дорогой)
        primary_method = max(results, key=lambda r: r.cost_kopecks).method

        return BillingResult(
            method=primary_method,
            cost_kopecks=total_cost,
            token_usage=TokenUsage(total_tokens=total_tokens) if total_tokens > 0 else None,
            details=f"Batch cost: {len(results)} requests, total {total_cost} kopecks",
        )


# Глобальный экземпляр калькулятора
_default_calculator = TokenCalculator()


def get_token_calculator() -> TokenCalculator:
    """Возвращает глобальный экземпляр калькулятора"""
    return _default_calculator


def create_calculator_with_multiplier(multiplier: float) -> TokenCalculator:
    """Создает новый калькулятор с заданным множителем"""
    config = BillingConfig(price_multiplier=multiplier)
    return TokenCalculator(config)
