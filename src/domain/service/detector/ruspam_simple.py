import re
import asyncio
from typing import Optional
from dataclasses import dataclass

try:
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


@dataclass
class RUSpamResult:
    is_spam: bool
    confidence: float
    details: str


class RUSpamSimpleClassifier:
    """RUSpam детектор через Hugging Face transformers (только spamNS_v1)"""

    def __init__(self):
        self.model_name = "RUSpam/spamNS_v1"
        self.device = None
        self.model: Optional['AutoModelForSequenceClassification'] = None
        self.tokenizer: Optional['AutoTokenizer'] = None
        self.is_loaded = False
        self.is_available = TRANSFORMERS_AVAILABLE

        if TRANSFORMERS_AVAILABLE:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            print(f"✅ RUSpam доступен, устройство: {self.device}")
        else:
            print("❌ Transformers не установлен: pip install torch transformers")

    async def _load_model(self):
        """Загрузка модели RUSpam/spamNS_v1"""
        if self.is_loaded or not self.is_available:
            return

        try:
            print(f"📥 Загрузка RUSpam модели: {self.model_name}")

            loop = asyncio.get_event_loop()

            # Загружаем токенизатор
            self.tokenizer = await loop.run_in_executor(
                None,
                AutoTokenizer.from_pretrained,
                self.model_name
            )

            # Загружаем модель (spamNS_v1 - регрессионная, 1 выход)
            def _load_model():
                return AutoModelForSequenceClassification.from_pretrained(
                    self.model_name,
                    num_labels=1,
                    ignore_mismatched_sizes=True
                ).to(self.device).eval()

            self.model = await loop.run_in_executor(None, _load_model)

            self.is_loaded = True
            print("✅ RUSpam модель загружена успешно")
            
        except Exception as e:
            print(f"❌ Ошибка загрузки RUSpam: {e}")
            print("💡 Попробуйте: pip install torch transformers")
            self.is_loaded = False

    def _clean_text(self, text: str) -> str:
        """Очистка текста для RUSpam модели"""
        # Убираем URL
        text = re.sub(r'http\S+', '', text)
        # Оставляем только русские буквы, цифры и базовые знаки
        text = re.sub(r'[^А-Яа-я0-9 .,!?-]+', ' ', text)
        # Нормализуем пробелы и приводим к нижнему регистру
        text = text.lower().strip()
        text = re.sub(r'\s+', ' ', text)
        return text

    async def classify(self, message: str) -> RUSpamResult:
        """Классификация сообщения на спам"""
        if not self.is_available:
            return RUSpamResult(
                is_spam=False,
                confidence=0.0,
                details="Transformers не установлен"
            )

        if not self.is_loaded:
            await self._load_model()

        if not self.is_loaded:
            return RUSpamResult(
                is_spam=False,
                confidence=0.0,
                details="RUSpam модель не загружена"
            )

        try:
            # Очищаем текст
            cleaned_text = self._clean_text(message)

            if len(cleaned_text.strip()) < 3:
                return RUSpamResult(
                    is_spam=False,
                    confidence=0.0,
                    details="Текст слишком короткий после очистки"
                )

            # Токенизация
            encoding = self.tokenizer(
                cleaned_text,
                padding='max_length',
                truncation=True,
                max_length=128,
                return_tensors='pt'
            )

            input_ids = encoding['input_ids'].to(self.device)
            attention_mask = encoding['attention_mask'].to(self.device)

            # Предсказание
            with torch.no_grad():
                outputs = self.model(input_ids, attention_mask=attention_mask).logits
                # spamNS_v1 - регрессионная модель с 1 выходом
                confidence = torch.sigmoid(outputs).cpu().numpy()[0][0]
                is_spam = bool(confidence >= 0.5)

            return RUSpamResult(
                is_spam=is_spam,
                confidence=float(confidence),
                details=f"RUSpam spamNS_v1: {'СПАМ' if is_spam else 'НЕ СПАМ'}"
            )

        except Exception as e:
            return RUSpamResult(
                is_spam=False,
                confidence=0.0,
                details=f"Ошибка RUSpam: {str(e)}"
            )
