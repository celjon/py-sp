from typing import Dict, Any

from ...entity.message import Message
from ...entity.detection_result import DetectorResult


class OpenAIDetector:
    """Детектор спама на основе OpenAI API"""
    
    def __init__(self, openai_gateway):
        """
        Args:
            openai_gateway: Шлюз для работы с OpenAI API
        """
        self.openai_gateway = openai_gateway
    
    async def detect(self, message: Message, user_context: Dict[str, Any] = None) -> DetectorResult:
        """
        Анализирует сообщение с помощью OpenAI
        
        Args:
            message: Сообщение для проверки
            user_context: Контекст пользователя
            
        Returns:
            Результат детекции
        """
        try:
            # Пропускаем очень короткие сообщения
            if len(message.text.strip()) < 10:
                return DetectorResult(
                    detector_name="openai",
                    is_spam=False,
                    confidence=0.0,
                    details="Message too short for OpenAI analysis"
                )
            
            # Анализируем сообщение через OpenAI
            result = await self.openai_gateway.check_openai(message.text)
            
            if result["is_spam"]:
                return DetectorResult(
                    detector_name="openai",
                    is_spam=True,
                    confidence=result["confidence"],
                    details=f"OpenAI detected spam: {result.get('reason', 'unknown')}"
                )
            else:
                return DetectorResult(
                    detector_name="openai",
                    is_spam=False,
                    confidence=1.0 - result["confidence"],
                    details="OpenAI classified as legitimate message"
                )
                
        except Exception as e:
            return DetectorResult(
                detector_name="openai",
                is_spam=False,
                confidence=0.0,
                details=f"OpenAI analysis failed: {str(e)}",
                error=str(e)
            )

