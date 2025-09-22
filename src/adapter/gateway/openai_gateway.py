import openai
import json
from typing import Dict, Any, Optional, Tuple
from ...lib.clients.http_client import HttpClient


class OpenAIGateway:
    def __init__(self, api_key: str, config: Dict[str, Any]):
        # Используем только стандартный OpenAI API
        self.client = openai.AsyncOpenAI(api_key=api_key)

        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = config.get("max_tokens", 150)
        self.temperature = config.get("temperature", 0.0)
        self.system_prompt = config.get("system_prompt", self._get_default_prompt())

        # Health check cache
        self._last_health_check = 0
        self._last_health_status = {"status": "healthy", "model": self.model, "max_tokens": self.max_tokens}

    async def check_openai(
        self, text: str, user_context: Optional[Dict] = None
    ) -> Tuple[bool, float]:
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
                {"role": "user", "content": f"{context_info}\n\nMessage to analyze: {text}"},
            ]

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)

            is_spam = result.get("is_spam", False)
            confidence = result.get("confidence", 0.0)

            # Валидируем confidence
            confidence = max(0.0, min(1.0, float(confidence)))

            # Извлекаем информацию о токенах
            usage = response.usage
            token_info = {
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            }

            return is_spam, confidence, token_info

        except Exception as e:
            print(f"OpenAI API error: {e}")
            return False, 0.0, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    async def analyze_spam(self, text: str, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Анализ спама с помощью OpenAI (аналог check_openai, но возвращает полный результат)

        Args:
            text: Текст для анализа
            user_context: Контекст пользователя

        Returns:
            Dict с результатами анализа
        """
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
                {"role": "user", "content": f"{context_info}\n\nMessage to analyze: {text}"},
            ]

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)

            is_spam = result.get("is_spam", False)
            confidence = result.get("confidence", 0.0)
            reason = result.get("reason", result.get("reasoning", ""))

            # Валидируем confidence
            confidence = max(0.0, min(1.0, float(confidence)))

            # Извлекаем информацию о токенах
            usage = response.usage
            token_info = {
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            }

            return {
                "is_spam": is_spam,
                "confidence": confidence,
                "reason": reason,
                "model": self.model,
                "token_usage": token_info,
                "processing_time_ms": 0,  # Можно добавить измерение времени
            }

        except Exception as e:
            print(f"OpenAI API error: {e}")
            return {
                "is_spam": False,
                "confidence": 0.0,
                "reason": f"API error: {str(e)}",
                "model": self.model,
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "error": str(e),
            }

    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья OpenAI Gateway"""
        import time

        current_time = time.time()

        # Делаем полную проверку API только раз в час
        if current_time - self._last_health_check > 3600:  # 1 час
            try:
                # Простая проверка доступности API
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "test"}],
                    max_tokens=1,
                    temperature=0.0,
                )
                self._last_health_status = {
                    "status": "healthy",
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "last_api_check": current_time
                }
                self._last_health_check = current_time
            except Exception as e:
                self._last_health_status = {
                    "status": "error",
                    "error": str(e),
                    "last_api_check": current_time
                }
                self._last_health_check = current_time

        # Возвращаем кешированный статус
        return self._last_health_status

    def _get_default_prompt(self) -> str:
        return """Ты эксперт по определению спама в сообщениях чатов. Анализируй быстро и точно.

ЗАДАЧА: Определи, является ли сообщение спамом.

СПАМ это:
- Реклама товаров/услуг без разрешения
- Призывы писать в личные сообщения для "заработка"
- Финансовые схемы и "быстрые деньги"
- Массовые рассылки и копипаста
- Навязчивые ссылки на внешние ресурсы
- Предложения инвестиций, криптовалют, форекса

НЕ СПАМ это:
- Обычное общение и вопросы
- Обмен опытом по теме чата
- Мемы, шутки, реакции
- Конструктивная критика
- Информативные ссылки по теме

ФОРМАТ ОТВЕТА (только JSON):
{
  "is_spam": boolean,
  "confidence": float (0.0-1.0),
  "reason": "краткое объяснение на русском"
}

Будь консервативным - при сомнениях классифицируй как НЕ спам."""
