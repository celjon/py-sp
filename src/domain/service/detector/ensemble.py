"""
Современный ансамблевый детектор спама для production
Архитектура: CAS → RUSpam → OpenAI (без устаревших эвристик и ML)
"""
import asyncio
import time
from typing import List, Dict, Any, Optional

from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectionResult, DetectorResult, DetectionReason
from .cas import CASDetector
from .openai import OpenAIDetector
from .ruspam_simple import RUSpamSimpleClassifier


class EnsembleDetector:
    """
    Production-ready ансамблевый детектор спама
    
    Архитектура (3 слоя с ранним выходом):
    1. 🛡️ CAS - мгновенная проверка базы забаненных
    2. 🤖 RUSpam - BERT модель для спам-детекции  
    3. 🧠 OpenAI - LLM анализ сложных случаев
    
    Преимущества:
    - Высокая точность без ложных срабатываний
    - Масштабируемость и производительность
    - Адаптивность к новым типам спама
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # Детекторы (lazy initialization)
        self.cas_detector: Optional[CASDetector] = None
        self.openai_detector: Optional[OpenAIDetector] = None
        self.ruspam_detector: Optional[RUSpamSimpleClassifier] = None
        
        # Основные пороги
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
        
        # Производительность
        self.max_processing_time = self.config.get("max_processing_time", 2.0)  # 2 секунды лимит
        self.enable_early_exit = self.config.get("enable_early_exit", True)
        
        print("🎯 Production ансамбль инициализирован: CAS + RUSpam + OpenAI")
    
    def add_cas_detector(self, cas_gateway) -> None:
        """Добавляет CAS детектор"""
        self.cas_detector = CASDetector(cas_gateway)
        print("✅ CAS детектор добавлен")
    
    def add_openai_detector(self, openai_gateway) -> None:
        """Добавляет OpenAI детектор"""
        self.openai_detector = OpenAIDetector(openai_gateway)
        print("✅ OpenAI детектор добавлен")
    
    def add_ruspam_detector(self) -> None:
        """Добавляет RUSpam BERT детектор"""
        if not self.use_ruspam:
            print("⚠️ RUSpam отключен в конфигурации")
            return
            
        try:
            self.ruspam_detector = RUSpamSimpleClassifier()
            print("✅ RUSpam BERT детектор инициализирован")
        except ImportError as e:
            print(f"⚠️ RUSpam dependencies не найдены: {e}")
            print("💡 Установите: pip install torch transformers ruSpam")
            self.ruspam_detector = None
        except Exception as e:
            print(f"⚠️ RUSpam не загружен: {e}")
            self.ruspam_detector = None
    
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
        cyrillic_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
        latin_chars = sum(1 for c in text if c.isalpha() and not ('\u0400' <= c <= '\u04FF'))
        
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
    
    async def detect(self, message: Message, user_context: Dict[str, Any] = None) -> DetectionResult:
        """
        Основной метод детекции спама
        
        Production логика:
        1. 🛡️ CAS проверка (0.1с) - если забанен → мгновенный бан
        2. 🤖 RUSpam BERT (0.3с) - если спам ≥0.8 → ранний выход  
        3. 🧠 OpenAI LLM (1.5с) - контекстуальный анализ
        
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
        
        print(f"🔍 Анализ: '{text[:50]}{'...' if len(text) > 50 else ''}' (язык: {detected_language})")
        
        try:
            # === СЛОЙ 1: CAS СИСТЕМА (критический путь) ===
            cas_result = await self._check_cas(message, user_context)
            if cas_result:
                results.append(cas_result)
                if cas_result.is_spam:
                    # CAS бан абсолютен - мгновенный выход
                    return self._create_final_result(
                        message, results, True, DetectionReason.CAS_BANNED,
                        1.0, start_time, "Пользователь забанен в CAS базе"
                    )
            
            # === СЛОЙ 2: RUSPAM BERT ===
            ruspam_result = await self._check_ruspam(text, detected_language)
            if ruspam_result:
                results.append(ruspam_result)
                if ruspam_result.is_spam:
                    is_spam_detected = True
                    primary_reason = DetectionReason.CLASSIFIER
                    max_confidence = ruspam_result.confidence
                    
                    # Ранний выход при высокой уверенности
                    if (self.enable_early_exit and 
                        ruspam_result.confidence >= self.high_confidence_threshold):
                        
                        return self._create_final_result(
                            message, results, True, primary_reason,
                            max_confidence, start_time, 
                            f"RUSpam высокая уверенность: {ruspam_result.details}"
                        )
            
            # === СЛОЙ 3: OPENAI LLM ===
            # Проверяем таймаут
            if time.time() - start_time >= self.max_processing_time:
                print(f"⏰ Превышен лимит времени, пропускаем OpenAI")
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
            
            return self._create_final_result(
                message, results, is_spam_detected, primary_reason,
                max_confidence, start_time, notes
            )
            
        except asyncio.TimeoutError:
            print(f"⏰ Timeout при детекции сообщения {message.id}")
            return self._create_timeout_result(message, results, start_time)
        except Exception as e:
            print(f"❌ Критическая ошибка в детекции: {e}")
            return self._create_error_result(message, results, start_time, str(e))
    
    async def _check_cas(self, message: Message, user_context: Dict[str, Any]) -> Optional[DetectorResult]:
        """Проверка CAS базы"""
        if not self.cas_detector:
            return None
            
        try:
            start_cas = time.time()
            cas_result = await asyncio.wait_for(
                self.cas_detector.detect(message, user_context),
                timeout=1.0  # 1 секунда на CAS
            )
            processing_time = (time.time() - start_cas) * 1000
            
            if cas_result.is_spam:
                print(f"🚨 CAS: Пользователь {message.user_id} забанен ({processing_time:.1f}ms)")
            else:
                print(f"✅ CAS: Пользователь чист ({processing_time:.1f}ms)")
            
            return cas_result
            
        except asyncio.TimeoutError:
            print(f"⏰ CAS timeout для пользователя {message.user_id}")
            return None
        except Exception as e:
            print(f"⚠️ CAS ошибка: {e}")
            return None
    
    async def _check_ruspam(self, text: str, language: str) -> Optional[DetectorResult]:
        """Проверка RUSpam BERT"""
        if (not self.ruspam_detector or 
            len(text.strip()) < self.ruspam_min_length):
            return None
        
        try:
            start_ruspam = time.time()
            ruspam_result = await asyncio.wait_for(
                self.ruspam_detector.classify(text),
                timeout=2.0  # 2 секунды на RUSpam
            )
            processing_time = (time.time() - start_ruspam) * 1000
            
            detector_result = DetectorResult(
                detector_name="RUSpam",
                is_spam=ruspam_result.is_spam,
                confidence=ruspam_result.confidence,
                details=ruspam_result.details,
                processing_time_ms=processing_time
            )
            
            if ruspam_result.is_spam:
                print(f"🚨 RUSpam: СПАМ обнаружен ({ruspam_result.confidence:.3f}, {processing_time:.1f}ms)")
            else:
                print(f"✅ RUSpam: Сообщение чистое ({1.0 - ruspam_result.confidence:.3f}, {processing_time:.1f}ms)")
            
            return detector_result
            
        except asyncio.TimeoutError:
            print(f"⏰ RUSpam timeout")
            return None
        except Exception as e:
            print(f"⚠️ RUSpam ошибка: {e}")
            return DetectorResult(
                detector_name="RUSpam",
                is_spam=False,
                confidence=0.0,
                details=f"RUSpam error: {str(e)}",
                error=str(e),
                processing_time_ms=0.0
            )
    
    async def _check_openai(self, message: Message, user_context: Dict[str, Any], text: str) -> Optional[DetectorResult]:
        """Проверка OpenAI LLM"""
        if (not self.openai_detector or 
            not self.use_openai_fallback or
            len(text.strip()) < self.openai_min_length):
            return None
        
        try:
            start_openai = time.time()
            openai_result = await asyncio.wait_for(
                self.openai_detector.detect(message, user_context),
                timeout=self.openai_timeout
            )
            processing_time = (time.time() - start_openai) * 1000
            
            if openai_result.is_spam:
                print(f"🚨 OpenAI: СПАМ обнаружен ({openai_result.confidence:.3f}, {processing_time:.1f}ms)")
            else:
                print(f"✅ OpenAI: Сообщение чистое ({processing_time:.1f}ms)")
            
            return openai_result
            
        except asyncio.TimeoutError:
            print(f"⏰ OpenAI timeout")
            return None
        except Exception as e:
            print(f"⚠️ OpenAI ошибка: {e}")
            return DetectorResult(
                detector_name="OpenAI",
                is_spam=False,
                confidence=0.0,
                details=f"OpenAI error: {str(e)}",
                error=str(e),
                processing_time_ms=0.0
            )
    
    def _create_final_result(
        self, 
        message: Message, 
        results: List[DetectorResult],
        is_spam: bool, 
        primary_reason: Optional[DetectionReason],
        confidence: float, 
        start_time: float, 
        notes: str
    ) -> DetectionResult:
        """Создает финальный результат детекции"""
        
        processing_time_ms = (time.time() - start_time) * 1000
        
        # Определяем рекомендуемые действия
        action = self._determine_action(confidence, is_spam)
        should_ban = action == "ban_and_delete"
        should_delete = action in ["ban_and_delete", "delete_and_warn"]
        should_restrict = action == "soft_warn_or_review"
        should_warn = action in ["delete_and_warn", "soft_warn_or_review"]
        
        return DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=is_spam,
            overall_confidence=confidence,
            primary_reason=primary_reason,
            detector_results=results,
            processing_time_ms=processing_time_ms,
            notes=notes,
            recommended_action=action,
            should_ban=should_ban,
            should_delete=should_delete,
            should_restrict=should_restrict,
            should_warn=should_warn
        )
    
    def _determine_action(self, confidence: float, is_spam: bool) -> str:
        """
        Определяет рекомендуемое действие на основе уверенности
        
        Production пороги:
        - ≥0.85: ban_and_delete (автобан)
        - 0.70-0.85: delete_and_warn (удалить + предупреждение)  
        - 0.60-0.70: soft_warn_or_review (мягкое предупреждение)
        - <0.60: allow (разрешить)
        """
        if not is_spam:
            return "allow"
        
        if confidence >= self.auto_ban_threshold:
            return "ban_and_delete"
        elif confidence >= 0.70:
            return "delete_and_warn"
        elif confidence >= self.spam_threshold:
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
    
    def _create_timeout_result(self, message: Message, results: List[DetectorResult], start_time: float) -> DetectionResult:
        """Создает результат при превышении таймаута"""
        return DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=False,  # При таймауте не блокируем
            overall_confidence=0.0,
            primary_reason=None,
            detector_results=results,
            processing_time_ms=(time.time() - start_time) * 1000,
            notes="Превышен лимит времени обработки",
            recommended_action="allow",
            should_ban=False,
            should_delete=False,
            should_restrict=False,
            should_warn=False
        )
    
    def _create_error_result(self, message: Message, results: List[DetectorResult], start_time: float, error: str) -> DetectionResult:
        """Создает результат при критической ошибке"""
        return DetectionResult(
            message_id=message.id or 0,
            user_id=message.user_id,
            is_spam=False,  # При ошибке не блокируем
            overall_confidence=0.0,
            primary_reason=None,
            detector_results=results,
            processing_time_ms=(time.time() - start_time) * 1000,
            notes=f"Ошибка детекции: {error}",
            recommended_action="allow",
            should_ban=False,
            should_delete=False,
            should_restrict=False,
            should_warn=False
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
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка состояния всех детекторов
        
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
                "early_exit_enabled": self.enable_early_exit
            }
        }
        
        detectors_status = []
        
        # CAS детектор
        try:
            if self.cas_detector:
                health["detectors"]["cas"] = {
                    "status": "healthy", 
                    "available": True,
                    "type": "user_database"
                }
                detectors_status.append(True)
            else:
                health["detectors"]["cas"] = {
                    "status": "not_configured", 
                    "available": False
                }
        except Exception as e:
            health["detectors"]["cas"] = {
                "status": "error", 
                "error": str(e), 
                "available": False
            }
            detectors_status.append(False)
        
        # RUSpam детектор
        try:
            if self.ruspam_detector:
                # Быстрый тест
                test_result = await asyncio.wait_for(
                    self.ruspam_detector.classify("тест"),
                    timeout=2.0
                )
                health["detectors"]["ruspam"] = {
                    "status": "healthy", 
                    "available": True,
                    "type": "bert_model"
                }
                detectors_status.append(True)
            else:
                health["detectors"]["ruspam"] = {
                    "status": "not_available", 
                    "available": False
                }
        except Exception as e:
            health["detectors"]["ruspam"] = {
                "status": "error", 
                "error": str(e), 
                "available": False
            }
            detectors_status.append(False)
        
        # OpenAI детектор
        try:
            if self.openai_detector:
                health["detectors"]["openai"] = {
                    "status": "healthy", 
                    "available": True,
                    "type": "llm_model"
                }
                detectors_status.append(True)
            else:
                health["detectors"]["openai"] = {
                    "status": "not_configured", 
                    "available": False
                }
        except Exception as e:
            health["detectors"]["openai"] = {
                "status": "error", 
                "error": str(e), 
                "available": False
            }
            detectors_status.append(False)
        
        # Определяем общий статус
        if all(detectors_status) and len(detectors_status) >= 2:
            health["status"] = "healthy"
        elif any(detectors_status):
            health["status"] = "degraded" 
        else:
            health["status"] = "unhealthy"
        
        # Добавляем рекомендации
        if health["status"] != "healthy":
            health["recommendations"] = []
            if not any(d.get("available", False) for d in health["detectors"].values()):
                health["recommendations"].append("Настройте хотя бы один детектор")
            if "cas" not in health["detectors"] or not health["detectors"]["cas"].get("available"):
                health["recommendations"].append("Настройте CAS для защиты от известных спамеров")
            if "ruspam" not in health["detectors"] or not health["detectors"]["ruspam"].get("available"):
                health["recommendations"].append("Установите RUSpam для BERT анализа")
        
        return health