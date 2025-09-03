from typing import Protocol, List
import time
from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectionResult, DetectorResult, DetectionReason
from ...service.detector.heuristic import HeuristicDetector
from ...service.detector.ml_classifier import MLClassifier
from ...service.detector.ensemble import EnsembleDetector

class MessageRepository(Protocol):
    async def save_message(self, message: Message) -> Message: ...
    async def get_user_message_count(self, user_id: int, chat_id: int) -> int: ...
    async def get_recent_messages(self, user_id: int, chat_id: int, limit: int = 10) -> List[Message]: ...

class UserRepository(Protocol):
    async def get_user(self, telegram_id: int) -> User | None: ...
    async def update_user_stats(self, user_id: int, message_count: int, spam_score: float) -> None: ...
    async def is_user_approved(self, telegram_id: int) -> bool: ...

class SpamDetectionGateway(Protocol):
    async def check_cas(self, user_id: int) -> bool: ...
    async def check_openai(self, text: str, user_context: dict = None) -> tuple[bool, float]: ...

class AdminNotificationService(Protocol):
    async def notify_spam_detected(self, message: Message, result: DetectionResult) -> None: ...

def create_check_message_usecase(
    message_repo: MessageRepository,
    user_repo: UserRepository,
    spam_gateway: SpamDetectionGateway,
    admin_notifier: AdminNotificationService,
    heuristic_detector: HeuristicDetector,
    ml_classifier: MLClassifier,
    ensemble_detector: EnsembleDetector,
    config: dict
):
    async def execute(message: Message) -> DetectionResult:
        start_time = time.time()
        
        # 1. Получаем информацию о пользователе
        user = await user_repo.get_user(message.user_id)
        if not user:
            # Новый пользователь - создаем базовую запись
            user = User(
                id=0,  # будет присвоен в БД
                telegram_id=message.user_id,
                message_count=0,
                spam_score=0.0
            )
        
        # 2. Проверяем список одобренных пользователей
        is_approved = await user_repo.is_user_approved(message.user_id)
        if is_approved:
            # Одобренные пользователи пропускают все проверки
            return DetectionResult(
                message_id=message.id or 0,
                user_id=message.user_id,
                is_spam=False,
                overall_confidence=0.0,
                primary_reason=DetectionReason.CLASSIFIER,  # Используем существующий reason
                detector_results=[]
            )
        
        detector_results: List[DetectorResult] = []
        
        # 3. Быстрые эвристические проверки (1-5ms)
        heuristic_result = await heuristic_detector.check_message(message, user)
        detector_results.append(heuristic_result)
        
        # Если эвристики сильно уверены в спаме - можно не вызывать остальные
        if heuristic_result.is_spam and heuristic_result.confidence > 0.9:
            return _build_final_result(message, detector_results)
        
        # 4. Внешние проверки (CAS)
        if user.is_new_user() or config.get("paranoid_mode", False):
            cas_start = time.time()
            is_cas_banned = await spam_gateway.check_cas(message.user_id)
            cas_time = (time.time() - cas_start) * 1000
            
            if is_cas_banned:
                detector_results.append(DetectorResult(
                    detector_name="CAS",
                    is_spam=True,
                    confidence=1.0,
                    details="User banned in CAS",
                    processing_time_ms=cas_time
                ))
                return _build_final_result(message, detector_results)
        
        # 5. ML классификация для длинных сообщений
        if len(message.text) >= config.get("min_message_length", 50):
            ml_start = time.time()
            ml_result = await ml_classifier.classify(message.text)
            ml_time = (time.time() - ml_start) * 1000
            
            detector_results.append(DetectorResult(
                detector_name="ML_Classifier",
                is_spam=ml_result.is_spam,
                confidence=ml_result.confidence,
                details=ml_result.details,
                processing_time_ms=ml_time
            ))
        
        # 6. OpenAI для сложных случаев (только если другие детекторы не уверены)
        needs_openai_check = (
            config.get("openai_enabled", False) and
            user.is_new_user() and
            len(message.text) >= config.get("min_message_length_openai", 30) and
            not any(r.is_spam and r.confidence > 0.8 for r in detector_results)
        )
        
        if needs_openai_check:
            openai_start = time.time()
            user_context = {
                "message_count": user.message_count,
                "spam_score": user.spam_score,
                "is_new_user": user.is_new_user()
            }
            
            is_openai_spam, openai_confidence = await spam_gateway.check_openai(
                message.text, 
                user_context
            )
            openai_time = (time.time() - openai_start) * 1000
            
            detector_results.append(DetectorResult(
                detector_name="OpenAI",
                is_spam=is_openai_spam,
                confidence=openai_confidence,
                details="OpenAI analysis",
                processing_time_ms=openai_time
            ))
        
        # 7. Ансамблевая оценка всех результатов
        ensemble_start = time.time()
        final_result = await ensemble_detector.combine_results(detector_results, message, user)
        ensemble_time = (time.time() - ensemble_start) * 1000
        
        # 8. Сохраняем сообщение и обновляем статистику пользователя
        message.is_spam = final_result.is_spam
        message.spam_confidence = final_result.overall_confidence
        await message_repo.save_message(message)
        
        # Обновляем статистику пользователя
        new_message_count = user.message_count + 1
        new_spam_score = _calculate_user_spam_score(user.spam_score, final_result.overall_confidence, new_message_count)
        await user_repo.update_user_stats(message.user_id, new_message_count, new_spam_score)
        
        # 9. Уведомляем администраторов если обнаружен спам
        if final_result.is_spam and config.get("admin_notifications", True):
            await admin_notifier.notify_spam_detected(message, final_result)
        
        total_time = (time.time() - start_time) * 1000
        print(f"Message check completed in {total_time:.2f}ms")
        
        return final_result
    
    def _build_final_result(message: Message, detector_results: List[DetectorResult]) -> DetectionResult:
        """Построить финальный результат на основе результатов детекторов"""
        spam_results = [r for r in detector_results if r.is_spam]
        
        if spam_results:
            highest_confidence = max(spam_results, key=lambda x: x.confidence)
            return DetectionResult(
                message_id=message.id or 0,
                user_id=message.user_id,
                is_spam=True,
                overall_confidence=highest_confidence.confidence,
                primary_reason=DetectionReason.CLASSIFIER,  # Используем существующий reason
                detector_results=detector_results,
                should_ban=highest_confidence.confidence > 0.8,
                should_delete=True,
                should_restrict=highest_confidence.confidence > 0.6
            )
        else:
            return DetectionResult(
                message_id=message.id or 0,
                user_id=message.user_id,
                is_spam=False,
                overall_confidence=0.0,
                primary_reason=DetectionReason.CLASSIFIER,  # Используем существующий reason
                detector_results=detector_results
            )
    
    def _calculate_user_spam_score(current_score: float, message_confidence: float, message_count: int) -> float:
        """Рассчитать обновленный spam score пользователя"""
        # Экспоненциально затухающее среднее
        alpha = 0.1  # коэффициент обучения
        return current_score * (1 - alpha) + message_confidence * alpha

    return execute

