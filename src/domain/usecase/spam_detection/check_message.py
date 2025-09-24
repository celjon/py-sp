from typing import Protocol, List
import time
from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectionResult
from ...service.detector.ensemble import EnsembleDetector
from ....adapter.gateway.bothub_gateway import BotHubGateway
from ...service.detector.bothub import BotHubDetector


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

    async def execute(self, message: Message) -> DetectionResult:
        start_time = time.time()

        # Пользователь и контекст
        user = await self.user_repo.get_user(message.user_id)
        if not user:
            # Создаем нового пользователя в БД при первом сообщении
            user = await self.user_repo.create_user(
                telegram_id=message.user_id,
                username=message.username,
                first_name=message.first_name,
                last_name=message.last_name
            )

        if await self.user_repo.is_user_approved(message.user_id):
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

        user_context = {
            "message_count": user.message_count,
            "spam_score": user.spam_score,
            "is_new_user": (
                user.is_new_user if hasattr(user, "is_new_user") else user.message_count == 0
            ),
            "chat_id": getattr(message, "chat_id", None),
        }

        # Настраиваем BotHub детектор если у пользователя есть токен
        if user.bothub_token and user.bothub_configured:
            try:
                # Создаем BotHub Gateway с токеном пользователя
                bothub_gateway = BotHubGateway(
                    user_token=user.bothub_token,
                    system_prompt=user.system_prompt
                )
                
                # Создаем BotHub детектор
                bothub_detector = BotHubDetector(bothub_gateway)
                
                # Добавляем в ensemble детектор
                self.spam_detector.add_bothub_detector(bothub_gateway)
            except Exception as e:
                # Если не удалось настроить BotHub, продолжаем без него
                pass

        # Ансамблевая детекция
        result = await self.spam_detector.detect(message, user_context)

        # Сохранение и обновление статистики
        await self._persist(message, user, result)

        total_time_ms = (time.time() - start_time) * 1000
        print(f"Message check completed in {total_time_ms:.2f}ms")
        return result

    async def _persist(self, message: Message, user: User, result: DetectionResult) -> None:
        message.is_spam = result.is_spam
        message.spam_confidence = result.overall_confidence
        await self.message_repo.save_message(message)

        new_message_count = user.message_count + 1
        new_spam_score = self._ema(user.spam_score, result.overall_confidence, 0.1)
        await self.user_repo.update_user_stats(message.user_id, new_message_count, new_spam_score)
        
        # Если сообщение определено как спам, увеличиваем счетчик
        if result.is_spam:
            daily_spam_count = await self.user_repo.increment_spam_count(message.user_id)
            print(f"🚨 Spam detected! User {message.user_id} spam count: {daily_spam_count}")
            
            # Проверяем, нужно ли банить пользователя
            if daily_spam_count >= self.max_daily_spam:
                print(f"🔨 User {message.user_id} should be banned for {daily_spam_count} spam messages today")
                # Устанавливаем флаги для бана
                result.should_ban = True
                result.should_delete = True

    def _ema(self, current_value: float, new_value: float, alpha: float) -> float:
        return current_value * (1 - alpha) + new_value * alpha
