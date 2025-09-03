import re
from typing import Dict, Any
from ...entity.message import Message
from ...entity.user import User
from ...entity.detection_result import DetectorResult
from ...lib.utils.text_processing import TextProcessor

class HeuristicDetector:
    """Эвристический детектор спама для быстрых проверок"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.text_processor = TextProcessor()
        
        # Пороги по умолчанию
        self.max_emoji = self.config.get("max_emoji", 3)
        self.max_caps_ratio = self.config.get("max_caps_ratio", 0.7)
        self.max_links = self.config.get("max_links", 2)
        self.max_mentions = self.config.get("max_mentions", 3)
        self.min_message_length = self.config.get("min_message_length", 10)
        self.spam_threshold = self.config.get("spam_threshold", 0.6)
    
    async def check_message(self, message: Message, user: User) -> DetectorResult:
        """Проверить сообщение эвристическими методами"""
        
        text = message.text or ""
        features = self.text_processor.extract_features(text)
        
        # Собираем все нарушения
        violations = []
        confidence = 0.0
        
        # 1. Проверка эмодзи
        emoji_count = features.get('emoji_count', 0)
        if emoji_count > self.max_emoji:
            violations.append(f"too many emojis ({emoji_count})")
            confidence += 0.2
        
        # 2. Проверка заглавных букв
        caps_ratio = features.get('caps_ratio', 0.0)
        if caps_ratio > self.max_caps_ratio:
            violations.append(f"too many caps ({caps_ratio:.2f})")
            confidence += 0.3
        
        # 3. Проверка ссылок
        url_count = features.get('url_count', 0)
        if url_count > self.max_links:
            violations.append(f"too many links ({url_count})")
            confidence += 0.4
        
        # 4. Проверка упоминаний
        mention_count = features.get('mention_count', 0)
        if mention_count > self.max_mentions:
            violations.append(f"too many mentions ({mention_count})")
            confidence += 0.2
        
        # 5. Проверка длины сообщения
        if len(text.strip()) < self.min_message_length:
            violations.append("message too short")
            confidence += 0.1
        
        # 6. Проверка только ссылок
        if url_count > 0 and len(text.strip()) < 20:
            violations.append("links only message")
            confidence += 0.5
        
        # 7. Проверка повторяющихся символов
        repeated_chars = self._check_repeated_characters(text)
        if repeated_chars:
            violations.append(f"repeated characters ({repeated_chars})")
            confidence += 0.3
        
        # 8. Проверка спам-паттернов
        spam_patterns = self.text_processor.contains_spam_patterns(text)
        pattern_score = 0.0
        for category, info in spam_patterns.items():
            if info['count'] > 0:
                pattern_score += info['ratio'] * 0.3
        
        if pattern_score > 0:
            violations.append(f"spam patterns detected ({pattern_score:.2f})")
            confidence += pattern_score
        
        # 9. Проверка восклицательных знаков
        exclamation_count = features.get('exclamation_count', 0)
        if exclamation_count > 3:
            violations.append(f"too many exclamations ({exclamation_count})")
            confidence += 0.2
        
        # 10. Проверка цифр
        digit_ratio = features.get('digit_ratio', 0.0)
        if digit_ratio > 0.3:
            violations.append(f"too many digits ({digit_ratio:.2f})")
            confidence += 0.1
        
        # Определяем итоговый результат
        is_spam = confidence >= self.spam_threshold
        
        # Ограничиваем уверенность
        confidence = min(confidence, 1.0)
        
        # Формируем детали
        details = "; ".join(violations) if violations else "no violations detected"
        
        return DetectorResult(
            detector_name="Heuristic",
            is_spam=is_spam,
            confidence=confidence,
            details=details,
            processing_time_ms=0.0  # Эвристики работают очень быстро
        )
    
    def _check_repeated_characters(self, text: str) -> str:
        """Проверить повторяющиеся символы"""
        if not text:
            return ""
        
        # Ищем повторяющиеся символы (3+ подряд)
        repeated_pattern = re.compile(r'(.)\1{2,}')
        matches = repeated_pattern.findall(text)
        
        if matches:
            # Группируем по символам
            char_counts = {}
            for char in matches:
                char_counts[char] = char_counts.get(char, 0) + 1
            
            # Формируем описание
            descriptions = []
            for char, count in char_counts.items():
                if count >= 3:
                    descriptions.append(f"'{char}' x{count}")
            
            return ", ".join(descriptions)
        
        return ""
    
    def update_config(self, new_config: Dict[str, Any]):
        """Обновить конфигурацию детектора"""
        self.config.update(new_config)
        
        # Обновляем пороги
        self.max_emoji = self.config.get("max_emoji", self.max_emoji)
        self.max_caps_ratio = self.config.get("max_caps_ratio", self.max_caps_ratio)
        self.max_links = self.config.get("max_links", self.max_links)
        self.max_mentions = self.config.get("max_mentions", self.max_mentions)
        self.min_message_length = self.config.get("min_message_length", self.min_message_length)
        self.spam_threshold = self.config.get("spam_threshold", self.spam_threshold)
    
    def get_config(self) -> Dict[str, Any]:
        """Получить текущую конфигурацию"""
        return {
            "max_emoji": self.max_emoji,
            "max_caps_ratio": self.max_caps_ratio,
            "max_links": self.max_links,
            "max_mentions": self.max_mentions,
            "min_message_length": self.min_message_length,
            "spam_threshold": self.spam_threshold
        }

