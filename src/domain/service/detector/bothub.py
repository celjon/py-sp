# src/domain/service/detector/bothub.py
"""
BotHub Spam Detector - детектор спама на основе BotHub LLM
"""

import time
import logging
import json
import asyncio
from typing import Dict, Any, Optional, List

from ...entity.message import Message
from ...entity.detection_result import DetectorResult

logger = logging.getLogger(__name__)


class BotHubDetector:
    """
    Production-ready детектор спама на основе BotHub LLM

    Features:
    - Context-aware анализ с учетом пользователя
    - Интеллектуальное определение спама через LLM
    - Comprehensive error handling
    - Performance monitoring
    - Fallback режимы
    - Настраиваемый системный промпт
    """

    def __init__(self, bothub_gateway, config: Dict[str, Any] = None):
        """
        Инициализация BotHub детектора
        
        Args:
            bothub_gateway: BotHub Gateway для API вызовов
            config: Конфигурация детектора
        """
        self.gateway = bothub_gateway
        self.config = config or {}
        
        # Настройки детекции
        self.min_text_length = self.config.get("min_text_length", 5)
        self.max_text_length = self.config.get("max_text_length", 4000)
        self.timeout = self.config.get("timeout", 10.0)
        self.max_retries = self.config.get("max_retries", 2)
        self.retry_delay = self.config.get("retry_delay", 1.0)
        
        # Статистика
        self._total_requests = 0
        self._total_processing_time = 0.0
        self._successful_requests = 0
        self._failed_requests = 0
        
        logger.info("🤖 BotHub Detector инициализирован")
        logger.info(f"   Min text length: {self.min_text_length}")
        logger.info(f"   Max text length: {self.max_text_length}")
        logger.info(f"   Timeout: {self.timeout}s, Retries: {self.max_retries}")

    async def detect(self, message: Message, user_context: Dict[str, Any] = None) -> DetectorResult:
        """
        Анализирует сообщение с помощью BotHub LLM

        Args:
            message: Сообщение для проверки
            user_context: Контекст пользователя

        Returns:
            DetectorResult с анализом LLM
        """
        start_time = time.time()
        self._total_requests += 1

        text = message.text or ""

        logger.debug(f"🤖 BotHub анализ: '{text[:50]}{'...' if len(text) > 50 else ''}'")

        try:
            # Валидация входных данных
            if len(text.strip()) < self.min_text_length:
                logger.debug(f"[WARN] Текст слишком короткий для BotHub: {len(text)} символов")
                return DetectorResult(
                    detector_name="BotHub",
                    is_spam=False,
                    confidence=0.0,
                    details=f"Text too short for analysis ({len(text)} chars)",
                    processing_time_ms=(time.time() - start_time) * 1000,
                )

            if len(text) > self.max_text_length:
                # Обрезаем текст
                text = text[:self.max_text_length]
                logger.warning(f"[WARN] Текст обрезан до {self.max_text_length} символов")

            # Подготавливаем контекст для анализа
            analysis_context = self._prepare_analysis_context(message, user_context)

            # Выполняем анализ с retry logic
            bothub_result = await self._analyze_with_retry(text, analysis_context)

            processing_time_ms = (time.time() - start_time) * 1000
            self._total_processing_time += processing_time_ms

            # Парсим результат
            if bothub_result:
                is_spam, confidence, token_usage = bothub_result
                self._successful_requests += 1
                
                # Формируем детали
                details = {
                    "model": self.gateway.model,
                    "tokens_used": token_usage.get("total_tokens", 0),
                    "processing_time_ms": processing_time_ms,
                    "user_context_provided": bool(user_context)
                }
                
                return DetectorResult(
                    detector_name="BotHub",
                    is_spam=is_spam,
                    confidence=confidence,
                    details=json.dumps(details),
                    processing_time_ms=processing_time_ms,
                )
            else:
                self._failed_requests += 1
                return DetectorResult(
                    detector_name="BotHub",
                    is_spam=False,
                    confidence=0.0,
                    details="BotHub API request failed",
                    processing_time_ms=processing_time_ms,
                )

        except Exception as e:
            self._failed_requests += 1
            processing_time_ms = (time.time() - start_time) * 1000
            self._total_processing_time += processing_time_ms
            
            logger.error(f"❌ BotHub detector error: {e}")
            
            return DetectorResult(
                detector_name="BotHub",
                is_spam=False,
                confidence=0.0,
                details=f"BotHub error: {str(e)}",
                processing_time_ms=processing_time_ms,
            )

    async def _analyze_with_retry(self, text: str, context: Dict[str, Any]) -> Optional[tuple]:
        """
        Выполняет анализ с повторными попытками
        
        Args:
            text: Текст для анализа
            context: Контекст анализа
            
        Returns:
            (is_spam, confidence, token_usage) или None при ошибке
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    await asyncio.sleep(self.retry_delay * attempt)
                    logger.debug(f"🔄 BotHub retry attempt {attempt}")
                
                # Вызываем BotHub API
                result = await self.gateway.check_spam(text, context)
                return result
                
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ BotHub attempt {attempt + 1} failed: {e}")
                
                if attempt == self.max_retries:
                    logger.error(f"❌ BotHub все попытки исчерпаны: {e}")
                    break
        
        return None

    def _prepare_analysis_context(self, message: Message, user_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Подготавливает контекст для анализа
        
        Args:
            message: Сообщение
            user_context: Контекст пользователя
            
        Returns:
            Подготовленный контекст
        """
        context = {
            "message_id": message.id,
            "user_id": message.user_id,
            "chat_id": message.chat_id,
            "message_length": len(message.text or ""),
            "timestamp": message.created_at.isoformat() if message.created_at else None,
        }
        
        if user_context:
            context.update({
                "user_message_count": user_context.get("message_count", 0),
                "user_spam_score": user_context.get("spam_score", 0.0),
                "is_new_user": user_context.get("is_new_user", False),
                "user_join_date": user_context.get("join_date"),
                "previous_detections": user_context.get("previous_detections", 0),
            })
        
        return context

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику детектора"""
        return {
            "total_requests": self._total_requests,
            "successful_requests": self._successful_requests,
            "failed_requests": self._failed_requests,
            "success_rate": self._successful_requests / max(self._total_requests, 1),
            "total_processing_time": self._total_processing_time,
            "avg_processing_time": self._total_processing_time / max(self._total_requests, 1),
            "config": {
                "min_text_length": self.min_text_length,
                "max_text_length": self.max_text_length,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
            }
        }

    def update_config(self, new_config: Dict[str, Any]) -> None:
        """
        Обновить конфигурацию детектора
        
        Args:
            new_config: Новая конфигурация
        """
        self.config.update(new_config)
        
        # Обновляем настройки
        self.min_text_length = self.config.get("min_text_length", self.min_text_length)
        self.max_text_length = self.config.get("max_text_length", self.max_text_length)
        self.timeout = self.config.get("timeout", self.timeout)
        self.max_retries = self.config.get("max_retries", self.max_retries)
        self.retry_delay = self.config.get("retry_delay", self.retry_delay)
        
        logger.info("🤖 BotHub Detector конфигурация обновлена")

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья детектора
        
        Returns:
            Статус детектора
        """
        try:
            # Проверяем здоровье gateway
            gateway_health = await self.gateway.health_check()
            
            return {
                "detector_status": "healthy" if gateway_health.get("status") == "healthy" else "unhealthy",
                "gateway_health": gateway_health,
                "stats": self.get_stats(),
                "config": {
                    "min_text_length": self.min_text_length,
                    "max_text_length": self.max_text_length,
                    "timeout": self.timeout,
                    "max_retries": self.max_retries,
                }
            }
            
        except Exception as e:
            return {
                "detector_status": "error",
                "error": str(e),
                "stats": self.get_stats()
            }
