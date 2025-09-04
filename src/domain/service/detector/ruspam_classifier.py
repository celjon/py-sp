import re
import asyncio
from typing import Optional
from dataclasses import dataclass

try:
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    TRANSFORMERS_AVAILABLE = True
except Exception:
    TRANSFORMERS_AVAILABLE = False


@dataclass
class RUSpamResult:
    """Результат RUSpam классификации"""
    is_spam: bool
    confidence: float
    details: str


class RUSpamClassifier:
    """RUSpam классификатор для русскоязычного спама"""

    def __init__(self):
        self.model_name = 'RUSpam/spamNS_v1'
        self.device = None
        self.model: Optional['AutoModelForSequenceClassification'] = None
        self.tokenizer: Optional['AutoTokenizer'] = None
        self.is_loaded = False

        if TRANSFORMERS_AVAILABLE:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            print(f"🤖 RUSpam will use device: {self.device}")
        else:
            print("⚠️ Transformers not available. Install torch and transformers to enable RUSpam.")

    async def load_model(self):
        """Асинхронная загрузка модели"""
        if self.is_loaded:
            return

        if not TRANSFORMERS_AVAILABLE:
            print("⚠️ Cannot load RUSpam: transformers not installed")
            return

        try:
            print(f"📥 Loading RUSpam model: {self.model_name}")

            loop = asyncio.get_event_loop()

            # Загружаем токенизатор
            self.tokenizer = await loop.run_in_executor(
                None,
                AutoTokenizer.from_pretrained,
                self.model_name
            )

            # Загружаем модель
            def _load_model():
                return AutoModelForSequenceClassification.from_pretrained(
                    self.model_name,
                    num_labels=1
                ).to(self.device).eval()

            self.model = await loop.run_in_executor(None, _load_model)

            self.is_loaded = True
            print("✅ RUSpam model loaded successfully")
        except Exception as e:
            print(f"❌ Failed to load RUSpam model: {e}")
            print("💡 Try: pip install torch transformers")
            self.is_loaded = False

    def clean_text(self, text: str) -> str:
        """Очистка текста по методике RUSpam"""
        text = re.sub(r'http\S+', '', text)
        text = re.sub(r'[^А-Яа-я0-9 ]+', ' ', text)
        text = text.lower().strip()
        text = re.sub(r'\s+', ' ', text)
        return text

    async def classify(self, message: str) -> RUSpamResult:
        """Классификация сообщения"""
        if not self.is_loaded:
            await self.load_model()

        if not self.is_loaded:
            return RUSpamResult(
                is_spam=False,
                confidence=0.0,
                details="RUSpam model not available"
            )

        try:
            cleaned_message = self.clean_text(message)

            if len(cleaned_message.strip()) < 3:
                return RUSpamResult(
                    is_spam=False,
                    confidence=0.0,
                    details="Text too short after cleaning"
                )

            encoding = self.tokenizer(
                cleaned_message,
                padding='max_length',
                truncation=True,
                max_length=128,
                return_tensors='pt'
            )

            input_ids = encoding['input_ids'].to(self.device)
            attention_mask = encoding['attention_mask'].to(self.device)

            with torch.no_grad():
                outputs = self.model(input_ids, attention_mask=attention_mask).logits
                pred = torch.sigmoid(outputs).cpu().numpy()[0][0]

            is_spam = bool(pred >= 0.5)
            confidence = float(pred)
            details = f"RUSpam confidence: {confidence:.3f}"
            if len(cleaned_message) != len(message):
                details += f" (cleaned: '{cleaned_message[:50]}...')"

            return RUSpamResult(
                is_spam=is_spam,
                confidence=confidence,
                details=details
            )

        except Exception as e:
            print(f"RUSpam classification error: {e}")
            return RUSpamResult(
                is_spam=False,
                confidence=0.0,
                details=f"RUSpam error: {str(e)}"
            )



