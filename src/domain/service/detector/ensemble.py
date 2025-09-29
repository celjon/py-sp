"""
Production-Ready Ensemble Spam Detector v2.0
Архитектура: CAS → RUSpam → BotHub (без устаревших эвристик и ML)
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
from .bothub import BotHubDetector
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
    3. 🔗 BotHub - LLM анализ сложных случаев (1.5s)

    Production Features:
    - Circuit breaker pattern для external services
    - Comprehensive error handling с fallbacks
    - Performance monitoring
    - Graceful degradation
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        self.cas_detector: Optional[CASDetector] = None
        self.bothub_detector: Optional[BotHubDetector] = None
        self.ruspam_detector: Optional[RUSpamSimpleClassifier] = None

        self.spam_threshold = self.config.get("spam_threshold", 0.6)
        self.high_confidence_threshold = self.config.get("high_confidence_threshold", 0.8)
        self.auto_ban_threshold = self.config.get("auto_ban_threshold", 0.85)

        self.use_ruspam = self.config.get("use_ruspam", True)
        self.ruspam_min_length = self.config.get("ruspam_min_length", 10)
        self.russian_threshold = self.config.get("russian_threshold", 0.3)

        
        self.bothub_min_length = self.config.get("bothub_min_length", 5)
        self.use_bothub_fallback = self.config.get("use_bothub_fallback", True)
        self.bothub_timeout = self.config.get("bothub_timeout", 60.0)
        self.bothub_min_ruspam_confidence = self.config.get("bothub_min_ruspam_confidence", 0.2)

        self.max_processing_time = self.config.get("max_processing_time", 2.0)
        self.enable_early_exit = self.config.get("enable_early_exit", True)

        self.circuit_breaker_enabled = self.config.get("circuit_breaker_enabled", True)
        self.circuit_breaker_threshold = self.config.get("circuit_breaker_threshold", 5)
        self.circuit_breaker_timeout = self.config.get("circuit_breaker_timeout", 60)

        self._circuit_breakers: Dict[str, CircuitBreakerState] = {
            "cas": CircuitBreakerState(),
            "ruspam": CircuitBreakerState(),
            "bothub": CircuitBreakerState(),
        }

        self._bothub_detectors_cache: Dict[str, tuple] = {}

        self._detection_count = 0
        self._total_processing_time = 0.0
        self._error_count = 0

        logger.info("[TARGET] Production ансамбль инициализирован: CAS + RUSpam + BotHub")
        logger.info(
            f"   Пороги: spam={self.spam_threshold}, high={self.high_confidence_threshold}, auto_ban={self.auto_ban_threshold}"
        )
        logger.info(
            f"   Circuit breaker: {'enabled' if self.circuit_breaker_enabled else 'disabled'}"
        )

    def add_cas_detector(self, cas_gateway) -> None:
        """Добавляет CAS детектор"""
        self.cas_detector = CASDetector(cas_gateway)
        logger.info("[OK] CAS детектор добавлен")


    def add_bothub_detector(self, bothub_gateway) -> None:
        """Добавляет BotHub детектор (новый провайдер)"""
        self.bothub_detector = BotHubDetector(bothub_gateway)
        logger.info("[OK] BotHub детектор добавлен")

    def add_ruspam_detector(self) -> None:
        """Добавляет RUSpam BERT детектор (критический компонент)"""
        if not self.use_ruspam:
            logger.warning("[WARN] RUSpam отключен в конфигурации")
            return

        try:
            self.ruspam_detector = RUSpamSimpleClassifier()
            logger.info("[OK] RUSpam BERT детектор инициализирован")
        except ImportError as e:
            error_msg = f"КРИТИЧЕСКАЯ ОШИБКА: RUSpam dependencies не найдены: {e}"
            logger.error(f"[ERROR] {error_msg}")
            logger.error("💡 Установите: pip install torch transformers")
            raise RuntimeError(error_msg)
        except RuntimeError:
            raise
        except Exception as e:
            error_msg = f"КРИТИЧЕСКАЯ ОШИБКА: RUSpam не загружен: {e}"
            logger.error(f"[ERROR] {error_msg}")
            raise RuntimeError(error_msg)

    def _is_circuit_breaker_open(self, detector_name: str) -> bool:
        """Проверяет, открыт ли circuit breaker для детектора"""
        if not self.circuit_breaker_enabled:
            return False

        breaker = self._circuit_breakers.get(detector_name)
        if not breaker or not breaker.is_open:
            return False

        if time.time() - breaker.last_failure_time > self.circuit_breaker_timeout:
            breaker.is_open = False
            breaker.failure_count = 0
            logger.info(f"[REFRESH] Circuit breaker для {detector_name} переходит в half-open")
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
                breaker.is_open = False
                breaker.failure_count = 0
                logger.info(f"[OK] Circuit breaker для {detector_name} закрыт")

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
                    f"[ALERT] Circuit breaker для {detector_name} открыт после {breaker.failure_count} ошибок"
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
        3. 🧠 BotHub LLM (1.5s) - контекстуальный анализ

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
        overall_confidence = 0.0

        text = message.text or ""
        detected_language = self._detect_language(text)

        self._detection_count += 1

        logger.info(
            f"[SEARCH] Детекция #{self._detection_count}: '{text[:50]}{'...' if len(text) > 50 else ''}' (язык: {detected_language})"
        )

        try:
            cas_result = await self._check_cas(message, user_context)
            if cas_result:
                results.append(cas_result)
                if cas_result.is_spam:
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
                        f"[ALERT] CAS BAN: пользователь {message.user_id} ({final_result.processing_time_ms:.1f}ms)"
                    )
                    return final_result

            ruspam_result = await self._check_ruspam(text, detected_language)
            if ruspam_result:
                results.append(ruspam_result)
                overall_confidence = max(overall_confidence, ruspam_result.confidence)
                if ruspam_result.is_spam:
                    is_spam_detected = True
                    primary_reason = DetectionReason.RUSPAM_DETECTED
                    max_confidence = ruspam_result.confidence

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
                            f"[ALERT] EARLY EXIT: RUSpam уверенность {ruspam_result.confidence:.3f} ({final_result.processing_time_ms:.1f}ms)"
                        )
                        return final_result

            elapsed_time = time.time() - start_time
            if elapsed_time >= self.max_processing_time:
                logger.warning(
                    f"[TIME] Превышен лимит времени ({elapsed_time:.2f}s), пропускаем BotHub"
                )
            else:
                ruspam_confidence = max_confidence if is_spam_detected else 0.0

                should_call_bothub = not is_spam_detected

                if should_call_bothub:
                    logger.info(f"[BOTHUB] Вызываем BotHub для проверки (RUSpam: не спам, уверенность: {ruspam_confidence:.3f})")
                    bothub_result = await self._check_bothub(message, user_context, text, ruspam_confidence)
                    if bothub_result:
                        results.append(bothub_result)
                        try:
                            import json
                            details_dict = json.loads(bothub_result.details) if bothub_result.details else {}
                            bothub_raw_confidence = details_dict.get("raw_confidence",
                                bothub_result.confidence if bothub_result.is_spam else (1.0 - bothub_result.confidence))
                        except (json.JSONDecodeError, ValueError):
                            bothub_raw_confidence = bothub_result.confidence if bothub_result.is_spam else (1.0 - bothub_result.confidence)
                        overall_confidence = max(overall_confidence, bothub_raw_confidence)
                        if bothub_result.is_spam:
                            is_spam_detected = True
                            primary_reason = DetectionReason.BOTHUB_DETECTED
                            max_confidence = max(max_confidence, bothub_result.confidence)
                else:
                    logger.debug(f"[BOTHUB] Пропускаем BotHub (RUSpam обнаружил спам: {ruspam_confidence:.3f})")

            notes = self._generate_notes(results, detected_language, is_spam_detected)

            final_result = self._create_final_result(
                message,
                results,
                is_spam_detected,
                primary_reason,
                overall_confidence,
                start_time,
                notes,
            )

            self._update_performance_metrics(final_result.processing_time_ms)

            result_emoji = "🚨" if is_spam_detected else "✅"
            logger.info(
                f"{result_emoji} Детекция завершена: spam={is_spam_detected}, confidence={overall_confidence:.3f}, время={final_result.processing_time_ms:.1f}ms"
            )

            return final_result

        except asyncio.TimeoutError:
            logger.error(f"[TIME] Timeout при детекции сообщения {message.id}")
            self._error_count += 1
            return self._create_timeout_result(message, results, start_time)
        except Exception as e:
            logger.error(f"[ERROR] Критическая ошибка в детекции: {e}")
            self._error_count += 1
            return self._create_error_result(message, results, start_time, str(e))

    async def _check_cas(
        self, message: Message, user_context: Dict[str, Any]
    ) -> Optional[DetectorResult]:
        """Проверка CAS базы с circuit breaker"""
        detector_name = "cas"

        if not self.cas_detector:
            return None

        if self._is_circuit_breaker_open(detector_name):
            logger.warning(f"[FAST] CAS circuit breaker открыт, пропускаем проверку")
            return None

        try:
            start_cas = time.time()
            cas_result = await asyncio.wait_for(
                self.cas_detector.detect(message, user_context), timeout=1.0
            )
            processing_time = (time.time() - start_cas) * 1000

            self._record_detector_success(detector_name)

            if cas_result.is_spam:
                logger.warning(
                    f"[ALERT] CAS: Пользователь {message.user_id} забанен ({processing_time:.1f}ms)"
                )
            else:
                logger.debug(f"[OK] CAS: Пользователь чист ({processing_time:.1f}ms)")

            return cas_result

        except asyncio.TimeoutError:
            logger.warning(f"[TIME] CAS timeout для пользователя {message.user_id}")
            self._record_detector_failure(detector_name, TimeoutError("CAS timeout"))
            return None
        except Exception as e:
            logger.error(f"[WARN] CAS ошибка: {e}")
            self._record_detector_failure(detector_name, e)
            return None

    async def _check_ruspam(self, text: str, language: str) -> Optional[DetectorResult]:
        """Проверка RUSpam BERT с circuit breaker"""
        detector_name = "ruspam"

        if not self.ruspam_detector or len(text.strip()) < self.ruspam_min_length:
            return None

        if self._is_circuit_breaker_open(detector_name):
            logger.warning(f"[FAST] RUSpam circuit breaker открыт, пропускаем проверку")
            return None

        try:
            start_ruspam = time.time()
            ruspam_result = await asyncio.wait_for(
                self.ruspam_detector.classify(text), timeout=2.0
            )
            processing_time = (time.time() - start_ruspam) * 1000

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
                    f"[ALERT] RUSpam: СПАМ обнаружен ({ruspam_result.confidence:.3f}, {processing_time:.1f}ms)"
                )
            else:
                logger.debug(
                    f"[OK] RUSpam: Сообщение чистое ({1.0 - ruspam_result.confidence:.3f}, {processing_time:.1f}ms)"
                )

            return detector_result

        except asyncio.TimeoutError:
            logger.warning(f"[TIME] RUSpam timeout")
            self._record_detector_failure(detector_name, TimeoutError("RUSpam timeout"))
            return None
        except Exception as e:
            logger.error(f"[WARN] RUSpam ошибка: {e}")
            self._record_detector_failure(detector_name, e)
            return DetectorResult(
                detector_name="RUSpam",
                is_spam=False,
                confidence=0.0,
                details=f"RUSpam error: {str(e)}",
                error=str(e),
                processing_time_ms=0.0,
            )

    def clear_bothub_cache_for_user(self, user_id: int):
        """Очистить кэш BotHub детекторов для конкретного пользователя"""
        keys_to_remove = []
        for cache_key in self._bothub_detectors_cache.keys():
            if f"user_{user_id}_" in cache_key:
                keys_to_remove.append(cache_key)

        for key in keys_to_remove:
            del self._bothub_detectors_cache[key]
            logger.info(f"[CACHE] Cleared BotHub cache for user {user_id}: {key}")

    def _get_or_create_bothub_detector(self, user_id: int, user_token: str, user_instructions: str = None, user_model: str = None):
        """Получить или создать BotHub детектор из кэша"""
        import time
        from ....adapter.gateway.bothub_gateway import BotHubGateway

        cache_key = f"user_{user_id}_{user_token[:10]}:{user_instructions or 'default'}:{user_model or 'default'}"

        current_time = time.time()

        if cache_key in self._bothub_detectors_cache:
            detector, last_used = self._bothub_detectors_cache[cache_key]
            if current_time - last_used < 300:
                self._bothub_detectors_cache[cache_key] = (detector, current_time)
                logger.debug(f"[CACHE] Using cached BotHub detector for user {user_id}")
                return detector
            else:
                del self._bothub_detectors_cache[cache_key]

        self.clear_bothub_cache_for_user(user_id)

        logger.info(f"[CACHE] Creating new BotHub detector for user {user_id}")
        user_bothub_gateway = BotHubGateway(
            user_token=user_token,
            user_instructions=user_instructions,
            user_model=user_model
        )
        user_bothub_detector = BotHubDetector(user_bothub_gateway)

        self._bothub_detectors_cache[cache_key] = (user_bothub_detector, current_time)

        keys_to_remove = []
        for key, (_, last_used) in self._bothub_detectors_cache.items():
            if current_time - last_used > 600:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._bothub_detectors_cache[key]
            logger.debug(f"[CACHE] Removed old BotHub detector from cache")

        return user_bothub_detector

    async def _check_bothub(
        self, message: Message, user_context: Dict[str, Any], text: str, ruspam_confidence: float = 0.0
    ) -> Optional[DetectorResult]:
        """Проверка BotHub LLM с circuit breaker"""
        detector_name = "bothub"

        if (
            not self.use_bothub_fallback
            or len(text.strip()) < self.bothub_min_length
        ):
            return None

        user_bothub_token = user_context.get("user_bothub_token") if user_context else None
        if not user_bothub_token:
            return None

        if self._is_circuit_breaker_open(detector_name):
            logger.warning(f"[FAST] BotHub circuit breaker открыт, пропускаем проверку")
            return None

        logger.info(f"[BOTHUB] Запускаем проверку (RUSpam уверенность: {ruspam_confidence:.3f}, длина текста: {len(text)})")

        try:
            user_id = user_context.get("user_id") if user_context else message.user_id
            user_bothub_detector = self._get_or_create_bothub_detector(
                user_id,
                user_bothub_token,
                user_context.get("user_system_prompt"),
                user_context.get("user_bothub_model")
            )

            start_bothub = time.time()
            bothub_result = await asyncio.wait_for(
                user_bothub_detector.detect(message, user_context), timeout=self.bothub_timeout
            )
            processing_time = (time.time() - start_bothub) * 1000

            self._record_detector_success(detector_name)

            user_id = message.user_id
            if user_id:
                try:
                    user_repository = user_context.get("user_repository") if user_context else None
                    if user_repository:
                        await user_repository.update_bothub_stats(user_id, processing_time / 1000)
                        logger.debug(f"[STATS] Updated BotHub stats for user {user_id}: +1 request, +{processing_time:.1f}ms")
                except Exception as e:
                    logger.warning(f"[WARN] Failed to update BotHub stats for user {user_id}: {e}")

            if bothub_result.is_spam:
                logger.warning(
                    f"[ALERT] BotHub: СПАМ обнаружен ({bothub_result.confidence:.3f}, {processing_time:.1f}ms)"
                )
            else:
                logger.debug(f"[OK] BotHub: Сообщение чистое ({processing_time:.1f}ms)")

            return bothub_result

        except asyncio.TimeoutError:
            logger.warning(f"[TIME] BotHub timeout")
            self._record_detector_failure(detector_name, TimeoutError("BotHub timeout"))

            user_id = message.user_id
            if user_id:
                try:
                    user_repository = user_context.get("user_repository") if user_context else None
                    if user_repository:
                        timeout_time = self.bothub_timeout
                        await user_repository.update_bothub_stats(user_id, timeout_time)
                        logger.debug(f"[STATS] Updated BotHub stats for user {user_id} (timeout): +1 request, +{timeout_time*1000:.1f}ms")
                except Exception as e:
                    logger.warning(f"[WARN] Failed to update BotHub stats for user {user_id} after timeout: {e}")
            return None
        except Exception as e:
            logger.error(f"[WARN] BotHub ошибка: {e}")
            self._record_detector_failure(detector_name, e)

            user_id = message.user_id
            if user_id:
                try:
                    user_repository = user_context.get("user_repository") if user_context else None
                    if user_repository:
                        error_time = 1.0
                        await user_repository.update_bothub_stats(user_id, error_time)
                        logger.debug(f"[STATS] Updated BotHub stats for user {user_id} (error): +1 request, +{error_time*1000:.1f}ms")
                except Exception as stats_error:
                    logger.warning(f"[WARN] Failed to update BotHub stats for user {user_id} after error: {stats_error}")

            return DetectorResult(
                detector_name="BotHub",
                is_spam=False,
                confidence=0.0,
                details=f"BotHub error: {str(e)}",
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

        should_ban = False
        should_delete = is_spam
        should_restrict = False
        should_warn = is_spam

        detection_reasons = []
        for result in results:
            if result.is_spam and result.details:
                detection_reasons.append(result.details)

        result = DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=is_spam,
            overall_confidence=confidence,
            primary_reason=primary_reason,
            detector_results=results,
            processing_time_ms=processing_time_ms,
            should_ban=should_ban,
            should_delete=should_delete,
            should_restrict=should_restrict,
            should_warn=should_warn,
        )

        result.metadata = {
            "notes": notes,
            "detection_reasons": detection_reasons,
            "recommended_action": "check_daily_counter",
        }

        return result

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

        if user_context and user_context.get("is_admin_or_owner", False):
            return "allow"

        effective_confidence = confidence

        if user_context and user_context.get("is_new_user", False):
            effective_confidence += 0.1

        previous_warnings = user_context.get("previous_warnings", 0) if user_context else 0
        if previous_warnings > 0:
            effective_confidence += 0.05 * previous_warnings

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

        result = DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=False,
            overall_confidence=0.0,
            primary_reason=DetectionReason.RUSPAM_CLEAN,
            detector_results=results,
            processing_time_ms=processing_time_ms,
            should_ban=False,
            should_delete=False,
            should_restrict=False,
            should_warn=False,
        )

        result.metadata = {
            "notes": f"Превышен лимит времени обработки ({processing_time_ms:.1f}ms)",
            "reasons": ["timeout"],
            "recommended_action": "allow",
        }

        return result

    def _create_error_result(
        self, message: Message, results: List[DetectorResult], start_time: float, error: str
    ) -> DetectionResult:
        """Создает результат при критической ошибке"""
        processing_time_ms = (time.time() - start_time) * 1000

        result = DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=False,
            overall_confidence=0.0,
            primary_reason=DetectionReason.RUSPAM_CLEAN,
            detector_results=results,
            processing_time_ms=processing_time_ms,
            should_ban=False,
            should_delete=False,
            should_restrict=False,
            should_warn=False,
        )

        result.metadata = {
            "notes": f"Ошибка детекции: {error}",
            "reasons": ["detection_error"],
            "recommended_action": "allow",
        }

        return result

    def _update_performance_metrics(self, processing_time_ms: float):
        """Обновляет метрики производительности"""
        self._total_processing_time += processing_time_ms

        if processing_time_ms > self.max_processing_time * 1000:
            logger.warning(
                f"[WARN] Медленная детекция: {processing_time_ms:.1f}ms (лимит: {self.max_processing_time * 1000}ms)"
            )

    async def get_available_detectors(self) -> List[str]:
        """Возвращает список доступных детекторов"""
        detectors = []

        if self.cas_detector:
            detectors.append("cas")
        if self.ruspam_detector:
            detectors.append("ruspam")

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
            "architecture": "modern",
            "detectors": {},
            "timestamp": time.time(),
            "performance": {
                "max_processing_time": self.max_processing_time,
                "early_exit_enabled": self.enable_early_exit,
                "circuit_breaker_enabled": self.circuit_breaker_enabled,
            },
        }

        detectors_status = []

        try:
            if self.cas_detector:
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

        try:
            if self.ruspam_detector:
                cb_state = self._circuit_breakers.get("ruspam", CircuitBreakerState())

                model_loaded = getattr(self.ruspam_detector, 'is_loaded', False)

                health["detectors"]["ruspam"] = {
                    "status": "degraded" if cb_state.is_open else ("healthy" if model_loaded else "error"),
                    "available": not cb_state.is_open and model_loaded,
                    "type": "bert_model",
                    "model_loaded": model_loaded,
                    "circuit_breaker": {
                        "is_open": cb_state.is_open,
                        "failure_count": cb_state.failure_count,
                    },
                }
                detectors_status.append(not cb_state.is_open and model_loaded)
            else:
                health["detectors"]["ruspam"] = {"status": "not_available", "available": False}
        except Exception as e:
            health["detectors"]["ruspam"] = {"status": "error", "error": str(e), "available": False}
            detectors_status.append(False)


        available_count = sum(1 for status in detectors_status if status)

        if available_count >= 2:
            health["status"] = "healthy"
        elif available_count >= 1:
            health["status"] = "degraded"
        else:
            health["status"] = "unhealthy"

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

        health["performance_stats"] = await self.get_performance_stats()

        return health
