"""
Production конфигурационные классы
Современная архитектура: CAS + RUSpam + BotHub (БЕЗ эвристик и ML)
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


@dataclass
class SpamDetectionConfig:
    """
    Современная конфигурация детекции спама
    БЕЗ устаревших heuristic и ml параметров
    """

    ensemble: Dict[str, Any]
    ruspam: Optional[Dict[str, Any]] = None


@dataclass
class RUSpamConfig:
    """Конфигурация RUSpam BERT модели"""

    model_name: str = "RUSpam/spamNS_v1"
    min_confidence: float = 0.6
    cache_results: bool = True
    cache_ttl: int = 300


@dataclass
class BotHubConfig:
    """Конфигурация BotHub API"""
    
    model: str = "gpt-5-nano"
    max_tokens: int = 300
    temperature: float = 0.0
    timeout: float = 60.0
    max_retries: int = 2
    retry_delay: float = 1.0


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
    bothub: BotHubConfig
    external_apis: Dict[str, Any]
    moderation: Dict[str, Any]
    logging: Dict[str, Any]
    http_server: Dict[str, Any]

    ruspam: Optional[RUSpamConfig] = None
    api: Optional[APIConfig] = None
    metrics: Optional[Dict[str, Any]] = None
    performance: Optional[Dict[str, Any]] = None
    security: Optional[Dict[str, Any]] = None

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
    def openrouter_api_key(self) -> str:
        return self.openrouter.api_key

    @property
    def admin_chat_id(self) -> int:
        return self.telegram.admin_chat_id

    @property
    def log_level(self) -> str:
        return str(self.logging.get("level", "INFO"))


def load_config(env: Optional[str] = None) -> Config:
    """Загрузить конфигурацию для указанного окружения"""
    if env is None:
        env = os.getenv("ENVIRONMENT", "development")

    config_dir = Path(__file__).parent.parent.parent / "config"
    config_file = config_dir / f"{env}.yaml"

    if not config_file.exists():
        return _create_default_config()

    with open(config_file, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    config_data = _substitute_env_variables(config_data)

    database_config = DatabaseConfig(**config_data["database"])
    redis_config = RedisConfig(**config_data["redis"])

    telegram_data = config_data["telegram"]
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
    )

    spam_detection_config = SpamDetectionConfig(
        ensemble=config_data["spam_detection"]["ensemble"],
        ruspam=config_data["spam_detection"].get("ruspam"),
    )

    bothub_data = config_data.get("bothub", {})
    bothub_config = BotHubConfig(
        model=bothub_data.get("model", "gpt-5-nano"),
        max_tokens=bothub_data.get("max_tokens", 150),
        temperature=bothub_data.get("temperature", 0.0),
        timeout=bothub_data.get("timeout", 60.0),
        max_retries=bothub_data.get("max_retries", 2),
        retry_delay=bothub_data.get("retry_delay", 1.0),
    )

    ruspam_config = None
    if "ruspam" in config_data:
        ruspam_config = RUSpamConfig(**config_data["ruspam"])

    api_config = None
    if "api" in config_data:
        api_config = APIConfig(**config_data["api"])

    return Config(
        database=database_config,
        redis=redis_config,
        telegram=telegram_config,
        spam_detection=spam_detection_config,
        bothub=bothub_config,
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
        ),
        spam_detection=SpamDetectionConfig(
            ensemble={
                "spam_threshold": 0.6,
                "high_confidence_threshold": 0.8,
                "auto_ban_threshold": 0.85,
                "use_ruspam": True,
                "ruspam_min_length": 10,
                "bothub_min_length": 5,
                "use_bothub_fallback": True,
            }
        ),
        bothub=BotHubConfig(
            model="gpt-5-nano",
            max_tokens=150,
            temperature=0.0,
            timeout=60.0,
            max_retries=2,
            retry_delay=1.0,
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
