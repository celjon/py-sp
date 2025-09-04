import asyncio
from dataclasses import dataclass


@dataclass
class RUSpamResult:
    is_spam: bool
    confidence: float
    details: str


class RUSpamSimpleClassifier:
    """Упрощенный RUSpam через ruSpamLib (по pip-документации)"""

    def __init__(self):
        self.is_available = False
        self._check_availability()

    def _check_availability(self):
        try:
            import ruSpamLib  # noqa: F401
            self.is_available = True
            print("✅ ruSpamLib доступна")
        except ImportError:
            print("❌ ruSpamLib не установлена: pip install ruSpamLib")
            self.is_available = False

    async def classify(self, message: str) -> RUSpamResult:
        """Классификация через ruSpamLib"""
        if not self.is_available:
            return RUSpamResult(
                is_spam=False,
                confidence=0.0,
                details="ruSpamLib not available",
            )

        try:
            from ruSpamLib import is_spam

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: is_spam(message, model_name="spamNS_v1"),
            )
            # ruSpamLib может возвращать bool или (bool, confidence)
            if isinstance(result, tuple) and len(result) >= 2:
                pred, conf = bool(result[0]), float(result[1])
            else:
                pred, conf = bool(result), (0.8 if result else 0.2)

            return RUSpamResult(
                is_spam=pred,
                confidence=conf,
                details=f"ruSpamLib prediction: {'SPAM' if pred else 'HAM'}",
            )

        except Exception as e:
            return RUSpamResult(
                is_spam=False,
                confidence=0.0,
                details=f"ruSpamLib error: {str(e)}",
            )


