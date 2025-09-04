import asyncio
import time
from typing import List, Dict, Any, Optional

from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectionResult, DetectorResult, DetectionReason
from .heuristic import HeuristicDetector
from .cas import CASDetector
from .openai import OpenAIDetector
from .ruspam_simple import RUSpamSimpleClassifier
from .ml_classifier import MLClassifier


class EnsembleDetector:
    """
    Ансамблевый детектор, объединяющий результаты нескольких детекторов спама
    Архитектура: быстрые эвристики -> CAS -> RUSpam (для RU) -> ML -> OpenAI
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.detectors = []
        self.cas_detector = None
        self.openai_detector = None
        self.ml_detector = None
        self.ruspam_detector = None
        self.heuristic_detector = HeuristicDetector(self.config.get("heuristic", {}))
        
        # Флаги для контроля последовательности проверок
        self.openai_veto_mode = self.config.get("openai_veto", False)
        self.skip_ml_if_detected = self.config.get("skip_ml_if_detected", True)
        self.spam_threshold = self.config.get("spam_threshold", 0.6)
        self.high_confidence_threshold = self.config.get("high_confidence_threshold", 0.8)
        
        # Настройки RUSpam
        self.use_ruspam = self.config.get("use_ruspam", True)
        self.ruspam_min_length = self.config.get("ruspam_min_length", 10)
        self.russian_threshold = self.config.get("russian_threshold", 0.3)  # Доля кириллицы для определения русского
    
    def add_cas_detector(self, cas_gateway):
        """Добавляет CAS детектор"""
        self.cas_detector = CASDetector(cas_gateway)
    
    def add_openai_detector(self, openai_gateway):
        """Добавляет OpenAI детектор"""
        self.openai_detector = OpenAIDetector(openai_gateway)
    
    def add_ml_detector(self, model_path, config):
        """Добавляет ML детектор"""
        try:
            from pathlib import Path
            self.ml_detector = MLClassifier(Path(model_path), config)
            print(f"✅ ML классификатор инициализирован: {model_path}")
        except Exception as e:
            print(f"⚠️ ML классификатор не загружен: {e}")
            self.ml_detector = None
    
    def add_ruspam_detector(self):
        """Добавляет RUSpam детектор"""
        if self.use_ruspam:
            try:
                self.ruspam_detector = RUSpamSimpleClassifier()
                print("✅ RUSpam детектор инициализирован")
            except Exception as e:
                print(f"⚠️ RUSpam детектор не загружен: {e}")
                self.ruspam_detector = None
    
    def configure(self, config: Dict[str, Any]):
        """Конфигурирует ансамбль"""
        self.config.update(config)
        self.openai_veto_mode = config.get("openai_veto", self.openai_veto_mode)
        self.skip_ml_if_detected = config.get("skip_ml_if_detected", self.skip_ml_if_detected)
        self.spam_threshold = config.get("spam_threshold", self.spam_threshold)
        self.high_confidence_threshold = config.get("high_confidence_threshold", self.high_confidence_threshold)
        self.use_ruspam = config.get("use_ruspam", self.use_ruspam)
    
    def _detect_language(self, text: str) -> str:
        """Определяет язык текста (упрощенная версия)"""
        if not text:
            return "unknown"
        
        # Подсчитываем кириллицу
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
        Выполняет детекцию спама используя все доступные детекторы
        
        Последовательность:
        1. Быстрые эвристики (emoji, caps, links)
        2. CAS проверка (если новый пользователь)
        3. RUSpam (если русский текст и достаточная длина)
        4. ML классификатор (если предыдущие не обнаружили спам)
        5. OpenAI (в зависимости от режима)
        """
        start_time = time.time()
        results = []
        is_spam_detected = False
        primary_reason = None
        max_confidence = 0.0
        
        # Определяем язык сообщения
        detected_language = self._detect_language(message.text or "")
        
        # 1. Быстрые эвристические проверки
        context_user = User(
            telegram_id=message.user_id,
            message_count=(user_context or {}).get("message_count", 0),
            spam_score=(user_context or {}).get("spam_score", 0.0)
        )
        
        heuristic_result = await self.heuristic_detector.check_message(message, context_user)
        results.append(heuristic_result)
        
        if heuristic_result.is_spam:
            is_spam_detected = True
            primary_reason = self._get_primary_reason(heuristic_result.details)
            max_confidence = max(max_confidence, heuristic_result.confidence)
            print(f"🚨 Heuristic detection: {heuristic_result.details} (confidence: {heuristic_result.confidence:.3f})")
        
        # 2. CAS проверка (для новых пользователей или если еще не обнаружен спам)
        if self.cas_detector and (not is_spam_detected or user_context.get("is_new_user", False)):
            cas_result = await self.cas_detector.detect(message, user_context)
            results.append(cas_result)
            
            if cas_result.is_spam:
                is_spam_detected = True
                if primary_reason is None:
                    primary_reason = DetectionReason.CAS_BANNED
                max_confidence = max(max_confidence, cas_result.confidence)
                print(f"🚨 CAS detection: User {message.user_id} banned (confidence: {cas_result.confidence:.3f})")
        
        # 3. RUSpam проверка (для русского текста)
        if (self.ruspam_detector and 
            detected_language == "ru" and 
            len(message.text.strip()) >= self.ruspam_min_length and
            (not is_spam_detected or not self.skip_ml_if_detected)):
            
            try:
                ruspam_result = await self.ruspam_detector.classify(message.text)
                ruspam_detector_result = DetectorResult(
                    detector_name="RUSpam",
                    is_spam=ruspam_result.is_spam,
                    confidence=ruspam_result.confidence,
                    details=ruspam_result.details,
                    processing_time_ms=0.0
                )
                results.append(ruspam_detector_result)
                
                if ruspam_result.is_spam:
                    is_spam_detected = True
                    if primary_reason is None:
                        primary_reason = DetectionReason.CLASSIFIER
                    max_confidence = max(max_confidence, ruspam_result.confidence)
                    print(f"🚨 RUSpam detection: {ruspam_result.details} (confidence: {ruspam_result.confidence:.3f})")
                else:
                    print(f"✅ RUSpam: clean (confidence: {1.0 - ruspam_result.confidence:.3f})")
                    
            except Exception as e:
                print(f"⚠️ RUSpam error: {e}")
                # Добавляем результат с ошибкой, но не прерываем детекцию
                error_result = DetectorResult(
                    detector_name="RUSpam",
                    is_spam=False,
                    confidence=0.0,
                    details=f"RUSpam error: {str(e)}",
                    error=str(e)
                )
                results.append(error_result)
        
        # 4. ML классификатор (пропускаем если уже обнаружен спам и включен skip_ml_if_detected)
        if (self.ml_detector and 
            (not is_spam_detected or not self.skip_ml_if_detected) and
            len(message.text.strip()) >= 50):  # Минимальная длина для ML
            
            try:
                ml_result = await self.ml_detector.classify(message.text)
                ml_detector_result = DetectorResult(
                    detector_name="ML_Classifier",
                    is_spam=ml_result.is_spam,
                    confidence=ml_result.confidence,
                    details=ml_result.details,
                    processing_time_ms=0.0
                )
                results.append(ml_detector_result)
                
                if ml_result.is_spam:
                    is_spam_detected = True
                    if primary_reason is None:
                        primary_reason = DetectionReason.CLASSIFIER
                    max_confidence = max(max_confidence, ml_result.confidence)
                    print(f"🚨 ML detection: {ml_result.details} (confidence: {ml_result.confidence:.3f})")
                else:
                    print(f"✅ ML: clean (confidence: {1.0 - ml_result.confidence:.3f})")
                    
            except Exception as e:
                print(f"⚠️ ML classifier error: {e}")
                # Добавляем результат с ошибкой, но не прерываем детекцию
                error_result = DetectorResult(
                    detector_name="ML_Classifier",
                    is_spam=False,
                    confidence=0.0,
                    details=f"ML error: {str(e)}",
                    error=str(e)
                )
                results.append(error_result)
        
        # 5. OpenAI проверка (в зависимости от режима)
        if (self.openai_detector and 
            len(message.text.strip()) >= 10 and  # Минимальная длина для OpenAI
            user_context.get("is_new_user", False)):
            
            should_use_openai = False
            
            if self.openai_veto_mode:
                # В режиме veto используем OpenAI только если уже обнаружен спам
                should_use_openai = is_spam_detected
            else:
                # В обычном режиме используем OpenAI если спам НЕ обнаружен или для подтверждения
                should_use_openai = not is_spam_detected or max_confidence < 0.7
            
            if should_use_openai:
                try:
                    openai_result = await self.openai_detector.detect(message, user_context)
                    results.append(openai_result)
                    
                    if self.openai_veto_mode:
                        # В режиме veto OpenAI может "отменить" спам
                        if not openai_result.is_spam and is_spam_detected:
                            print(f"🔄 OpenAI veto: overriding spam detection (confidence: {openai_result.confidence:.3f})")
                            is_spam_detected = False
                            primary_reason = None
                            max_confidence = 0.0
                    else:
                        # В обычном режиме OpenAI может "добавить" спам
                        if openai_result.is_spam:
                            is_spam_detected = True
                            if primary_reason is None:
                                primary_reason = DetectionReason.OPENAI_DETECTED
                            max_confidence = max(max_confidence, openai_result.confidence)
                            print(f"🚨 OpenAI detection: {openai_result.details} (confidence: {openai_result.confidence:.3f})")
                        else:
                            print(f"✅ OpenAI: clean (confidence: {1.0 - openai_result.confidence:.3f})")
                            
                except Exception as e:
                    print(f"⚠️ OpenAI error: {e}")
                    # Добавляем результат с ошибкой, но не прерываем детекцию
                    error_result = DetectorResult(
                        detector_name="OpenAI",
                        is_spam=False,
                        confidence=0.0,
                        details=f"OpenAI error: {str(e)}",
                        error=str(e)
                    )
                    results.append(error_result)
        
        # Создаем итоговый результат детекции
        processing_time_ms = (time.time() - start_time) * 1000
        
        detection_result = DetectionResult(
            message_id=message.id,
            user_id=message.user_id,
            is_spam=is_spam_detected,
            overall_confidence=max_confidence,
            primary_reason=primary_reason or DetectionReason.CLASSIFIER,
            detector_results=results,
            processing_time_ms=processing_time_ms
        )
        
        # Определяем рекомендуемые действия
        detection_result.determine_actions(self.spam_threshold)
        
        # Дополнительные метаданные
        detection_result.metadata = {
            "detected_language": detected_language,
            "detectors_used": [r.detector_name for r in results],
            "user_context": user_context
        }
        
        return detection_result
    
    async def combine_results(self, detector_results: List[DetectorResult], message: Message, user: User) -> DetectionResult:
        """Объединить результаты всех детекторов в финальный результат (legacy метод)"""
        
        if not detector_results:
            return DetectionResult(
                message_id=message.id,
                user_id=message.user_id,
                is_spam=False,
                overall_confidence=0.0,
                primary_reason=DetectionReason.CLASSIFIER,
                detector_results=[]
            )
        
        # Анализируем результаты
        spam_results = [r for r in detector_results if r.is_spam]
        clean_results = [r for r in detector_results if not r.is_spam]
        
        # Определяем основной результат
        if spam_results:
            # Есть детекторы, обнаружившие спам
            highest_spam = max(spam_results, key=lambda x: x.confidence)
            
            # Определяем рекомендуемые действия
            should_ban = highest_spam.confidence >= self.high_confidence_threshold
            should_delete = highest_spam.confidence >= self.spam_threshold
            should_restrict = highest_spam.confidence >= self.spam_threshold and not should_ban
            
            return DetectionResult(
                message_id=message.id,
                user_id=message.user_id,
                is_spam=True,
                overall_confidence=highest_spam.confidence,
                primary_reason=self._get_primary_reason(highest_spam.details),
                detector_results=detector_results,
                should_ban=should_ban,
                should_delete=should_delete,
                should_restrict=should_restrict,
                should_warn=highest_spam.confidence < self.spam_threshold
            )
        else:
            # Все детекторы считают сообщение чистым
            avg_confidence = sum(r.confidence for r in clean_results) / len(clean_results) if clean_results else 0.0
            
            return DetectionResult(
                message_id=message.id,
                user_id=message.user_id,
                is_spam=False,
                overall_confidence=avg_confidence,
                primary_reason=DetectionReason.CLASSIFIER,
                detector_results=detector_results
            )
    
    def _get_primary_reason(self, details: str) -> DetectionReason:
        """Определяет основную причину детекции по деталям"""
        details_lower = details.lower()
        
        if "emoji" in details_lower:
            return DetectionReason.TOO_MANY_EMOJI
        elif "caps" in details_lower:
            return DetectionReason.TOO_MANY_LINKS  # Используем как общий эвристический
        elif "links" in details_lower:
            return DetectionReason.TOO_MANY_LINKS
        elif "mentions" in details_lower:
            return DetectionReason.TOO_MANY_MENTIONS
        elif "links only" in details_lower:
            return DetectionReason.LINKS_ONLY
        elif "repeated" in details_lower:
            return DetectionReason.ABNORMAL_SPACING
        elif "ruspam" in details_lower:
            return DetectionReason.CLASSIFIER
        elif "openai" in details_lower:
            return DetectionReason.OPENAI_DETECTED
        else:
            return DetectionReason.CLASSIFIER  # Общий случай
    
    async def get_available_detectors(self) -> List[str]:
        """Возвращает список доступных детекторов"""
        detectors = ["heuristic"]
        
        if self.cas_detector:
            detectors.append("cas")
        if self.ruspam_detector:
            detectors.append("ruspam")
        if self.ml_detector:
            detectors.append("ml_classifier")
        if self.openai_detector:
            detectors.append("openai")
            
        return detectors
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка состояния всех детекторов"""
        health = {
            "status": "healthy",
            "detectors": {},
            "timestamp": time.time()
        }
        
        # Проверяем каждый детектор
        detectors_status = []
        
        try:
            # Heuristic всегда доступен
            health["detectors"]["heuristic"] = {"status": "healthy", "available": True}
            detectors_status.append(True)
        except Exception as e:
            health["detectors"]["heuristic"] = {"status": "error", "error": str(e), "available": False}
            detectors_status.append(False)
        
        if self.cas_detector:
            try:
                # Простая проверка CAS (можно улучшить)
                health["detectors"]["cas"] = {"status": "healthy", "available": True}
                detectors_status.append(True)
            except Exception as e:
                health["detectors"]["cas"] = {"status": "error", "error": str(e), "available": False}
                detectors_status.append(False)
        
        if self.ruspam_detector:
            try:
                # Проверяем RUSpam на простом тексте
                test_result = await self.ruspam_detector.classify("тест")
                health["detectors"]["ruspam"] = {"status": "healthy", "available": True}
                detectors_status.append(True)
            except Exception as e:
                health["detectors"]["ruspam"] = {"status": "error", "error": str(e), "available": False}
                detectors_status.append(False)
        
        if self.ml_detector:
            try:
                # Проверяем ML на простом тексте
                test_result = await self.ml_detector.classify("test message")
                health["detectors"]["ml_classifier"] = {"status": "healthy", "available": True}
                detectors_status.append(True)
            except Exception as e:
                health["detectors"]["ml_classifier"] = {"status": "error", "error": str(e), "available": False}
                detectors_status.append(False)
        
        if self.openai_detector:
            try:
                health["detectors"]["openai"] = {"status": "healthy", "available": True}
                detectors_status.append(True)
            except Exception as e:
                health["detectors"]["openai"] = {"status": "error", "error": str(e), "available": False}
                detectors_status.append(False)
        
        # Определяем общий статус
        if all(detectors_status):
            health["status"] = "healthy"
        elif any(detectors_status):
            health["status"] = "degraded"
        else:
            health["status"] = "unhealthy"
        
        return health