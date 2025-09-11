# src/domain/service/detector/openai.py
"""
Production-Ready OpenAI Spam Detector
Контекстуальный анализ спама с помощью LLM
"""

import time
import logging
import json
from typing import Dict, Any, Optional, List

from ...entity.message import Message
from ...entity.detection_result import DetectorResult

logger = logging.getLogger(__name__)


class OpenAIDetector:
    """
    Production-ready детектор спама на основе OpenAI LLM
    
    Features:
    - Context-aware анализ с учетом пользователя
    - Интеллектуальное определение спама через LLM
    - Comprehensive error handling
    - Performance monitoring
    - Fallback режимы
    """
    
    def __init__(self, openai_gateway, config: Dict[str, Any] = None):
        """
        Args:
            openai_gateway: Шлюз для работы с OpenAI API
            config: Дополнительная конфигурация
        """
        self.openai_gateway = openai_gateway
        self.config = config or {}
        
        # Detection settings
        self.min_text_length = self.config.get("min_text_length", 10)
        self.max_text_length = self.config.get("max_text_length", 4000)
        self.confidence_threshold = self.config.get("confidence_threshold", 0.7)
        
        # Performance settings
        self.timeout = self.config.get("timeout", 5.0)
        self.max_retries = self.config.get("max_retries", 2)
        self.retry_delay = self.config.get("retry_delay", 1.0)
        
        # Context settings
        self.use_user_context = self.config.get("use_user_context", True)
        self.analyze_patterns = self.config.get("analyze_patterns", True)
        
        # Metrics
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._spam_detected = 0
        self._total_processing_time = 0.0
        
        logger.info("🧠 OpenAI Detector инициализирован")
        logger.info(f"   Min length: {self.min_text_length}, Max length: {self.max_text_length}")
        logger.info(f"   Timeout: {self.timeout}s, Retries: {self.max_retries}")
    
    async def detect(self, message: Message, user_context: Dict[str, Any] = None) -> DetectorResult:
        """
        Анализирует сообщение с помощью OpenAI LLM
        
        Args:
            message: Сообщение для проверки
            user_context: Контекст пользователя
            
        Returns:
            DetectorResult с анализом LLM
        """
        start_time = time.time()
        self._total_requests += 1
        
        text = message.text or ""
        
        logger.debug(f"🧠 OpenAI анализ: '{text[:50]}{'...' if len(text) > 50 else ''}'")
        
        try:
            # Валидация входных данных
            if len(text.strip()) < self.min_text_length:
                logger.debug(f"⚠️ Текст слишком короткий для OpenAI: {len(text)} символов")
                return DetectorResult(
                    detector_name="OpenAI",
                    is_spam=False,
                    confidence=0.0,
                    details=f"Text too short for analysis ({len(text)} chars)",
                    processing_time_ms=(time.time() - start_time) * 1000
                )
            
            if len(text) > self.max_text_length:
                # Обрезаем текст
                text = text[:self.max_text_length]
                logger.warning(f"⚠️ Текст обрезан до {self.max_text_length} символов")
            
            # Подготавливаем контекст для анализа
            analysis_context = self._prepare_analysis_context(message, user_context)
            
            # Выполняем анализ с retry logic
            openai_result = await self._analyze_with_retry(text, analysis_context)
            
            processing_time_ms = (time.time() - start_time) * 1000
            self._total_processing_time += processing_time_ms
            
            # Парсим результат
            is_spam, confidence, reasoning = self._parse_openai_result(openai_result)
            
            if is_spam:
                self._spam_detected += 1
                logger.warning(f"🚨 OpenAI: СПАМ обнаружен (confidence: {confidence:.3f}, время: {processing_time_ms:.1f}ms)")
                logger.warning(f"   Обоснование: {reasoning}")
            else:
                logger.debug(f"✅ OpenAI: сообщение чистое (confidence: {confidence:.3f}, время: {processing_time_ms:.1f}ms)")
            
            self._successful_requests += 1
            
            return DetectorResult(
                detector_name="OpenAI",
                is_spam=is_spam,
                confidence=confidence,
                details=reasoning,
                processing_time_ms=processing_time_ms
            )
            
        except Exception as e:
            self._failed_requests += 1
            processing_time_ms = (time.time() - start_time) * 1000
            
            logger.error(f"⚠️ OpenAI detector failed: {e}")
            
            # Graceful degradation
            return DetectorResult(
                detector_name="OpenAI",
                is_spam=False,
                confidence=0.0,
                details=f"OpenAI analysis failed: {str(e)}",
                error=str(e),
                processing_time_ms=processing_time_ms
            )
    
    def _prepare_analysis_context(self, message: Message, user_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Подготавливает контекст для OpenAI анализа"""
        context = {
            "message_length": len(message.text or ""),
            "has_links": self._contains_links(message.text or ""),
            "has_mentions": self._contains_mentions(message.text or ""),
            "language": self._detect_primary_language(message.text or "")
        }
        
        if user_context and self.use_user_context:
            context.update({
                "is_new_user": user_context.get("is_new_user", False),
                "user_id": user_context.get("user_id"),
                "previous_warnings": user_context.get("previous_warnings", 0),
                "is_admin": user_context.get("is_admin_or_owner", False)
            })
        
        return context
    
    async def _analyze_with_retry(self, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Выполняет анализ с retry logic"""
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    await asyncio.sleep(self.retry_delay * attempt)
                    logger.info(f"🔄 OpenAI retry attempt {attempt + 1}")
                
                # Выполняем запрос к OpenAI
                result = await asyncio.wait_for(
                    self.openai_gateway.analyze_spam(text, context),
                    timeout=self.timeout
                )
                
                return result
                
            except asyncio.TimeoutError as e:
                last_error = f"Timeout after {self.timeout}s"
                logger.warning(f"⏰ OpenAI timeout на попытке {attempt + 1}")
                continue
            except Exception as e:
                last_error = str(e)
                logger.warning(f"⚠️ OpenAI ошибка на попытке {attempt + 1}: {e}")
                continue
        
        # Все попытки неудачны
        raise RuntimeError(f"OpenAI analysis failed after {self.max_retries + 1} attempts: {last_error}")
    
    def _parse_openai_result(self, openai_result: Dict[str, Any]) -> tuple[bool, float, str]:
        """
        Парсит результат OpenAI и извлекает is_spam, confidence, reasoning
        
        Returns:
            (is_spam, confidence, reasoning)
        """
        try:
            is_spam = openai_result.get("is_spam", False)
            confidence = float(openai_result.get("confidence", 0.0))
            
            # Нормализуем confidence
            confidence = max(0.0, min(1.0, confidence))
            
            # Извлекаем обоснование
            reasoning = openai_result.get("reasoning", "No reasoning provided")
            if isinstance(reasoning, list):
                reasoning = "; ".join(reasoning)
            
            # Добавляем дополнительную информацию
            spam_indicators = openai_result.get("spam_indicators", [])
            if spam_indicators and isinstance(spam_indicators, list):
                reasoning += f" (индикаторы: {', '.join(spam_indicators)})"
            
            return is_spam, confidence, reasoning
            
        except (ValueError, TypeError) as e:
            logger.error(f"⚠️ Ошибка парсинга OpenAI результата: {e}")
            logger.error(f"   Raw result: {openai_result}")
            
            # Fallback parsing
            return False, 0.0, "Failed to parse OpenAI result"
    
    def _contains_links(self, text: str) -> bool:
        """Проверяет наличие ссылок в тексте"""
        import re
        link_patterns = [
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            r'www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            r't\.me/[a-zA-Z0-9_]+',
            r'@[a-zA-Z0-9_]+',
        ]
        
        for pattern in link_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        
        return False
    
    def _contains_mentions(self, text: str) -> bool:
        """Проверяет наличие упоминаний в тексте"""
        import re
        return bool(re.search(r'@[a-zA-Z0-9_]+', text))
    
    def _detect_primary_language(self, text: str) -> str:
        """Определяет основной язык текста"""
        if not text:
            return "unknown"
        
        # Подсчитываем символы
        cyrillic_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
        latin_chars = sum(1 for c in text if c.isalpha() and not ('\u0400' <= c <= '\u04FF'))
        
        total_letters = cyrillic_chars + latin_chars
        if total_letters == 0:
            return "unknown"
        
        cyrillic_ratio = cyrillic_chars / total_letters
        
        if cyrillic_ratio >= 0.3:
            return "ru"
        elif cyrillic_ratio < 0.1:
            return "en"
        else:
            return "mixed"
    
    async def batch_detect(self, messages: List[Message], user_contexts: List[Dict[str, Any]] = None) -> List[DetectorResult]:
        """
        Batch анализ сообщений для оптимизации
        
        Args:
            messages: Список сообщений
            user_contexts: Список контекстов пользователей
            
        Returns:
            Список DetectorResult
        """
        if not messages:
            return []
        
        logger.info(f"🧠 OpenAI batch анализ: {len(messages)} сообщений")
        
        results = []
        
        # Группируем по языкам для оптимизации промптов
        grouped_messages = self._group_messages_by_language(messages)
        
        for language, msg_group in grouped_messages.items():
            try:
                # Batch анализ для одного языка
                if hasattr(self.openai_gateway, 'analyze_spam_batch'):
                    batch_results = await self.openai_gateway.analyze_spam_batch(
                        [msg.text for msg in msg_group],
                        language=language
                    )
                    
                    for i, msg in enumerate(msg_group):
                        if i < len(batch_results):
                            is_spam, confidence, reasoning = self._parse_openai_result(batch_results[i])
                            results.append(DetectorResult(
                                detector_name="OpenAI",
                                is_spam=is_spam,
                                confidence=confidence,
                                details=reasoning
                            ))
                        else:
                            # Fallback если результатов меньше
                            results.append(DetectorResult(
                                detector_name="OpenAI",
                                is_spam=False,
                                confidence=0.0,
                                details="Batch result missing"
                            ))
                else:
                    # Fallback: последовательный анализ
                    for msg in msg_group:
                        user_ctx = user_contexts[messages.index(msg)] if user_contexts else None
                        result = await self.detect(msg, user_ctx)
                        results.append(result)
                        
            except Exception as e:
                logger.error(f"⚠️ OpenAI batch ошибка для языка {language}: {e}")
                
                # Fallback: помечаем как ошибку
                for msg in msg_group:
                    results.append(DetectorResult(
                        detector_name="OpenAI",
                        is_spam=False,
                        confidence=0.0,
                        details=f"Batch analysis failed: {str(e)}",
                        error=str(e)
                    ))
        
        logger.info(f"✅ OpenAI batch анализ завершен: {len(results)} результатов")
        return results
    
    def _group_messages_by_language(self, messages: List[Message]) -> Dict[str, List[Message]]:
        """Группирует сообщения по языкам для оптимизации"""
        groups = {"ru": [], "en": [], "mixed": [], "unknown": []}
        
        for message in messages:
            language = self._detect_primary_language(message.text or "")
            groups[language].append(message)
        
        # Убираем пустые группы
        return {lang: msgs for lang, msgs in groups.items() if msgs}
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Возвращает статистику производительности"""
        success_rate = (
            self._successful_requests / self._total_requests 
            if self._total_requests > 0 else 0
        )
        
        avg_processing_time = (
            self._total_processing_time / self._successful_requests
            if self._successful_requests > 0 else 0
        )
        
        spam_detection_rate = (
            self._spam_detected / self._successful_requests
            if self._successful_requests > 0 else 0
        )
        
        return {
            "total_requests": self._total_requests,
            "successful_requests": self._successful_requests,
            "failed_requests": self._failed_requests,
            "spam_detected": self._spam_detected,
            "success_rate": success_rate,
            "average_processing_time_ms": avg_processing_time,
            "spam_detection_rate": spam_detection_rate
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка состояния OpenAI detector
        
        Returns:
            Статус здоровья системы
        """
        try:
            # Выполняем тестовый запрос
            start_time = time.time()
            
            test_text = "Тестовое сообщение для проверки API"
            test_context = {"is_new_user": False}
            
            test_result = await self.openai_gateway.analyze_spam(test_text, test_context)
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # Проверяем корректность ответа
            if not isinstance(test_result, dict):
                raise ValueError(f"Invalid response format: {type(test_result)}")
            
            required_fields = ["is_spam", "confidence"]
            missing_fields = [field for field in required_fields if field not in test_result]
            
            if missing_fields:
                raise ValueError(f"Missing required fields: {missing_fields}")
            
            return {
                "status": "healthy",
                "api_available": True,
                "response_time_ms": response_time_ms,
                "test_result": {
                    "is_spam": test_result.get("is_spam"),
                    "confidence": test_result.get("confidence")
                },
                "performance": self.get_performance_stats(),
                "config": {
                    "model": getattr(self.openai_gateway, 'model', 'unknown'),
                    "timeout": self.timeout,
                    "min_text_length": self.min_text_length,
                    "use_user_context": self.use_user_context
                }
            }
            
        except Exception as e:
            logger.error(f"❌ OpenAI health check failed: {e}")
            
            return {
                "status": "error",
                "api_available": False,
                "error": str(e),
                "performance": self.get_performance_stats()
            }
    
    async def validate_configuration(self) -> Dict[str, Any]:
        """
        Валидирует конфигурацию OpenAI detector
        
        Returns:
            Результат валидации
        """
        validation_result = {
            "status": "valid",
            "errors": [],
            "warnings": [],
            "recommendations": []
        }
        
        try:
            # Проверяем gateway
            if not self.openai_gateway:
                validation_result["errors"].append("OpenAI gateway not configured")
                validation_result["status"] = "invalid"
                return validation_result
            
            # Проверяем API key
            if not hasattr(self.openai_gateway, 'api_key') or not self.openai_gateway.api_key:
                validation_result["errors"].append("OpenAI API key not configured")
                validation_result["status"] = "invalid"
            
            # Проверяем модель
            model = getattr(self.openai_gateway, 'model', None)
            if not model:
                validation_result["warnings"].append("OpenAI model not specified")
            elif model not in ["gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini"]:
                validation_result["warnings"].append(f"Unusual OpenAI model: {model}")
            
            # Проверяем timeout settings
            if self.timeout < 1.0:
                validation_result["warnings"].append("Very low timeout - may cause frequent failures")
            elif self.timeout > 10.0:
                validation_result["warnings"].append("High timeout - may impact performance")
            
            # Проверяем text length limits
            if self.min_text_length < 5:
                validation_result["recommendations"].append("Consider increasing min_text_length for better accuracy")
            
            if self.max_text_length > 8000:
                validation_result["warnings"].append("High max_text_length may increase costs and latency")
            
            # Тестовый запрос
            health = await self.health_check()
            if health["status"] != "healthy":
                validation_result["errors"].append(f"Health check failed: {health.get('error')}")
                validation_result["status"] = "invalid"
            
        except Exception as e:
            validation_result["errors"].append(f"Validation failed: {str(e)}")
            validation_result["status"] = "error"
        
        return validation_result
    
    def reset_stats(self):
        """Сбрасывает статистику (для тестирования)"""
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._spam_detected = 0
        self._total_processing_time = 0.0
        logger.info("📊 OpenAI статистика сброшена")
