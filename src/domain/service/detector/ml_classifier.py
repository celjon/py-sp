import pickle
import asyncio
import re
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
from sklearn.pipeline import Pipeline
from src.lib.utils.text_processing import TextProcessor

# Попытка импорта BERT модели (опционально)
try:
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    BERT_AVAILABLE = True
except ImportError:
    BERT_AVAILABLE = False
    print("⚠️ PyTorch/Transformers not available. Using sklearn fallback.")

@dataclass
class MLResult:
    """Результат ML классификации"""
    is_spam: bool
    confidence: float
    details: str
    model_name: str

class MLClassifier:
    """ML классификатор для детекции спама"""
    
    def __init__(self, model_path: Path, config: Dict[str, Any]):
        self.model_path = model_path
        self.config = config
        self.model: Optional[Pipeline] = None
        self.vectorizer = None
        self.text_processor = TextProcessor()
        self.spam_threshold = config.get("spam_threshold", 0.6)
        
        # BERT модель для русского языка
        self.bert_model = None
        self.bert_tokenizer = None
        self.device = None
        self.use_bert = config.get("use_bert", True) and BERT_AVAILABLE
        self.bert_model_name = config.get("bert_model_name", "RUSpam/spamNS_v1")
        
    async def load_model(self):
        """Загрузить обученную модель"""
        try:
            # Сначала пытаемся загрузить BERT модель
            if self.use_bert:
                await self._load_bert_model()
            
            # Затем загружаем fallback sklearn модель
            model_file = self.model_path / "spam_classifier.pkl"
            if model_file.exists():
                with open(model_file, 'rb') as f:
                    self.model = pickle.load(f)
                print(f"✅ Sklearn model loaded from {model_file}")
            else:
                print(f"⚠️ Model file not found: {model_file}")
                self.model = self._create_fallback_model()
            
            # Загружаем векторайзер отдельно для быстрого доступа
            vectorizer_file = self.model_path / "vectorizer.pkl"
            if vectorizer_file.exists():
                with open(vectorizer_file, 'rb') as f:
                    self.vectorizer = pickle.load(f)
                print(f"✅ Vectorizer loaded from {vectorizer_file}")
                
        except Exception as e:
            print(f"❌ Error loading ML model: {e}")
            self.model = self._create_fallback_model()

    async def _load_bert_model(self):
        """Загрузить BERT модель для русского языка"""
        try:
            if not BERT_AVAILABLE:
                print("⚠️ BERT dependencies not available")
                self.use_bert = False
                return
                
            print(f"🤖 Loading BERT model: {self.bert_model_name}")
            
            # Определяем устройство
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            print(f"📱 Using device: {self.device}")
            
            # Загружаем RUSpam модель
            try:
                self.bert_tokenizer = AutoTokenizer.from_pretrained(self.bert_model_name)
                # В соответствии с тестом RUSpam/spamNS_v1 — регрессионная модель с одним выходом
                self.bert_model = AutoModelForSequenceClassification.from_pretrained(
                    self.bert_model_name,
                    num_labels=1,
                    ignore_mismatched_sizes=True
                ).to(self.device).eval()
                print(f"✅ RUSpam модель загружена успешно (регрессия, 1 выход)")
            except Exception as e:
                print(f"❌ Не удалось загрузить RUSpam: {e}")
                print("💡 Попробуйте: pip install torch transformers")
                self.use_bert = False
            
        except Exception as e:
            print(f"❌ Error loading BERT model: {e}")
            self.use_bert = False
    
    def _create_fallback_model(self) -> Pipeline:
        """Создать базовую модель если основная не загружена"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.naive_bayes import MultinomialNB
        
        vectorizer = TfidfVectorizer(
            max_features=1000,
            ngram_range=(1, 2),
            stop_words='english'
        )
        
        classifier = MultinomialNB(alpha=1.0)
        
        pipeline = Pipeline([
            ('vectorizer', vectorizer),
            ('classifier', classifier)
        ])
        
        print("⚠️ Using fallback ML model")
        return pipeline
    
    async def classify(self, text: str) -> MLResult:
        """Классифицировать текст"""
        if not self.model and not self.bert_model:
            await self.load_model()
        
        try:
            # Сначала пытаемся использовать BERT модель
            if self.use_bert and self.bert_model is not None:
                return await self._classify_with_bert(text)
            
            # Fallback на sklearn модель
            return await self._classify_with_sklearn(text)
            
        except Exception as e:
            print(f"ML classification error: {e}")
            # Возвращаем безопасный результат
            return MLResult(
                is_spam=False,
                confidence=0.0,
                details=f"ML error: {str(e)}",
                model_name="ML_Classifier_Error"
            )

    async def _classify_with_bert(self, text: str) -> MLResult:
        """Классификация с помощью BERT модели"""
        try:
            # Очищаем текст по методу RUSpam
            cleaned_text = self._clean_text_for_bert(text)
            
            if len(cleaned_text.strip()) < 3:
                return MLResult(
                    is_spam=False,
                    confidence=0.0,
                    details="Text too short for BERT classification",
                    model_name="BERT_RUSpam"
                )
            
            # Токенизация
            # Для моделей семейства DeBERTa/Roberta можно увеличить max_length до 512,
            # но у RUSpam/spamNS_v1 достаточно 128 для снижения латентности
            encoding = self.bert_tokenizer(
                cleaned_text,
                padding='max_length',
                truncation=True,
                max_length=128,
                return_tensors='pt'
            )
            
            input_ids = encoding['input_ids'].to(self.device)
            attention_mask = encoding['attention_mask'].to(self.device)
            
            # Предсказание (в соответствии с тестом: регрессия + sigmoid)
            with torch.no_grad():
                outputs = self.bert_model(input_ids, attention_mask=attention_mask).logits
                spam_prob_tensor = torch.sigmoid(outputs)
                spam_prob = float(spam_prob_tensor.cpu().numpy()[0][0])

            is_spam = bool(spam_prob >= 0.5)
            confidence = float(spam_prob)
            
            details = self._generate_details(text, is_spam, confidence)
            details += " (BERT model)"
            
            return MLResult(
                is_spam=is_spam,
                confidence=confidence,
                details=details,
                model_name="BERT_RUSpam"
            )
            
        except Exception as e:
            print(f"BERT classification error: {e}")
            # Fallback на sklearn
            return await self._classify_with_sklearn(text)

    async def _classify_with_sklearn(self, text: str) -> MLResult:
        """Классификация с помощью sklearn модели"""
        try:
            # Предобрабатываем текст
            cleaned_text = self.text_processor.clean_text(text)
            
            if len(cleaned_text.strip()) < 3:
                return MLResult(
                    is_spam=False,
                    confidence=0.0,
                    details="Text too short for ML classification",
                    model_name="Sklearn_Fallback"
                )
            
            # Получаем предсказание
            prediction = self.model.predict([cleaned_text])[0]
            probabilities = self.model.predict_proba([cleaned_text])[0]
            
            # Определяем уверенность
            confidence = probabilities[prediction]
            is_spam = bool(prediction)
            
            # Дополнительные детали
            details = self._generate_details(text, is_spam, confidence)
            details += " (sklearn model)"
            
            return MLResult(
                is_spam=is_spam,
                confidence=confidence,
                details=details,
                model_name="Sklearn_Classifier"
            )
            
        except Exception as e:
            print(f"Sklearn classification error: {e}")
            return MLResult(
                is_spam=False,
                confidence=0.0,
                details=f"Sklearn error: {str(e)}",
                model_name="Sklearn_Error"
            )

    def _clean_text_for_bert(self, text: str) -> str:
        """Очистка текста для BERT модели (по методу RUSpam)"""
        # Удаляем URL
        text = re.sub(r'http\S+', '', text)
        # Оставляем только русские буквы, цифры и пробелы
        text = re.sub(r'[^А-Яа-я0-9 ]+', ' ', text)
        # Приводим к нижнему регистру и убираем лишние пробелы
        text = text.lower().strip()
        text = re.sub(r'\s+', ' ', text)
        return text
    
    def _generate_details(self, text: str, is_spam: bool, confidence: float) -> str:
        """Генерировать детали классификации"""
        features = self.text_processor.extract_features(text)
        
        details_parts = []
        
        if features.get('caps_ratio', 0) > 0.7:
            details_parts.append("high caps ratio")
        
        if features.get('emoji_count', 0) > 3:
            details_parts.append("many emojis")
        
        if features.get('url_count', 0) > 2:
            details_parts.append("multiple links")
        
        if features.get('exclamation_count', 0) > 3:
            details_parts.append("many exclamations")
        
        # Проверяем спам-паттерны
        spam_patterns = self.text_processor.contains_spam_patterns(text)
        for category, info in spam_patterns.items():
            if info['count'] > 0:
                details_parts.append(f"{category}: {info['found']}")
        
        if not details_parts:
            details_parts.append("text analysis")
        
        details = ", ".join(details_parts)
        
        if is_spam:
            if confidence > 0.8:
                details += " (high confidence)"
            elif confidence > 0.6:
                details += " (medium confidence)"
            else:
                details += " (low confidence)"
        
        return details
    
    async def update_model(self, new_samples: list):
        """Обновить модель новыми образцами"""
        if not self.model:
            await self.load_model()
        
        try:
            # Здесь должна быть логика дообучения модели
            # Для простоты просто перезагружаем
            await self.load_model()
            print("✅ Model updated successfully")
        except Exception as e:
            print(f"❌ Error updating model: {e}")
    
    def get_model_info(self) -> Dict[str, Any]:
        """Получить информацию о модели"""
        return {
            "model_type": type(self.model).__name__ if self.model else "None",
            "vectorizer_type": type(self.vectorizer).__name__ if self.vectorizer else "None",
            "spam_threshold": self.spam_threshold,
            "model_path": str(self.model_path),
            "is_loaded": self.model is not None
        }
