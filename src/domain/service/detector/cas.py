from typing import Dict, Any

from ...entity.message import Message
from ...entity.detection_result import DetectorResult


class CASDetector:
    """Детектор спама на основе CAS (Combot Anti-Spam) API"""
    
    def __init__(self, cas_gateway):
        """
        Args:
            cas_gateway: Шлюз для работы с CAS API
        """
        self.cas_gateway = cas_gateway
    
    async def detect(self, message: Message, user_context: Dict[str, Any] = None) -> DetectorResult:
        """
        Проверяет пользователя в базе CAS
        
        Args:
            message: Сообщение для проверки
            user_context: Контекст пользователя
            
        Returns:
            Результат детекции
        """
        try:
            # Проверяем пользователя в CAS
            is_banned = await self.cas_gateway.check_cas(message.user_id)
            
            if is_banned:
                return DetectorResult(
                    detector_name="cas",
                    is_spam=True,
                    confidence=0.9,
                    details="User banned in CAS database"
                )
            else:
                return DetectorResult(
                    detector_name="cas",
                    is_spam=False,
                    confidence=0.1,
                    details="User not found in CAS"
                )
                
        except Exception as e:
            return DetectorResult(
                detector_name="cas",
                is_spam=False,
                confidence=0.0,
                details=f"CAS check failed: {str(e)}",
                error=str(e)
            )

