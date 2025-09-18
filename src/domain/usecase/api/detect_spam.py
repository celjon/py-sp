import time
from typing import Protocol, Dict, Any, Optional
from dataclasses import dataclass
from ...entity.message import Message
from ...entity.detection_result import DetectionResult
from ...entity.client_usage import ApiUsageRecord, RequestStatus
from ...entity.api_key import ApiKey


@dataclass
class DetectionRequest:
    """Запрос на детекцию спама через публичный API"""

    text: str
    context: Dict[str, Any]

    # Метаданные запроса
    client_ip: str
    user_agent: Optional[str] = None
    request_size_bytes: int = 0


@dataclass
class DetectionResponse:
    """Ответ на запрос детекции спама"""

    is_spam: bool
    confidence: float
    reason: str
    action: str
    processing_time_ms: float

    # Дополнительная информация
    details: Optional[str] = None
    detected_patterns: Optional[list] = None

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь для JSON ответа"""
        result = {
            "is_spam": self.is_spam,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "action": self.action,
            "processing_time_ms": round(self.processing_time_ms, 2),
        }

        if self.details:
            result["details"] = self.details
        if self.detected_patterns:
            result["detected_patterns"] = self.detected_patterns

        return result


class SpamDetector(Protocol):
    """Протокол для детектора спама"""

    async def detect(
        self, message: Message, user_context: Dict[str, Any] = None
    ) -> DetectionResult: ...


class UsageRepository(Protocol):
    """Протокол репозитория для статистики использования"""

    async def record_api_usage(self, usage_record: ApiUsageRecord) -> ApiUsageRecord: ...


class ApiKeyRepository(Protocol):
    """Протокол репозитория API ключей"""

    async def update_last_used(self, api_key_id: int) -> None: ...


class DetectSpamUseCase:
    """Use case для детекции спама через публичный API"""

    def __init__(
        self,
        spam_detector: SpamDetector,
        usage_repo: UsageRepository,
        api_key_repo: ApiKeyRepository,
    ):
        self.spam_detector = spam_detector
        self.usage_repo = usage_repo
        self.api_key_repo = api_key_repo

    async def execute(self, api_key: ApiKey, request: DetectionRequest) -> DetectionResponse:
        """
        Выполняет детекцию спама для публичного API

        Args:
            api_key: API ключ клиента
            request: Запрос на детекцию

        Returns:
            Результат детекции
        """
        start_time = time.time()

        try:
            # Создаем доменное сообщение
            message = Message(
                user_id=request.context.get("user_id", 0),
                chat_id=request.context.get("chat_id", 0),
                text=request.text,
            )

            # Подготавливаем контекст для детектора
            user_context = {
                "is_new_user": request.context.get("is_new_user", False),
                "user_id": message.user_id,
                "chat_id": message.chat_id,
                "is_admin_or_owner": request.context.get("is_admin_or_owner", False),
                "language_hint": request.context.get("language", None),
                "previous_warnings": request.context.get("previous_warnings", 0),
            }

            # Выполняем детекцию
            detection_result = await self.spam_detector.detect(message, user_context)

            # Определяем рекомендуемое действие
            action = self._determine_action(detection_result)

            # Подготавливаем ответ
            processing_time_ms = (time.time() - start_time) * 1000

            response = DetectionResponse(
                is_spam=detection_result.is_spam,
                confidence=detection_result.overall_confidence,
                reason=(
                    detection_result.primary_reason.value
                    if detection_result.primary_reason
                    else "unknown"
                ),
                action=action,
                processing_time_ms=processing_time_ms,
                details=self._get_detection_details(detection_result),
                detected_patterns=self._get_detected_patterns(detection_result),
            )

            # Записываем использование API
            await self._record_usage(api_key, request, response, RequestStatus.SUCCESS)

            # Обновляем время последнего использования ключа
            await self.api_key_repo.update_last_used(api_key.id)

            return response

        except Exception as e:
            # В случае ошибки возвращаем безопасный результат
            processing_time_ms = (time.time() - start_time) * 1000

            error_response = DetectionResponse(
                is_spam=False,
                confidence=0.0,
                reason="error",
                action="allow",
                processing_time_ms=processing_time_ms,
                details=f"Detection error: {str(e)}",
            )

            # Записываем ошибку в статистику
            await self._record_usage(api_key, request, error_response, RequestStatus.ERROR)

            # Перебрасываем ошибку для обработки на уровне API
            raise Exception(f"Spam detection failed: {str(e)}")

    def _determine_action(self, detection_result: DetectionResult) -> str:
        """Определяет рекомендуемое действие на основе результата детекции"""
        if not detection_result.is_spam:
            return "allow"

        confidence = detection_result.overall_confidence

        if confidence >= 0.85:
            return "ban_and_delete"
        elif confidence >= 0.70:
            return "delete_and_warn"
        elif confidence >= 0.60:
            return "soft_warn_or_review"
        else:
            return "allow"

    def _get_detection_details(self, detection_result: DetectionResult) -> Optional[str]:
        """Формирует детали детекции для ответа"""
        if not detection_result.detector_results:
            return None

        details = []
        for detector_result in detection_result.detector_results:
            if detector_result.is_spam:
                details.append(f"{detector_result.detector_name}: {detector_result.details}")

        return "; ".join(details) if details else None

    def _get_detected_patterns(self, detection_result: DetectionResult) -> Optional[list]:
        """Извлекает обнаруженные паттерны спама (CAS + RUSpam + OpenAI)"""
        patterns = []

        for detector_result in detection_result.detector_results:
            if detector_result.is_spam and detector_result.detector_name == "cas":
                patterns.append("cas_banned_user")

            elif detector_result.is_spam and detector_result.detector_name == "RUSpam":
                patterns.append("ruspam_detected")

            elif detector_result.is_spam and detector_result.detector_name == "openai":
                patterns.append("ai_detected_spam")

        return patterns if patterns else None

    async def _record_usage(
        self,
        api_key: ApiKey,
        request: DetectionRequest,
        response: DetectionResponse,
        status: RequestStatus,
    ):
        """Записывает использование API в статистику"""
        try:
            usage_record = ApiUsageRecord(
                api_key_id=api_key.id,
                endpoint="/api/v1/detect",
                method="POST",
                status=status,
                client_ip=request.client_ip,
                user_agent=request.user_agent,
                request_size_bytes=request.request_size_bytes,
                response_size_bytes=len(str(response.to_dict())),  # Примерная оценка
                processing_time_ms=response.processing_time_ms,
                is_spam_detected=response.is_spam,
                detection_confidence=response.confidence,
                detection_reason=response.reason,
            )

            await self.usage_repo.record_api_usage(usage_record)

        except Exception as e:
            # Логируем ошибку записи статистики, но не прерываем основной процесс
            print(f"Failed to record API usage: {e}")


class BatchDetectSpamUseCase:
    """Use case для batch детекции спама"""

    def __init__(self, detect_spam_usecase: DetectSpamUseCase):
        self.detect_spam_usecase = detect_spam_usecase

    async def execute(
        self, api_key: ApiKey, requests: list[DetectionRequest], max_batch_size: int = 100
    ) -> list[DetectionResponse]:
        """
        Выполняет batch детекцию спама

        Args:
            api_key: API ключ клиента
            requests: Список запросов на детекцию
            max_batch_size: Максимальный размер batch

        Returns:
            Список результатов детекции
        """
        if len(requests) > max_batch_size:
            raise ValueError(f"Batch size {len(requests)} exceeds maximum {max_batch_size}")

        results = []

        # Обрабатываем запросы последовательно (можно распараллелить)
        for request in requests:
            try:
                result = await self.detect_spam_usecase.execute(api_key, request)
                results.append(result)
            except Exception as e:
                # Для batch запросов возвращаем ошибку как часть результата
                error_result = DetectionResponse(
                    is_spam=False,
                    confidence=0.0,
                    reason="error",
                    action="allow",
                    processing_time_ms=0.0,
                    details=f"Error: {str(e)}",
                )
                results.append(error_result)

        return results
