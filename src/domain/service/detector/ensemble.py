# src/domain/service/detector/ensemble.py
"""
Production-Ready Ensemble Spam Detector v2.0
Архитектура: CAS → RUSpam → OpenAI (без устаревших эвристик и ML)
"""
import asyncio
import time
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectionResult, DetectorResult, DetectionReason
from .cas import CASDetector
from .openai import OpenAIDetector
from .ruspam_simple import RUSpamSimpleClassifier

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    """Circuit breaker состояние для детектора"""

    failure_count: int = 0
    last_failure_time: float = 0
    is_open: bool = False
    success_count: int = 0


class EnsembleDetector:
    """
    Production-ready ансамблевый детектор спама

    Архитектура (3 слоя с ранним выходом):
    1. 🛡️ CAS - мгновенная проверка базы забаненных (100ms)
    2. 🤖 RUSpam - BERT модель для спам-детекции (300ms)
    3. 🧠 OpenAI - LLM анализ сложных случаев (1.5s)

    Production Features:
    - Circuit breaker pattern для external services
    - Comprehensive error handling с fallbacks
    - Performance monitoring
    - Graceful degradation
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Детекторы (lazy initialization)
        self.cas_detector: Optional[CASDetector] = None
        self.openai_detector: Optional[OpenAIDetector] = None
        self.ruspam_detector: Optional[RUSpamSimpleClassifier] = None

        # Production пороги
        self.spam_threshold = self.config.get("spam_threshold", 0.6)
        self.high_confidence_threshold = self.config.get("high_confidence_threshold", 0.8)
        self.auto_ban_threshold = self.config.get("auto_ban_threshold", 0.85)

        # Настройки RUSpam
        self.use_ruspam = self.config.get("use_ruspam", True)
        self.ruspam_min_length = self.config.get("ruspam_min_length", 10)
        self.russian_threshold = self.config.get("russian_threshold", 0.3)

        # Настройки OpenAI
        self.openai_min_length = self.config.get("openai_min_length", 5)
        self.use_openai_fallback = self.config.get("use_openai_fallback", True)
        self.openai_timeout = self.config.get("openai_timeout", 5.0)

        # Performance settings
        self.max_processing_time = self.config.get("max_processing_time", 2.0)
        self.enable_early_exit = self.config.get("enable_early_exit", True)

        # Circuit breaker settings
        self.circuit_breaker_enabled = self.config.get("circuit_breaker_enabled", True)
        self.circuit_breaker_threshold = self.config.get("circuit_breaker_threshold", 5)
        self.circuit_breaker_timeout = self.config.get("circuit_breaker_timeout", 60)

        # Circuit breaker states
        self._circuit_breakers: Dict[str, CircuitBreakerState] = {
            "cas": CircuitBreakerState(),
            "ruspam": CircuitBreakerState(),
            "openai": CircuitBreakerState(),
        }

        # Performance metrics
        self._detection_count = 0
        self._total_processing_time = 0.0
        self._error_count = 0

        logger.info("🎯 Production ансамбль инициализирован: CAS + RUSpam + OpenAI")
        logger.info(
            f"   Пороги: spam={self.spam_threshold}, high={self.high_confidence_threshold}, auto_ban={self.auto_ban_threshold}"
        )
        logger.info(
            f"   Circuit breaker: {'enabled' if self.circuit_breaker_enabled else 'disabled'}"
        )

    def add_cas_detector(self, cas_gateway) -> None:
        """Добавляет CAS детектор"""
        self.cas_detector = CASDetector(cas_gateway)
        logger.info("✅ CAS детектор добавлен")

    def add_openai_detector(self, openai_gateway) -> None:
        """Добавляет OpenAI детектор"""
        self.openai_detector = OpenAIDetector(openai_gateway)
        logger.info("✅ OpenAI детектор добавлен")

    def add_ruspam_detector(self) -> None:
        """Добавляет RUSpam BERT детектор"""
        if not self.use_ruspam:
            logger.warning("⚠️ RUSpam отключен в конфигурации")
            return

        try:
            self.ruspam_detector = RUSpamSimpleClassifier()
            logger.info("✅ RUSpam BERT детектор инициализирован")
        except ImportError as e:
            logger.warning(f"⚠️ RUSpam dependencies не найдены: {e}")
            logger.info("💡 Установите: pip install torch transformers ruSpam")
            self.ruspam_detector = None
        except Exception as e:
            logger.error(f"⚠️ RUSpam не загружен: {e}")
            self.ruspam_detector = None

    def _is_circuit_breaker_open(self, detector_name: str) -> bool:
        """Проверяет, открыт ли circuit breaker для детектора"""
        if not self.circuit_breaker_enabled:
            return False

        breaker = self._circuit_breakers.get(detector_name)
        if not breaker or not breaker.is_open:
            return False

        # Проверяем, не пора ли попробовать снова
        if time.time() - breaker.last_failure_time > self.circuit_breaker_timeout:
            breaker.is_open = False
            breaker.failure_count = 0
            logger.info(f"🔄 Circuit breaker для {detector_name} переходит в half-open")
            return False

        return True

    def _record_detector_success(self, detector_name: str):
        """Записывает успешный вызов детектора"""
        if not self.circuit_breaker_enabled:
            return

        breaker = self._circuit_breakers.get(detector_name)
        if breaker:
            breaker.success_count += 1
            if breaker.is_open and breaker.success_count >= 3:
                # Закрываем circuit breaker после нескольких успешных вызовов
                breaker.is_open = False
                breaker.failure_count = 0
                logger.info(f"✅ Circuit breaker для {detector_name} закрыт")

    def _record_detector_failure(self, detector_name: str, error: Exception):
        """Записывает ошибку детектора"""
        if not self.circuit_breaker_enabled:
            return

        breaker = self._circuit_breakers.get(detector_name)
        if breaker:
            breaker.failure_count += 1
            breaker.last_failure_time = time.time()
            breaker.success_count = 0

            if breaker.failure_count >= self.circuit_breaker_threshold:
                breaker.is_open = True
                logger.warning(
                    f"🚨 Circuit breaker для {detector_name} открыт после {breaker.failure_count} ошибок"
                )
                logger.warning(f"   Последняя ошибка: {error}")

    def _detect_language(self, text: str) -> str:
        """
        Определяет язык текста для оптимизации детекции

        Returns:
            "ru" - русский (приоритет RUSpam)
            "en" - английский
            "mixed" - смешанный
            "unknown" - неопределен
        """
        if not text:
            return "unknown"

        # Подсчитываем символы
        cyrillic_chars = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
        latin_chars = sum(1 for c in text if c.isalpha() and not ("\u0400" <= c <= "\u04ff"))

        total_letters = cyrillic_chars + latin_chars
        if total_letters == 0:
            return "unknown"

        cyrillic_ratio = cyrillic_chars / total_letters

        if cyrillic_ratio >= self.russian_threshold:
            return "ru"
        elif cyrillic_ratio < 0.1:
            return "en"
        else:
            return "mixed"

    async def detect(
        self, message: Message, user_context: Dict[str, Any] = None
    ) -> DetectionResult:
        """
        Основной метод детекции спама с полным error handling

        Production логика:
        1. 🛡️ CAS проверка (100ms) - если забанен → мгновенный бан
        2. 🤖 RUSpam BERT (300ms) - если спам ≥0.8 → ранний выход
        3. 🧠 OpenAI LLM (1.5s) - контекстуальный анализ

        Args:
            message: Сообщение для анализа
            user_context: Контекст пользователя

        Returns:
            DetectionResult с рекомендациями по действиям
        """
        start_time = time.time()
        results: List[DetectorResult] = []
        is_spam_detected = False
        primary_reason: Optional[DetectionReason] = None
        max_confidence = 0.0

        text = message.text or ""
        detected_language = self._detect_language(text)

        # Увеличиваем счетчик детекций
        self._detection_count += 1

        logger.info(
            f"🔍 Детекция #{self._detection_count}: '{text[:50]}{'...' if len(text) > 50 else ''}' (язык: {detected_language})"
        )

        try:
            # === СЛОЙ 1: CAS СИСТЕМА (критический путь) ===
            cas_result = await self._check_cas(message, user_context)
            if cas_result:
                results.append(cas_result)
                if cas_result.is_spam:
                    # CAS бан абсолютен - мгновенный выход
                    final_result = self._create_final_result(
                        message,
                        results,
                        True,
                        DetectionReason.CAS_BANNED,
                        1.0,
                        start_time,
                        "Пользователь забанен в CAS базе",
                    )
                    logger.warning(
                        f"🚨 CAS BAN: пользователь {message.user_id} ({final_result.processing_time_ms:.1f}ms)"
                    )
                    return final_result

            # === СЛОЙ 2: RUSPAM BERT ===
            ruspam_result = await self._check_ruspam(text, detected_language)
            if ruspam_result:
                results.append(ruspam_result)
                if ruspam_result.is_spam:
                    is_spam_detected = True
                    primary_reason = DetectionReason.CLASSIFIER
                    max_confidence = ruspam_result.confidence

                    # Ранний выход при высокой уверенности
                    if (
                        self.enable_early_exit
                        and ruspam_result.confidence >= self.high_confidence_threshold
                    ):

                        final_result = self._create_final_result(
                            message,
                            results,
                            True,
                            primary_reason,
                            max_confidence,
                            start_time,
                            f"RUSpam высокая уверенность: {ruspam_result.details}",
                        )
                        logger.warning(
                            f"🚨 EARLY EXIT: RUSpam уверенность {ruspam_result.confidence:.3f} ({final_result.processing_time_ms:.1f}ms)"
                        )
                        return final_result

            # === СЛОЙ 3: OPENAI LLM ===
            # Проверяем таймаут
            elapsed_time = time.time() - start_time
            if elapsed_time >= self.max_processing_time:
                logger.warning(
                    f"⏰ Превышен лимит времени ({elapsed_time:.2f}s), пропускаем OpenAI"
                )
            else:
                openai_result = await self._check_openai(message, user_context, text)
                if openai_result:
                    results.append(openai_result)
                    if openai_result.is_spam:
                        if not is_spam_detected:  # OpenAI как первичный детектор
                            is_spam_detected = True
                            primary_reason = DetectionReason.OPENAI_DETECTED
                        max_confidence = max(max_confidence, openai_result.confidence)

            # Генерируем финальное решение
            notes = self._generate_notes(results, detected_language, is_spam_detected)

            final_result = self._create_final_result(
                message,
                results,
                is_spam_detected,
                primary_reason,
                max_confidence,
                start_time,
                notes,
            )

            # Записываем метрики
            self._update_performance_metrics(final_result.processing_time_ms)

            # Логируем результат
            result_emoji = "🚨" if is_spam_detected else "✅"
            logger.info(
                f"{result_emoji} Детекция завершена: spam={is_spam_detected}, confidence={max_confidence:.3f}, время={final_result.processing_time_ms:.1f}ms"
            )

            return final_result

        except asyncio.TimeoutError:
            logger.error(f"⏰ Timeout при детекции сообщения {message.id}")
            self._error_count += 1
            return self._create_timeout_result(message, results, start_time)
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в детекции: {e}")
            self._error_count += 1
            return self._create_error_result(message, results, start_time, str(e))

    async def _check_cas(
        self, message: Message, user_context: Dict[str, Any]
    ) -> Optional[DetectorResult]:
        """Проверка CAS базы с circuit breaker"""
        detector_name = "cas"

        if not self.cas_detector:
            return None

        # Проверяем circuit breaker
        if self._is_circuit_breaker_open(detector_name):
            logger.warning(f"⚡ CAS circuit breaker открыт, пропускаем проверку")
            return None

        try:
            start_cas = time.time()
            cas_result = await asyncio.wait_for(
                self.cas_detector.detect(message, user_context), timeout=1.0  # 1 секунда на CAS
            )
            processing_time = (time.time() - start_cas) * 1000

            # Записываем успех
            self._record_detector_success(detector_name)

            if cas_result.is_spam:
                logger.warning(
                    f"🚨 CAS: Пользователь {message.user_id} забанен ({processing_time:.1f}ms)"
                )
            else:
                logger.debug(f"✅ CAS: Пользователь чист ({processing_time:.1f}ms)")

            return cas_result

        except asyncio.TimeoutError:
            logger.warning(f"⏰ CAS timeout для пользователя {message.user_id}")
            self._record_detector_failure(detector_name, TimeoutError("CAS timeout"))
            return None
        except Exception as e:
            logger.error(f"⚠️ CAS ошибка: {e}")
            self._record_detector_failure(detector_name, e)
            return None

    async def _check_ruspam(self, text: str, language: str) -> Optional[DetectorResult]:
        """Проверка RUSpam BERT с circuit breaker"""
        detector_name = "ruspam"

        if not self.ruspam_detector or len(text.strip()) < self.ruspam_min_length:
            return None

        # Проверяем circuit breaker
        if self._is_circuit_breaker_open(detector_name):
            logger.warning(f"⚡ RUSpam circuit breaker открыт, пропускаем проверку")
            return None

        try:
            start_ruspam = time.time()
            ruspam_result = await asyncio.wait_for(
                self.ruspam_detector.classify(text), timeout=2.0  # 2 секунды на RUSpam
            )
            processing_time = (time.time() - start_ruspam) * 1000

            # Записываем успех
            self._record_detector_success(detector_name)

            detector_result = DetectorResult(
                detector_name="RUSpam",
                is_spam=ruspam_result.is_spam,
                confidence=ruspam_result.confidence,
                details=ruspam_result.details,
                processing_time_ms=processing_time,
            )

            if ruspam_result.is_spam:
                logger.warning(
                    f"🚨 RUSpam: СПАМ обнаружен ({ruspam_result.confidence:.3f}, {processing_time:.1f}ms)"
                )
            else:
                logger.debug(
                    f"✅ RUSpam: Сообщение чистое ({1.0 - ruspam_result.confidence:.3f}, {processing_time:.1f}ms)"
                )

            return detector_result

        except asyncio.TimeoutError:
            logger.warning(f"⏰ RUSpam timeout")
            self._record_detector_failure(detector_name, TimeoutError("RUSpam timeout"))
            return None
        except Exception as e:
            logger.error(f"⚠️ RUSpam ошибка: {e}")
            self._record_detector_failure(detector_name, e)
            return DetectorResult(
                detector_name="RUSpam",
                is_spam=False,
                confidence=0.0,
                details=f"RUSpam error: {str(e)}",
                error=str(e),
                processing_time_ms=0.0,
            )

    async def _check_openai(
        self, message: Message, user_context: Dict[str, Any], text: str
    ) -> Optional[DetectorResult]:
        """Проверка OpenAI LLM с circuit breaker"""
        detector_name = "openai"

        if (
            not self.openai_detector
            or not self.use_openai_fallback
            or len(text.strip()) < self.openai_min_length
        ):
            return None

        # Проверяем circuit breaker
        if self._is_circuit_breaker_open(detector_name):
            logger.warning(f"⚡ OpenAI circuit breaker открыт, пропускаем проверку")
            return None

        try:
            start_openai = time.time()
            openai_result = await asyncio.wait_for(
                self.openai_detector.detect(message, user_context), timeout=self.openai_timeout
            )
            processing_time = (time.time() - start_openai) * 1000

            # Записываем успех
            self._record_detector_success(detector_name)

            if openai_result.is_spam:
                logger.warning(
                    f"🚨 OpenAI: СПАМ обнаружен ({openai_result.confidence:.3f}, {processing_time:.1f}ms)"
                )
            else:
                logger.debug(f"✅ OpenAI: Сообщение чистое ({processing_time:.1f}ms)")

            return openai_result

        except asyncio.TimeoutError:
            logger.warning(f"⏰ OpenAI timeout")
            self._record_detector_failure(detector_name, TimeoutError("OpenAI timeout"))
            return None
        except Exception as e:
            logger.error(f"⚠️ OpenAI ошибка: {e}")
            self._record_detector_failure(detector_name, e)
            return DetectorResult(
                detector_name="OpenAI",
                is_spam=False,
                confidence=0.0,
                details=f"OpenAI error: {str(e)}",
                error=str(e),
                processing_time_ms=0.0,
            )

    def _create_final_result(
        self,
        message: Message,
        results: List[DetectorResult],
        is_spam: bool,
        primary_reason: Optional[DetectionReason],
        confidence: float,
        start_time: float,
        notes: str,
    ) -> DetectionResult:
        """Создает финальный результат детекции"""

        processing_time_ms = (time.time() - start_time) * 1000

        # Определяем рекомендуемые действия
        action = self._determine_action(confidence, is_spam, user_context=None)
        should_ban = action == "ban_and_delete"
        should_delete = action in ["ban_and_delete", "delete_and_warn"]
        should_restrict = action == "soft_warn_or_review"
        should_warn = action in ["delete_and_warn", "soft_warn_or_review"]

        # Собираем список причин
        detection_reasons = []
        for result in results:
            if result.is_spam and result.details:
                detection_reasons.append(result.details)

        return DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=is_spam,
            overall_confidence=confidence,
            primary_reason=primary_reason,
            detector_results=results,
            processing_time_ms=processing_time_ms,
            notes=notes,
            reasons=detection_reasons,
            recommended_action=action,
            should_ban=should_ban,
            should_delete=should_delete,
            should_restrict=should_restrict,
            should_warn=should_warn,
        )

    def _determine_action(
        self, confidence: float, is_spam: bool, user_context: Dict[str, Any] = None
    ) -> str:
        """
        Определяет рекомендуемое действие на основе уверенности и контекста

        Production пороги:
        - ≥0.85: ban_and_delete (автобан)
        - 0.70-0.85: delete_and_warn (удалить + предупреждение)
        - 0.60-0.70: soft_warn_or_review (мягкое предупреждение)
        - <0.60: allow (разрешить)

        Модификаторы:
        - Новые пользователи: понижение порога на 0.1
        - Админы/владельцы: только логирование
        """
        if not is_spam:
            return "allow"

        # Проверяем админа/владельца
        if user_context and user_context.get("is_admin_or_owner", False):
            return "allow"  # Админов не банят автоматически

        # Применяем модификаторы
        effective_confidence = confidence

        # Новый пользователь - более строгие правила
        if user_context and user_context.get("is_new_user", False):
            effective_confidence += 0.1  # Повышаем уверенность для новых

        # Предыдущие нарушения
        previous_warnings = user_context.get("previous_warnings", 0) if user_context else 0
        if previous_warnings > 0:
            effective_confidence += 0.05 * previous_warnings  # +5% за каждое предупреждение

        # Определяем действие
        if effective_confidence >= self.auto_ban_threshold:
            return "ban_and_delete"
        elif effective_confidence >= 0.70:
            return "delete_and_warn"
        elif effective_confidence >= self.spam_threshold:
            return "soft_warn_or_review"
        else:
            return "allow"

    def _generate_notes(self, results: List[DetectorResult], language: str, is_spam: bool) -> str:
        """Генерирует человекочитаемые заметки о детекции"""
        if not results:
            return "Детекторы не активны"

        active_detectors = [r.detector_name for r in results if r.confidence > 0]
        spam_detectors = [r.detector_name for r in results if r.is_spam]

        if is_spam and spam_detectors:
            spam_details = []
            for result in results:
                if result.is_spam and result.details:
                    spam_details.append(f"{result.detector_name}: {result.details}")

            details_str = "; ".join(spam_details) if spam_details else "неизвестные причины"
            return f"Спам обнаружен ({', '.join(spam_detectors)}): {details_str} [язык: {language}]"
        else:
            return f"Сообщение прошло проверку ({', '.join(active_detectors)}) [язык: {language}]"

    def _create_timeout_result(
        self, message: Message, results: List[DetectorResult], start_time: float
    ) -> DetectionResult:
        """Создает результат при превышении таймаута"""
        processing_time_ms = (time.time() - start_time) * 1000

        return DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=False,  # При таймауте не блокируем
            overall_confidence=0.0,
            primary_reason=None,
            detector_results=results,
            processing_time_ms=processing_time_ms,
            notes=f"Превышен лимит времени обработки ({processing_time_ms:.1f}ms)",
            reasons=["timeout"],
            recommended_action="allow",
            should_ban=False,
            should_delete=False,
            should_restrict=False,
            should_warn=False,
        )

    def _create_error_result(
        self, message: Message, results: List[DetectorResult], start_time: float, error: str
    ) -> DetectionResult:
        """Создает результат при критической ошибке"""
        processing_time_ms = (time.time() - start_time) * 1000

        return DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=False,  # При ошибке не блокируем
            overall_confidence=0.0,
            primary_reason=None,
            detector_results=results,
            processing_time_ms=processing_time_ms,
            notes=f"Ошибка детекции: {error}",
            reasons=["detection_error"],
            recommended_action="allow",
            should_ban=False,
            should_delete=False,
            should_restrict=False,
            should_warn=False,
        )

    def _update_performance_metrics(self, processing_time_ms: float):
        """Обновляет метрики производительности"""
        self._total_processing_time += processing_time_ms

        # Логируем если обработка слишком долгая
        if processing_time_ms > self.max_processing_time * 1000:
            logger.warning(
                f"⚠️ Медленная детекция: {processing_time_ms:.1f}ms (лимит: {self.max_processing_time * 1000}ms)"
            )

    async def get_available_detectors(self) -> List[str]:
        """Возвращает список доступных детекторов"""
        detectors = []

        if self.cas_detector:
            detectors.append("cas")
        if self.ruspam_detector:
            detectors.append("ruspam")
        if self.openai_detector:
            detectors.append("openai")

        return detectors

    async def get_performance_stats(self) -> Dict[str, Any]:
        """Возвращает статистику производительности"""
        avg_processing_time = (
            self._total_processing_time / self._detection_count if self._detection_count > 0 else 0
        )

        error_rate = self._error_count / self._detection_count if self._detection_count > 0 else 0

        return {
            "total_detections": self._detection_count,
            "total_errors": self._error_count,
            "error_rate": error_rate,
            "average_processing_time_ms": avg_processing_time,
            "circuit_breakers": {
                name: {
                    "is_open": state.is_open,
                    "failure_count": state.failure_count,
                    "success_count": state.success_count,
                }
                for name, state in self._circuit_breakers.items()
            },
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Комплексная проверка состояния всех детекторов

        Returns:
            Словарь с состоянием системы
        """
        health = {
            "status": "unknown",
            "architecture": "modern",  # CAS + RUSpam + OpenAI
            "detectors": {},
            "timestamp": time.time(),
            "performance": {
                "max_processing_time": self.max_processing_time,
                "early_exit_enabled": self.enable_early_exit,
                "circuit_breaker_enabled": self.circuit_breaker_enabled,
            },
        }

        detectors_status = []

        # CAS детектор
        try:
            if self.cas_detector:
                # Проверяем circuit breaker
                cb_state = self._circuit_breakers.get("cas", CircuitBreakerState())
                health["detectors"]["cas"] = {
                    "status": "degraded" if cb_state.is_open else "healthy",
                    "available": not cb_state.is_open,
                    "type": "user_database",
                    "circuit_breaker": {
                        "is_open": cb_state.is_open,
                        "failure_count": cb_state.failure_count,
                    },
                }
                detectors_status.append(not cb_state.is_open)
            else:
                health["detectors"]["cas"] = {"status": "not_configured", "available": False}
        except Exception as e:
            health["detectors"]["cas"] = {"status": "error", "error": str(e), "available": False}
            detectors_status.append(False)

        # RUSpam детектор
        try:
            if self.ruspam_detector:
                # Быстрый тест
                try:
                    test_result = await asyncio.wait_for(
                        self.ruspam_detector.classify("тест"), timeout=2.0
                    )

                    cb_state = self._circuit_breakers.get("ruspam", CircuitBreakerState())
                    health["detectors"]["ruspam"] = {
                        "status": "degraded" if cb_state.is_open else "healthy",
                        "available": not cb_state.is_open,
                        "type": "bert_model",
                        "circuit_breaker": {
                            "is_open": cb_state.is_open,
                            "failure_count": cb_state.failure_count,
                        },
                    }
                    detectors_status.append(not cb_state.is_open)
                except Exception as e:
                    health["detectors"]["ruspam"] = {
                        "status": "error",
                        "error": str(e),
                        "available": False,
                    }
                    detectors_status.append(False)
            else:
                health["detectors"]["ruspam"] = {"status": "not_available", "available": False}
        except Exception as e:
            health["detectors"]["ruspam"] = {"status": "error", "error": str(e), "available": False}
            detectors_status.append(False)

        # OpenAI детектор
        try:
            if self.openai_detector:
                cb_state = self._circuit_breakers.get("openai", CircuitBreakerState())
                health["detectors"]["openai"] = {
                    "status": "degraded" if cb_state.is_open else "healthy",
                    "available": not cb_state.is_open,
                    "type": "llm_model",
                    "circuit_breaker": {
                        "is_open": cb_state.is_open,
                        "failure_count": cb_state.failure_count,
                    },
                }
                detectors_status.append(not cb_state.is_open)
            else:
                health["detectors"]["openai"] = {"status": "not_configured", "available": False}
        except Exception as e:
            health["detectors"]["openai"] = {"status": "error", "error": str(e), "available": False}
            detectors_status.append(False)

        # Определяем общий статус
        available_count = sum(1 for status in detectors_status if status)

        if available_count >= 2:
            health["status"] = "healthy"
        elif available_count >= 1:
            health["status"] = "degraded"
        else:
            health["status"] = "unhealthy"

        # Добавляем рекомендации
        if health["status"] != "healthy":
            health["recommendations"] = []
            if available_count == 0:
                health["recommendations"].append("Настройте хотя бы один детектор")
            if "cas" not in health["detectors"] or not health["detectors"]["cas"].get("available"):
                health["recommendations"].append("Настройте CAS для защиты от известных спамеров")
            if "ruspam" not in health["detectors"] or not health["detectors"]["ruspam"].get(
                "available"
            ):
                health["recommendations"].append("Установите RUSpam для BERT анализа")

        # Добавляем performance stats
        health["performance_stats"] = await self.get_performance_stats()

        return health
