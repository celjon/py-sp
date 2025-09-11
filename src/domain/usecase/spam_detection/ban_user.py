from typing import Protocol, List, Dict, Any

from ...entity.user import User, UserStatus
from ...entity.detection_result import DetectionResult


class UserRepository(Protocol):
    """Протокол репозитория пользователей"""
    async def get_user(self, telegram_id: int) -> User: ...
    async def update_user_status(self, telegram_id: int, status: UserStatus) -> None: ...


class MessageRepository(Protocol):
    """Протокол репозитория сообщений"""
    async def get_recent_messages(self, user_id: int, chat_id: int, limit: int = 10) -> List: ...
    async def mark_messages_deleted(self, message_ids: List[int]) -> None: ...


class TelegramGateway(Protocol):
    """Протокол шлюза для работы с Telegram API"""
    async def ban_user(self, chat_id: int, user_id: int, delete_messages: bool = True) -> bool: ...
    async def restrict_user(self, chat_id: int, user_id: int) -> bool: ...
    async def delete_message(self, chat_id: int, message_id: int) -> bool: ...


class BanUserUseCase:
    """Use case для бана пользователя"""
    
    def __init__(
        self,
        user_repo: UserRepository,
        message_repo: MessageRepository,
        telegram_gateway: TelegramGateway
    ):
        self.user_repo = user_repo
        self.message_repo = message_repo
        self.telegram_gateway = telegram_gateway
    
    async def execute(
        self,
        chat_id: int,
        user_id: int,
        detection_result: DetectionResult,
        ban_type: str = "permanent",
        aggressive_cleanup: bool = False
    ) -> Dict[str, Any]:
        """
        Выполняет бан или ограничение пользователя
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя
            detection_result: Результат детекции спама
            ban_type: Тип бана ("permanent", "restrict", "warn")
            aggressive_cleanup: Удалять ли все недавние сообщения пользователя
        
        Returns:
            Словарь с результатами операции
        """
        result = {
            "banned": False,
            "restricted": False,
            "warned": False,
            "messages_deleted": 0,
            "error": None
        }
        
        try:
            # Получаем пользователя
            user = await self.user_repo.get_user(user_id)
            if not user:
                result["error"] = "User not found"
                return result
            
            # Выполняем действие в зависимости от типа
            if ban_type == "permanent" or detection_result.should_ban:
                success = await self._ban_user(chat_id, user_id)
                if success:
                    result["banned"] = True
                    await self.user_repo.update_user_status(user_id, UserStatus.BANNED)
                else:
                    result["error"] = "Failed to ban user via Telegram API"
                    return result
            
            elif ban_type == "restrict" or detection_result.should_restrict:
                success = await self._restrict_user(chat_id, user_id)
                if success:
                    result["restricted"] = True
                    await self.user_repo.update_user_status(user_id, UserStatus.RESTRICTED)
                else:
                    result["error"] = "Failed to restrict user via Telegram API"
                    return result
            
            elif ban_type == "warn" or detection_result.should_warn:
                # Для предупреждения просто помечаем пользователя
                result["warned"] = True
                # Не меняем статус в базе данных для предупреждений
            
            # Удаляем сообщения если требуется
            if detection_result.should_delete:
                deleted_count = await self._delete_user_messages(
                    chat_id, user_id, aggressive_cleanup
                )
                result["messages_deleted"] = deleted_count
            
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    async def _ban_user(self, chat_id: int, user_id: int) -> bool:
        """Банит пользователя в чате"""
        return await self.telegram_gateway.ban_user(
            chat_id=chat_id,
            user_id=user_id,
            delete_messages=True
        )
    
    async def _restrict_user(self, chat_id: int, user_id: int) -> bool:
        """Ограничивает пользователя в чате"""
        return await self.telegram_gateway.restrict_user(
            chat_id=chat_id,
            user_id=user_id
        )
    
    async def _delete_user_messages(
        self, 
        chat_id: int, 
        user_id: int, 
        aggressive_cleanup: bool = False
    ) -> int:
        """
        Удаляет сообщения пользователя
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя
            aggressive_cleanup: Удалять ли все недавние сообщения (до 100)
        
        Returns:
            Количество удаленных сообщений
        """
        deleted_count = 0
        
        try:
            # Определяем количество сообщений для удаления
            limit = 100 if aggressive_cleanup else 10
            
            # Получаем недавние сообщения пользователя
            recent_messages = await self.message_repo.get_recent_messages(
                user_id=user_id,
                chat_id=chat_id,
                limit=limit
            )
            
            # Удаляем сообщения через Telegram API
            message_ids = []
            for msg in recent_messages:
                try:
                    success = await self.telegram_gateway.delete_message(
                        chat_id=chat_id,
                        message_id=msg.id
                    )
                    if success:
                        deleted_count += 1
                        message_ids.append(msg.id)
                except Exception as e:
                    print(f"Failed to delete message {msg.id}: {e}")
            
            # Помечаем сообщения как удаленные в базе данных
            if message_ids:
                await self.message_repo.mark_messages_deleted(message_ids)
            
        except Exception as e:
            print(f"Error deleting user messages: {e}")
        
        return deleted_count


