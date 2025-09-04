import asyncio
import time
from typing import List, Dict, Any, Optional

from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectionResult, DetectorResult, DetectionReason
from .heuristic import HeuristicDetector
from .cas import CASDetector
from .openai import OpenAIDetector


class EnsembleDetector:
    """
    Ансамблевый детектор, объединяющий результаты нескольких детекторов спама
    Архитектура: быстрые эвристики -> CAS -> ML -> OpenAI
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.detectors = []
        self.cas_detector = None
        self.openai_detector = None
        self.ml_detector = None
        self.heuristic_detector = HeuristicDetector()
        
        # Флаги для контроля последовательности проверок
        self.openai_veto_mode = self.config.get("openai_veto", False)
        self.skip_ml_if_detected = self.config.get("skip_ml_if_detected", True)
        self.spam_threshold = self.config.get("spam_threshold", 0.6)
        self.high_confidence_threshold = self.config.get("high_confidence_threshold", 0.8)
    
    def add_cas_detector(self, cas_gateway):
        """Добавляет CAS детектор"""
        self.cas_detector = CASDetector(cas_gateway)
    
    def add_openai_detector(self, openai_gateway):
        """Добавляет OpenAI детектор"""
        self.openai_detector = OpenAIDetector(openai_gateway)
    
    def add_ml_detector(self, detector):
        """Добавляет ML детектор"""
        self.ml_detector = detector
    
    def configure(self, config: Dict[str, Any]):
        """Конфигурирует ансамбль"""
        self.config.update(config)
        self.openai_veto_mode = config.get("openai_veto", False)
        self.skip_ml_if_detected = config.get("skip_ml_if_detected", True)
        self.spam_threshold = config.get("spam_threshold", self.spam_threshold)
        self.high_confidence_threshold = config.get("high_confidence_threshold", self.high_confidence_threshold)
    
    async def detect(self, message: Message, user_context: Dict[str, Any] = None) -> DetectionResult:
        """
        Выполняет детекцию спама используя все доступные детекторы
        
        Последовательность:
        1. Быстрые эвристики (emoji, caps, links)
        2. CAS проверка (если новый пользователь)
        3. ML классификатор (если предыдущие не обнаружили спам)
        4. OpenAI (в зависимости от режима)
        """
        start_time = time.time()
        results = []
        is_spam_detected = False
        primary_reason = None
        max_confidence = 0.0
        
        # 1. Быстрые эвристические проверки
        # Преобразуем контекст в User для согласованности интерфейсов
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
        
        # 2. CAS проверка (для новых пользователей или если еще не обнаружен спам)
        if self.cas_detector and (not is_spam_detected or user_context.get("is_new_user", False)):
            cas_result = await self.cas_detector.detect(message, user_context)
            results.append(cas_result)
            
            if cas_result.is_spam:
                is_spam_detected = True
                if primary_reason is None:
                    primary_reason = DetectionReason.CAS_BANNED
                max_confidence = max(max_confidence, cas_result.confidence)
        
        # 3. ML классификатор (пропускаем если уже обнаружен спам и включен skip_ml_if_detected)
        if self.ml_detector and (not is_spam_detected or not self.skip_ml_if_detected):
            # Пропускаем ML для коротких сообщений
            if len(message.text.strip()) >= 50:  # min_msg_len как в tg-spam
                ml_result = await self.ml_detector.classify(message.text)
                results.append(DetectorResult(
                    detector_name="ML_Classifier",
                    is_spam=ml_result.is_spam,
                    confidence=ml_result.confidence,
                    details=ml_result.details,
                    processing_time_ms=0.0
                ))
                
                if ml_result.is_spam:
                    is_spam_detected = True
                    if primary_reason is None:
                        primary_reason = DetectionReason.CLASSIFIER
                    max_confidence = max(max_confidence, ml_result.confidence)
        
        # 4. OpenAI проверка (в зависимости от режима)
        if self.openai_detector and user_context.get("is_new_user", False):
            should_use_openai = False
            
            if self.openai_veto_mode:
                # В режиме veto используем OpenAI только если уже обнаружен спам
                should_use_openai = is_spam_detected
            else:
                # В обычном режиме используем OpenAI если спам НЕ обнаружен
                should_use_openai = not is_spam_detected
            
            if should_use_openai:
                openai_result = await self.openai_detector.detect(message, user_context)
                results.append(openai_result)
                
                if self.openai_veto_mode:
                    # В режиме veto OpenAI может "отменить" спам
                    if not openai_result.is_spam:
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
        
        # Создаем итоговый результат детекции
        detection_result = DetectionResult(
            message_id=message.id,
            user_id=message.user_id,
            is_spam=is_spam_detected,
            overall_confidence=max_confidence,
            primary_reason=primary_reason or DetectionReason.CLASSIFIER,
            detector_results=results,
            processing_time_ms=(time.time() - start_time) * 1000
        )
        
        return detection_result
    
    async def combine_results(self, detector_results: List[DetectorResult], message: Message, user: User) -> DetectionResult:
        """Объединить результаты всех детекторов в финальный результат"""
        
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
        else:
            return DetectionReason.CLASSIFIER  # Общий случай
    
    async def get_available_detectors(self) -> List[str]:
        """Возвращает список доступных детекторов"""
        detectors = ["heuristic"]
        
        if self.cas_detector:
            detectors.append("cas")
        if self.ml_detector:
            detectors.append("ml_classifier")
        if self.openai_detector:
            detectors.append("openai")
            
        return detectors
