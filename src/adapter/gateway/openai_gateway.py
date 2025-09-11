import openai
import json
from typing import Dict, Any, Optional, Tuple
from ...lib.clients.http_client import HttpClient

class OpenAIGateway:
    def __init__(self, api_key: str, config: Dict[str, Any]):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = config.get("max_tokens", 150)
        self.temperature = config.get("temperature", 0.0)
        self.system_prompt = config.get("system_prompt", self._get_default_prompt())

    async def check_openai(self, text: str, user_context: Optional[Dict] = None) -> Tuple[bool, float]:
        """Проверить сообщение через OpenAI API"""
        try:
            # Формируем контекстную информацию
            context_info = ""
            if user_context:
                context_info = f"""
User context:
- Message count: {user_context.get('message_count', 0)}
- Spam score: {user_context.get('spam_score', 0.0)}
- Is new user: {user_context.get('is_new_user', False)}
"""

            # Формируем запрос
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"{context_info}\n\nMessage to analyze: {text}"}
            ]

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            
            is_spam = result.get("is_spam", False)
            confidence = result.get("confidence", 0.0)
            
            # Валидируем confidence
            confidence = max(0.0, min(1.0, float(confidence)))
            
            return is_spam, confidence

        except Exception as e:
            print(f"OpenAI API error: {e}")
            return False, 0.0

    def _get_default_prompt(self) -> str:
        return """You are a spam detection system for Telegram groups. 
Analyze the given message and determine if it's spam.

Consider these spam indicators:
- Promotional content with aggressive sales language
- Requests for personal information or payments  
- Phishing attempts or suspicious links
- Repetitive or bot-like content
- Messages that seem automated or mass-sent
- Content that violates typical group rules

Respond with valid JSON in this format:
{
    "is_spam": boolean,
    "confidence": float (0.0 to 1.0),
    "reasoning": "brief explanation"
}

Be conservative - when in doubt, classify as not spam."""





