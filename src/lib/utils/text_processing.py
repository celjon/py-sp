"""
Утилиты для обработки текста и извлечения признаков
"""
import re
from typing import Dict, List, Set
from urllib.parse import urlparse


class TextProcessor:
    """Процессор для обработки текста и извлечения признаков"""
    
    def __init__(self):
        # Паттерны для спама (как в tg-spam)
        self.spam_patterns = [
            r'\b(?:earn|make|money|dollars?|cash|income|profit|revenue)\b',
            r'\b(?:work from home|work at home|home based|online job)\b',
            r'\b(?:click here|visit|buy now|order now|limited time)\b',
            r'\b(?:free|freebie|no cost|no charge|100% free)\b',
            r'\b(?:guarantee|guaranteed|promise|assure|ensure)\b',
            r'\b(?:act now|hurry|urgent|immediate|instant)\b',
            r'\b(?:investment|invest|trading|forex|bitcoin|crypto)\b',
            r'\b(?:weight loss|diet|fitness|health|supplement)\b',
            r'\b(?:loan|credit|debt|mortgage|refinance)\b',
            r'\b(?:insurance|coverage|policy|quote|premium)\b',
            r'\b(?:купить|заказать|дешево|скидка|акция|предложение)\b',  # Русские паттерны
            r'\b(?:заработать|деньги|доход|прибыль|бизнес)\b',
        ]
        
        # Спам-фразы (как в tg-spam) - это реальные маркеры спама, а не обычные слова
        self.spam_phrases = {
            'в личку', 'писать в лс', 'пишите в лс', 'в личные сообщения',
            'личных сообщениях', 'заработок удалённо', 'заработок в интернете',
            'заработок в сети', 'для удалённого заработка', 'детали в лс',
            'ищу партнеров', 'написать в лс', 'подробности в личку',
            'заработать деньги', 'быстрый заработок', 'заработок без вложений',
            'работа на дому', 'подработка', 'дополнительный доход',
            'инвестиции', 'криптовалюта', 'бинарные опционы', 'форекс',
            'массаж', 'интим', 'знакомства', 'встречи', 'свидания'
        }
    
    def clean_text(self, text: str) -> str:
        """Очищает текст от лишних символов"""
        if not text:
            return ""
        
        # Убираем лишние пробелы
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Убираем специальные символы, оставляем буквы, цифры, пробелы и основные знаки
        text = re.sub(r'[^\w\s\-.,!?;:()]', '', text)
        
        return text
    
    def extract_features(self, text: str) -> Dict[str, any]:
        """Извлекает признаки из текста"""
        if not text:
            return {}
        
        features = {}
        
        # Базовая статистика
        features['length'] = len(text)
        features['word_count'] = len(text.split())
        
        # Эмодзи
        emoji_pattern = re.compile(r'[^\w\s,.]')
        emojis = emoji_pattern.findall(text)
        features['emoji_count'] = len([e for e in emojis if len(e) == 1])
        
        # Заглавные буквы
        caps_count = sum(1 for c in text if c.isupper())
        features['caps_count'] = caps_count
        features['caps_ratio'] = caps_count / len(text) if text else 0
        
        # Цифры
        digits = re.findall(r'\d', text)
        features['digit_count'] = len(digits)
        features['digit_ratio'] = len(digits) / len(text) if text else 0
        
        # Ссылки
        url_pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
        urls = url_pattern.findall(text)
        features['link_count'] = len(urls)
        
        # Упоминания
        mentions = re.findall(r'@\w+', text)
        features['mention_count'] = len(mentions)
        
        # Хештеги
        hashtags = re.findall(r'#\w+', text)
        features['hashtag_count'] = len(hashtags)
        
        # Восклицательные знаки
        exclamation_count = text.count('!')
        features['exclamation_count'] = exclamation_count
        
        # Повторяющиеся символы
        repeated_chars = 0
        for i in range(len(text) - 2):
            if text[i] == text[i+1] == text[i+2]:
                repeated_chars += 1
        features['repeated_chars'] = repeated_chars
        
        # Спам паттерны (регулярные выражения)
        spam_score = 0
        for pattern in self.spam_patterns:
            matches = re.findall(pattern, text.lower())
            spam_score += len(matches)
        features['spam_pattern_matches'] = spam_score
        
        # Спам-фразы (точные совпадения)
        text_lower = text.lower()
        spam_phrase_count = 0
        for phrase in self.spam_phrases:
            if phrase in text_lower:
                spam_phrase_count += 1
        features['spam_phrase_matches'] = spam_phrase_count
        
        return features
    
    def contains_spam_patterns(self, text: str) -> Dict[str, Dict[str, any]]:
        """Проверяет текст на спам-паттерны и фразы.
        Возвращает словарь категорий с количеством совпадений и найденными элементами.
        """
        if not text:
            return {
                'phrases': {'count': 0, 'found': []},
                'patterns': {'count': 0, 'found': []}
            }
        
        cleaned = text.lower()
        
        # Подсчет спам-фраз (точные вхождения подстрок)
        found_phrases: List[str] = []
        phrase_count = 0
        for phrase in self.spam_phrases:
            if phrase in cleaned:
                found_phrases.append(phrase)
                # Количество вхождений данной фразы
                phrase_count += cleaned.count(phrase)
        
        # Подсчет спам-паттернов по регулярным выражениям
        found_patterns: List[str] = []
        pattern_count = 0
        for pattern in self.spam_patterns:
            matches = re.findall(pattern, cleaned)
            if matches:
                found_patterns.append(pattern)
                pattern_count += len(matches)
        
        # Дополнительно считаем подозрительные паттерны форматирования/символов
        suspicious_count = 0
        for pattern in getattr(self, 'suspicious_patterns', []):
            matches = re.findall(pattern, text or "")
            suspicious_count += len(matches)

        return {
            'phrases': {
                'count': phrase_count,
                'found': found_phrases,
                'ratio': min(phrase_count * 0.3, 1.0) if phrase_count > 0 else 0.0,
            },
            'patterns': {
                'count': pattern_count,
                'found': found_patterns,
                'ratio': min(pattern_count * 0.2, 1.0) if pattern_count > 0 else 0.0,
            },
            'suspicious_patterns': {
                'count': suspicious_count,
                'found': [],
                'ratio': min(suspicious_count * 0.2, 1.0) if suspicious_count > 0 else 0.0,
            },
        }
    
    def is_likely_spam(self, text: str, threshold: float = 0.4) -> bool:
        """Определяет, является ли текст вероятным спамом (как в tg-spam)"""
        features = self.extract_features(text)
        
        # Простая эвристическая оценка (как в tg-spam)
        score = 0.0
        
        # Эмодзи (много эмодзи = подозрительно)
        if features.get('emoji_count', 0) > 2:
            score += 0.3
        
        # Заглавные буквы
        if features.get('caps_ratio', 0) > 0.5:
            score += 0.2
        
        # Ссылки
        if features.get('link_count', 0) > 1:
            score += 0.2
        
        # Спам паттерны (регулярные выражения)
        if features.get('spam_pattern_matches', 0) > 0:
            score += 0.3
        
        # Спам-фразы (точные совпадения)
        if features.get('spam_phrase_matches', 0) > 0:
            score += 0.4  # Высокий вес для точных фраз
        
        # Повторяющиеся символы
        if features.get('repeated_chars', 0) > 1:
            score += 0.1
        
        return score >= threshold
    
    def get_spam_confidence(self, text: str) -> float:
        """Возвращает уверенность в том, что текст является спамом (0.0 - 1.0)"""
        features = self.extract_features(text)
        
        confidence = 0.0
        
        # Эмодзи
        emoji_score = min(features.get('emoji_count', 0) / 5.0, 1.0)
        confidence += emoji_score * 0.2
        
        # Заглавные буквы
        caps_score = min(features.get('caps_ratio', 0) / 0.8, 1.0)
        confidence += caps_score * 0.2
        
        # Ссылки
        link_score = min(features.get('link_count', 0) / 3.0, 1.0)
        confidence += link_score * 0.2
        
        # Спам паттерны
        pattern_score = min(features.get('spam_pattern_matches', 0) / 2.0, 1.0)
        confidence += pattern_score * 0.2
        
        # Спам-фразы (высокий вес)
        phrase_score = min(features.get('spam_phrase_matches', 0) / 1.0, 1.0)
        confidence += phrase_score * 0.3
        
        # Повторяющиеся символы
        repeat_score = min(features.get('repeated_chars', 0) / 3.0, 1.0)
        confidence += repeat_score * 0.1
        
        return min(confidence, 1.0)
