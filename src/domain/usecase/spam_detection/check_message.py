from typing import Protocol, List
import time
import logging
from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectionResult
from ...service.detector.ensemble import EnsembleDetector
from ....adapter.gateway.bothub_gateway import BotHubGateway
from ...service.detector.bothub import BotHubDetector

logger = logging.getLogger(__name__)


class MessageRepository(Protocol):
    async def save_message(self, message: Message) -> Message: ...


class UserRepository(Protocol):
    async def get_user(self, telegram_id: int) -> User | None: ...
    async def update_user_stats(
        self, user_id: int, message_count: int, spam_score: float
    ) -> None: ...
    async def is_user_approved(self, telegram_id: int) -> bool: ...


class CheckMessageUseCase:
    """Use case для проверки сообщений на спам"""

    def __init__(
        self,
        message_repo: MessageRepository,
        user_repo: UserRepository,
        spam_detector: EnsembleDetector,
        spam_threshold: float = 0.6,
        max_daily_spam: int = 3,
    ):
        self.message_repo = message_repo
        self.user_repo = user_repo
        self.spam_detector = spam_detector
        self.spam_threshold = spam_threshold
        self.max_daily_spam = max_daily_spam

    async def execute(self, message: Message, chat=None) -> DetectionResult:
        start_time = time.time()

        user = await self.user_repo.get_user(message.user_id)
        if not user:
            user = await self.user_repo.create_user(
                telegram_id=message.user_id,
                username=message.username,
                first_name=message.first_name,
                last_name=message.last_name
            )

        if await self.user_repo.is_user_approved(message.user_id, message.chat_id):
            logger.info(f"⭐ User {message.user_id} is in whitelist (approved_users) - skipping spam detection")
            result = DetectionResult(
                message_id=message.id or 0,
                user_id=message.user_id,
                is_spam=False,
                overall_confidence=0.0,
                primary_reason=None,
                detector_results=[],
            )
            await self._persist(message, user, result)
            return result

        effective_spam_threshold = self.spam_threshold
        if chat and hasattr(chat, 'spam_threshold'):
            effective_spam_threshold = chat.spam_threshold

        system_prompt = None
        if chat and chat.system_prompt:
            system_prompt = chat.system_prompt
        elif user.bothub_configured and user.system_prompt:
            system_prompt = user.system_prompt

        user_context = {
            "message_count": user.message_count,
            "spam_score": user.spam_score,
            "is_new_user": (
                user.is_new_user if hasattr(user, "is_new_user") else user.message_count == 0
            ),
            "chat_id": getattr(message, "chat_id", None),
            "user_bothub_token": user.bothub_token if user.bothub_configured else None,
            "user_system_prompt": system_prompt,
            "user_bothub_model": user.bothub_model if user.bothub_configured else None,
            "spam_threshold": effective_spam_threshold,
            "user_repository": self.user_repo,
        }

        result = await self.spam_detector.detect(message, user_context)

        original_is_spam = result.is_spam
        result.is_spam = result.overall_confidence >= effective_spam_threshold

        result.should_delete = result.is_spam
        result.should_warn = result.is_spam

        if original_is_spam != result.is_spam:
            pass

        await self._persist(message, user, result)

        total_time_ms = (time.time() - start_time) * 1000
        return result

    async def _persist(self, message: Message, user: User, result: DetectionResult) -> None:
        message.is_spam = result.is_spam
        message.spam_confidence = result.overall_confidence
        await self.message_repo.save_message(message)

        new_message_count = user.message_count + 1
        new_spam_score = self._ema(user.spam_score, result.overall_confidence, 0.1)
        await self.user_repo.update_user_stats(message.user_id, new_message_count, new_spam_score)
        
        if result.is_spam:
            daily_spam_count = await self.user_repo.increment_spam_count(message.user_id)

            if daily_spam_count >= self.max_daily_spam:
                result.should_ban = True
                result.should_delete = True

    def _ema(self, current_value: float, new_value: float, alpha: float) -> float:
        return current_value * (1 - alpha) + new_value * alpha
