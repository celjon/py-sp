"""
Production конфигурационные классы
Современная архитектура: CAS + RUSpam + OpenAI (БЕЗ эвристик и ML)
"""

import os
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    url: str
    pool_size: int = 10


@dataclass
class RedisConfig:
    url: str


@dataclass
class TelegramConfig:
    token: str
    admin_chat_id: int
    admin_users: List[int]
    webhook_url: Optional[str] = None
    ngrok_url: Optional[str] = None


@dataclass
class SpamDetectionConfig:
    """
    Современная конфигурация детекции спама
    БЕЗ устаревших heuristic и ml параметров
    """

    ensemble: Dict[str, Any]
    # Дополнительные настройки (опционально)
    ruspam: Optional[Dict[str, Any]] = None


@dataclass
class RUSpamConfig:
    """Конфигурация RUSpam BERT модели"""

    model_name: str = "RUSpam/spamNS_v1"
    min_confidence: float = 0.6
    cache_results: bool = True
    cache_ttl: int = 300


@dataclass
class OpenAIConfig:
    api_key: str
    model: str
    max_tokens: int
    temperature: float = 0.0
    enabled: bool = True
    system_prompt: Optional[str] = None


@dataclass
class APIConfig:
    """Конфигурация публичного API"""

    rate_limit: Dict[str, Any]
    auth: Dict[str, Any]
    features: Dict[str, Any]


@dataclass
class Config:
    """Основная конфигурация системы"""

    database: DatabaseConfig
    redis: RedisConfig
    telegram: TelegramConfig
    spam_detection: SpamDetectionConfig
    openai: OpenAIConfig
    external_apis: Dict[str, Any]
    moderation: Dict[str, Any]
    logging: Dict[str, Any]
    http_server: Dict[str, Any]

    # Новые секции
    ruspam: Optional[RUSpamConfig] = None
    api: Optional[APIConfig] = None
    metrics: Optional[Dict[str, Any]] = None
    performance: Optional[Dict[str, Any]] = None
    security: Optional[Dict[str, Any]] = None

    # Удобные свойства совместимости
    @property
    def bot_token(self) -> str:
        return self.telegram.token

    @property
    def database_url(self) -> str:
        return self.database.url

    @property
    def redis_url(self) -> str:
        return self.redis.url

    @property
    def openai_api_key(self) -> str:
        return self.openai.api_key

    @property
    def admin_chat_id(self) -> int:
        return self.telegram.admin_chat_id

    @property
    def log_level(self) -> str:
        return str(self.logging.get("level", "INFO"))


def load_config(env: Optional[str] = None) -> Config:
    """Загрузить конфигурацию для указанного окружения"""
    # Определяем окружение из переменной среды или по умолчанию
    if env is None:
        env = os.getenv("ENVIRONMENT", "development")

    # Определяем путь к конфигурационному файлу
    config_dir = Path(__file__).parent.parent.parent / "config"
    config_file = config_dir / f"{env}.yaml"

    if not config_file.exists():
        print(f"⚠️ Config file {config_file} not found, using defaults")
        return _create_default_config()

    # Загружаем YAML
    with open(config_file, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    # Заменяем переменные окружения
    config_data = _substitute_env_variables(config_data)

    # Создаем объекты конфигурации
    database_config = DatabaseConfig(**config_data["database"])
    redis_config = RedisConfig(**config_data["redis"])

    telegram_data = config_data["telegram"]
    # Обрабатываем admin_users - может быть строкой из env или списком
    admin_users = telegram_data["admin_users"]
    if isinstance(admin_users, str):
        if admin_users.startswith("${") and admin_users.endswith("}"):
            admin_users = []
        elif not admin_users.strip():
            admin_users = []
        else:
            try:
                if "," in admin_users:
                    admin_users = [int(x.strip()) for x in admin_users.split(",") if x.strip()]
                else:
                    admin_users = [int(admin_users.strip())] if admin_users.strip() else []
            except ValueError as e:
                print(f"❌ Ошибка парсинга ADMIN_USERS: {admin_users} ({e})")
                admin_users = []

    admin_chat_id = telegram_data["admin_chat_id"]
    if isinstance(admin_chat_id, str):
        if admin_chat_id.startswith("${") and admin_chat_id.endswith("}"):
            admin_chat_id = 0
        else:
            try:
                admin_chat_id = int(admin_chat_id)
            except ValueError:
                admin_chat_id = 0

    telegram_config = TelegramConfig(
        token=telegram_data["token"],
        admin_chat_id=admin_chat_id,
        admin_users=admin_users,
        webhook_url=telegram_data.get("webhook_url"),
        ngrok_url=telegram_data.get("ngrok_url"),
    )

    # Современная конфигурация спам-детекции (БЕЗ heuristic и ml)
    spam_detection_config = SpamDetectionConfig(
        ensemble=config_data["spam_detection"]["ensemble"],
        ruspam=config_data["spam_detection"].get("ruspam"),
    )

    # OpenAI конфигурация
    openai_data = config_data["openai"]
    openai_config = OpenAIConfig(
        api_key=openai_data["api_key"],
        model=openai_data["model"],
        max_tokens=openai_data["max_tokens"],
        temperature=openai_data.get("temperature", 0.0),
        enabled=openai_data.get("enabled", True),
        system_prompt=openai_data.get("system_prompt"),
    )

    # RUSpam конфигурация (если есть)
    ruspam_config = None
    if "ruspam" in config_data:
        ruspam_config = RUSpamConfig(**config_data["ruspam"])

    # API конфигурация (если есть)
    api_config = None
    if "api" in config_data:
        api_config = APIConfig(**config_data["api"])

    return Config(
        database=database_config,
        redis=redis_config,
        telegram=telegram_config,
        spam_detection=spam_detection_config,
        openai=openai_config,
        external_apis=config_data.get("external_apis", {}),
        moderation=config_data.get("moderation", {}),
        logging=config_data.get("logging", {}),
        http_server=config_data.get("http_server", {}),
        ruspam=ruspam_config,
        api=api_config,
        metrics=config_data.get("metrics"),
        performance=config_data.get("performance"),
        security=config_data.get("security"),
    )


def _substitute_env_variables(data: Any) -> Any:
    """Заменяет ${VAR} на значения переменных окружения"""
    if isinstance(data, dict):
        return {key: _substitute_env_variables(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_variables(item) for item in data]
    elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        env_var = data[2:-1]
        return os.getenv(env_var, data)
    else:
        return data


def _parse_admin_users(admin_users_str: str) -> List[int]:
    """Парсит строку с admin users в список int"""
    if not admin_users_str or admin_users_str.startswith("${"):
        return []

    try:
        if "," in admin_users_str:
            return [int(x.strip()) for x in admin_users_str.split(",") if x.strip()]
        else:
            return [int(admin_users_str.strip())] if admin_users_str.strip() else []
    except ValueError:
        print(f"⚠️ Неверный формат ADMIN_USERS: {admin_users_str}")
        return []


def _create_default_config() -> Config:
    """Создать конфигурацию по умолчанию из переменных окружения"""
    return Config(
        database=DatabaseConfig(url=os.getenv("DATABASE_URL") or ""),
        redis=RedisConfig(url=os.getenv("REDIS_URL") or ""),
        telegram=TelegramConfig(
            token=os.getenv("BOT_TOKEN", ""),
            admin_chat_id=int(os.getenv("ADMIN_CHAT_ID", "0")),
            admin_users=_parse_admin_users(os.getenv("ADMIN_USERS", "")),
            webhook_url=os.getenv("WEBHOOK_URL"),
            ngrok_url=os.getenv("NGROK_URL"),
        ),
        # СОВРЕМЕННАЯ конфигурация детекции (БЕЗ heuristic и ml!)
        spam_detection=SpamDetectionConfig(
            ensemble={
                "spam_threshold": 0.6,
                "high_confidence_threshold": 0.8,
                "auto_ban_threshold": 0.85,
                "use_ruspam": True,
                "ruspam_min_length": 10,
                "openai_min_length": 5,
                "use_openai_fallback": True,
            }
        ),
        openai=OpenAIConfig(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model="gpt-4o-mini",
            max_tokens=150,
            temperature=0.0,
            enabled=bool(os.getenv("OPENAI_API_KEY")),
        ),
        external_apis={
            "cas": {"api_url": os.getenv("CAS_API_URL"), "timeout": 5, "cache_ttl": 3600}
        },
        moderation={"auto_ban_threshold": 0.85, "auto_restrict_threshold": 0.70},
        logging={"level": "INFO"},
        http_server={"enabled": True, "host": "0.0.0.0", "port": 8080},
        ruspam=RUSpamConfig(),
        api=APIConfig(
            rate_limit={"default_requests_per_minute": 60, "default_requests_per_day": 5000},
            auth={
                "jwt_secret": os.getenv("JWT_SECRET", "dev_secret_change_in_production"),
                "access_token_expire_minutes": 30,
            },
            features={"batch_detection": True, "usage_analytics": True},
        ),
    )
