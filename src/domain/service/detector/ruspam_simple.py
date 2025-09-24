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
        self.model: Optional["AutoModelForSequenceClassification"] = None
        self.tokenizer: Optional["AutoTokenizer"] = None
        self.is_loaded = False
        self.is_available = TRANSFORMERS_AVAILABLE

        if not TRANSFORMERS_AVAILABLE:
            raise RuntimeError("❌ КРИТИЧЕСКАЯ ОШИБКА: Transformers не установлен! Выполните: pip install torch transformers")

        # Инициализируем устройство
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[OK] RUSpam доступен, устройство: {self.device}")

        # Загружаем модель сразу при инициализации
        self._load_model_sync()

    def _load_model_sync(self):
        """Синхронная загрузка модели при инициализации"""
        try:
            print(f"📥 Загрузка RUSpam модели: {self.model_name}")

            # Загружаем токенизатор
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)

            # Загружаем модель (spamNS_v1 - регрессионная, 1 выход)
            self.model = (
                AutoModelForSequenceClassification.from_pretrained(
                    self.model_name, num_labels=1, ignore_mismatched_sizes=True
                )
                .to(self.device)
                .eval()
            )

            self.is_loaded = True
            print("[OK] RUSpam модель загружена успешно")

        except Exception as e:
            error_msg = f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить RUSpam модель: {e}"
            print(error_msg)
            print("💡 Проверьте подключение к интернету и доступность Hugging Face Hub")
            raise RuntimeError(error_msg)


    def _clean_text(self, text: str) -> str:
        """Очистка текста для RUSpam модели"""
        # Убираем URL
        text = re.sub(r"http\S+", "", text)
        # Оставляем только русские буквы, цифры и базовые знаки
        text = re.sub(r"[^А-Яа-я0-9 .,!?-]+", " ", text)
        # Нормализуем пробелы и приводим к нижнему регистру
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        return text

    async def classify(self, message: str) -> RUSpamResult:
        """Классификация сообщения на спам"""
        if not self.is_loaded:
            return RUSpamResult(is_spam=False, confidence=0.0, details="RUSpam модель не загружена")

        try:
            # Очищаем текст
            cleaned_text = self._clean_text(message)

            if len(cleaned_text.strip()) < 3:
                return RUSpamResult(
                    is_spam=False, confidence=0.0, details="Текст слишком короткий после очистки"
                )

            # Токенизация
            encoding = self.tokenizer(
                cleaned_text,
                padding="max_length",
                truncation=True,
                max_length=128,
                return_tensors="pt",
            )

            input_ids = encoding["input_ids"].to(self.device)
            attention_mask = encoding["attention_mask"].to(self.device)

            # Предсказание
            with torch.no_grad():
                outputs = self.model(input_ids, attention_mask=attention_mask).logits
                # spamNS_v1 - регрессионная модель с 1 выходом
                confidence = torch.sigmoid(outputs).cpu().numpy()[0][0]
                is_spam = bool(confidence >= 0.5)

            return RUSpamResult(
                is_spam=is_spam,
                confidence=float(confidence),
                details=f"RUSpam spamNS_v1: {'СПАМ' if is_spam else 'НЕ СПАМ'}",
            )

        except Exception as e:
            return RUSpamResult(is_spam=False, confidence=0.0, details=f"Ошибка RUSpam: {str(e)}")
