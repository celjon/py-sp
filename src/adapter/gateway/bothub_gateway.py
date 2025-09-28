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

from src.domain.service.prompt_factory import PromptFactory

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

    @staticmethod
    async def get_available_models(token: str) -> list[dict]:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    'https://bothub.chat/api/v2/model/list?children=1',
                    headers={
                        'Authorization': f'Bearer {token}',
                        'Content-Type': 'application/json'
                    },
                    timeout=60.0
                )
                if response.status_code == 200:
                    models = response.json()
                    text_models = [
                        model for model in models
                        if 'TEXT_TO_TEXT' in model.get('features', [])
                    ]
                    return text_models
                return []
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            return []

    @staticmethod
    async def verify_token(token: str) -> bool:
        """
        Проверяет валидность токена BotHub

        Args:
            token: Токен для проверки

        Returns:
            bool: True если токен валиден, False иначе
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    'https://bothub.chat/api/v2/openai/v1/chat/completions',
                    headers={
                        'Authorization': f'Bearer {token}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        'model': 'gpt-5-nano',
                        'messages': [{'role': 'user', 'content': 'test'}],
                        'max_tokens': 5
                    },
                    timeout=60.0
                )
                return response.status_code in [200, 429]
        except Exception as e:
            logger.error(f"Error verifying token: {e}")
            return False

    def __init__(self, user_token: str, user_instructions: str = None, user_model: str = None, config: Dict[str, Any] = None):
        """
        Инициализация BotHub Gateway

        Args:
            user_token: Токен пользователя BotHub
            user_instructions: Пользовательские инструкции для детекции (без формата ответа)
            user_model: Модель пользователя для детекции
            config: Дополнительная конфигурация
        """
        self.user_token = user_token
        self.user_instructions = user_instructions or PromptFactory.get_default_user_instructions()
        self.system_prompt = PromptFactory.build_spam_detection_prompt(self.user_instructions)
        self.config = config or {}

        self.model = user_model or self.config.get("model", "gpt-5-nano")
        self.max_tokens = self.config.get("max_tokens", 1000)
        self.temperature = self.config.get("temperature", 0.0)
        self.timeout = self.config.get("timeout", 60.0)
        self.max_retries = self.config.get("max_retries", 2)
        self.retry_delay = self.config.get("retry_delay", 1.0)
        
        self.base_url = "https://bothub.chat/api/v2/openai/v1"
        
        self.client = AsyncOpenAI(
            api_key=self.user_token,
            base_url=self.base_url,
            timeout=self.timeout
        )
        
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
        start_time = time.time()

        try:
            context_info = ""
            if user_context:
                context_info = f"""
User context:
- Message count: {user_context.get('message_count', 0)}
- Spam score: {user_context.get('spam_score', 0.0)}
- Is new user: {user_context.get('is_new_user', False)}
"""

            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"{context_info}\n\nMessage to analyze: {text}"},
            ]

            # Параметры запроса
            request_params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature
            }

            # Для GPT моделей полностью отключаем reasoning - ответ будет только в content
            if self.model.lower().startswith('gpt') or 'gpt' in self.model.lower():
                request_params["reasoning"] = {"max_tokens": 0}  # Полное отключение reasoning
                logger.debug(f"[BOTHUB] Полностью отключаем reasoning для GPT модели: {self.model}")

            # Принудительно требуем JSON ответ без дополнительного текста
            if "max_tokens" in request_params:
                request_params["max_tokens"] = min(request_params["max_tokens"], 200)  # Ограничиваем для краткости

            response = await self.client.chat.completions.create(**request_params)

            content = response.choices[0].message.content
            logger.info(f"[BOTHUB] Raw API response: {repr(content)}")

            # Проверяем на пустой content
            if not content or content.strip() == "":
                logger.error(f"[BOTHUB] Empty response despite completion_tokens={response.usage.completion_tokens if response.usage else 0}")
                logger.error(f"[BOTHUB] Full response: {response}")
                # Возвращаем "не спам" с низкой уверенностью при пустом ответе
                return False, 0.0, {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                }

            try:
                # Очищаем content от возможного мусора (пробелы, переносы строк)
                clean_content = content.strip()

                # Если есть дополнительный текст до/после JSON, пытаемся извлечь только JSON
                import re
                json_match = re.search(r'\{[^}]*"is_spam"[^}]*"confidence"[^}]*\}', clean_content)
                if json_match:
                    clean_content = json_match.group(0)
                    logger.debug(f"[BOTHUB] Извлечен чистый JSON: {clean_content}")

                result = json.loads(clean_content)
                logger.info(f"[BOTHUB] Parsed JSON: {result}")

                # Проверяем что JSON содержит обязательные поля
                if "is_spam" not in result or "confidence" not in result:
                    raise ValueError(f"Missing required fields in response: {result}")

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"[BOTHUB] JSON decode/validation error: {e}")
                logger.error(f"[BOTHUB] Full response content (len={len(content)}): {content}")
                logger.error(f"[BOTHUB] Usage: {response.usage}")
                # Fallback - возвращаем безопасные значения
                return False, 0.0, {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                }

            is_spam = result.get("is_spam", False)
            raw_confidence = float(result.get("confidence", 0.0))

            # Конвертируем BotHub confidence в RUSpam-совместимый формат:
            # BotHub: is_spam=true, confidence=0.95 → RUSpam: 0.95 (спам)
            # BotHub: is_spam=false, confidence=0.95 → RUSpam: 0.05 (не спам)
            confidence = raw_confidence if is_spam else (1.0 - raw_confidence)

            token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
                "raw_confidence": raw_confidence  # Сохраняем исходную уверенность для логирования
            }

            processing_time = time.time() - start_time
            self._total_requests += 1
            self._total_processing_time += processing_time

            logger.debug(f"🔗 BotHub анализ: is_spam={is_spam}, raw_confidence={raw_confidence:.3f}, normalized_confidence={confidence:.3f}, время={processing_time*1000:.1f}ms")

            return is_spam, confidence, token_usage
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ BotHub JSON decode error: {e}")
            return False, 0.0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            
        except Exception as e:
            logger.error(f"❌ BotHub API error: {e}")
            return False, 0.0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья BotHub API через проверку доступности модели

        Returns:
            Статус API
        """
        current_time = time.time()

        if current_time - self._last_health_check < 30:
            return self._last_health_status

        try:
            start_time = time.time()

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    'https://bothub.chat/api/v2/model/list?children=1',
                    headers={
                        'Authorization': f'Bearer {self.user_token}',
                        'Content-Type': 'application/json'
                    },
                    timeout=60.0
                )

                response_time = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    models = response.json()
                    model_found = any(
                        model.get('id') == self.model or model.get('label') == self.model
                        for model in models
                    )

                    status = "healthy" if model_found else "warning"

                    self._last_health_status = {
                        "status": status,
                        "response_time_ms": response_time,
                        "model": self.model,
                        "model_available": model_found,
                        "last_check": current_time,
                        "total_requests": self._total_requests,
                        "avg_processing_time": self._total_processing_time / max(self._total_requests, 1)
                    }
                else:
                    self._last_health_status = {
                        "status": "error",
                        "error": f"HTTP {response.status_code}",
                        "model": self.model,
                        "last_check": current_time
                    }

            self._last_health_check = current_time

        except Exception as e:
            logger.warning(f"BotHub health check failed: {e}")
            self._last_health_status = {
                "status": "error",
                "error": str(e),
                "model": self.model,
                "last_check": current_time
            }
            self._last_health_check = current_time

        return self._last_health_status

    def update_user_instructions(self, new_instructions: str) -> None:
        """
        Обновить пользовательские инструкции

        Args:
            new_instructions: Новые пользовательские инструкции
        """
        self.user_instructions = new_instructions
        self.system_prompt = PromptFactory.build_spam_detection_prompt(self.user_instructions)
        logger.info("🔗 BotHub пользовательские инструкции обновлены")

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


