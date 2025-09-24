# src/adapter/gateway/bothub_gateway.py
"""
BotHub Gateway - OpenAI-совместимый клиент для BotHub API
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, Tuple, List
import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class BotHubGateway:
    """
    BotHub Gateway - OpenAI-совместимый клиент для детекции спама
    
    Features:
    - OpenAI-совместимый API через BotHub
    - Поддержка пользовательских токенов
    - Настраиваемый системный промпт
    - Comprehensive error handling
    - Health checks и мониторинг
    """

    def __init__(self, user_token: str, system_prompt: str = None, config: Dict[str, Any] = None):
        """
        Инициализация BotHub Gateway
        
        Args:
            user_token: Токен пользователя BotHub
            system_prompt: Системный промпт для детекции
            config: Дополнительная конфигурация
        """
        self.user_token = user_token
        self.system_prompt = system_prompt or self._get_default_prompt()
        self.config = config or {}
        
        # Настройки из конфига
        self.model = self.config.get("model", "gpt-4o-mini")
        self.max_tokens = self.config.get("max_tokens", 150)
        self.temperature = self.config.get("temperature", 0.0)
        self.timeout = self.config.get("timeout", 10.0)
        self.max_retries = self.config.get("max_retries", 2)
        self.retry_delay = self.config.get("retry_delay", 1.0)
        
        # BotHub API настройки
        self.base_url = "https://bothub.chat/api/v2/openai/v1"
        
        # Инициализация OpenAI клиента
        self.client = AsyncOpenAI(
            api_key=self.user_token,
            base_url=self.base_url,
            timeout=self.timeout
        )
        
        # Статистика
        self._total_requests = 0
        self._total_processing_time = 0.0
        self._last_health_check = 0
        self._last_health_status = {"status": "unknown"}
        
        logger.info(f"🔗 BotHub Gateway инициализирован")
        logger.info(f"   Модель: {self.model}")
        logger.info(f"   Max tokens: {self.max_tokens}")
        logger.info(f"   Timeout: {self.timeout}s")

    async def check_spam(
        self, text: str, user_context: Optional[Dict] = None
    ) -> Tuple[bool, float, Dict[str, int]]:
        """
        Проверить сообщение через BotHub API
        
        Args:
            text: Текст для анализа
            user_context: Контекст пользователя
            
        Returns:
            (is_spam, confidence, token_usage)
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

            # Выполняем запрос к BotHub
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"}
            )

            # Парсим ответ
            content = response.choices[0].message.content
            result = json.loads(content)
            
            # Извлекаем данные
            is_spam = result.get("is_spam", False)
            confidence = float(result.get("confidence", 0.0))
            
            # Токены
            token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
            
            self._total_requests += 1
            
            logger.debug(f"🔗 BotHub анализ: is_spam={is_spam}, confidence={confidence:.3f}")
            
            return is_spam, confidence, token_usage
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ BotHub JSON decode error: {e}")
            return False, 0.0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            
        except Exception as e:
            logger.error(f"❌ BotHub API error: {e}")
            return False, 0.0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья BotHub API
        
        Returns:
            Статус API
        """
        current_time = time.time()
        
        # Кэшируем результат на 30 секунд
        if current_time - self._last_health_check < 30:
            return self._last_health_status
            
        try:
            # Простой тестовый запрос
            test_messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello"}
            ]
            
            start_time = time.time()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=test_messages,
                max_tokens=10,
                temperature=0.0
            )
            
            response_time = (time.time() - start_time) * 1000
            
            self._last_health_status = {
                "status": "healthy",
                "response_time_ms": response_time,
                "model": self.model,
                "last_check": current_time,
                "total_requests": self._total_requests,
                "avg_processing_time": self._total_processing_time / max(self._total_requests, 1)
            }
            
            self._last_health_check = current_time
            
        except Exception as e:
            self._last_health_status = {
                "status": "error",
                "error": str(e),
                "last_check": current_time
            }
            self._last_health_check = current_time

        return self._last_health_status

    def update_system_prompt(self, new_prompt: str) -> None:
        """
        Обновить системный промпт
        
        Args:
            new_prompt: Новый системный промпт
        """
        self.system_prompt = new_prompt
        logger.info("🔗 BotHub системный промпт обновлен")

    def update_user_token(self, new_token: str) -> None:
        """
        Обновить токен пользователя
        
        Args:
            new_token: Новый токен
        """
        self.user_token = new_token
        self.client = AsyncOpenAI(
            api_key=self.user_token,
            base_url=self.base_url,
            timeout=self.timeout
        )
        logger.info("🔗 BotHub токен пользователя обновлен")

    def _get_default_prompt(self) -> str:
        """Системный промпт для детекции спама"""
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

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику использования"""
        return {
            "total_requests": self._total_requests,
            "total_processing_time": self._total_processing_time,
            "avg_processing_time": self._total_processing_time / max(self._total_requests, 1),
            "model": self.model,
            "base_url": self.base_url
        }

    def get_model_info(self) -> Dict[str, Any]:
        """Получить информацию о текущей модели"""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "base_url": self.base_url
        }
