import os
import yaml
from typing import Dict, Any, List
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
    heuristic: Dict[str, Any]
    ml: Dict[str, Any]
    ensemble: Dict[str, Any]

@dataclass
class OpenAIConfig:
    api_key: str
    model: str
    max_tokens: int
    enabled: bool

@dataclass
class Config:
    database: DatabaseConfig
    redis: RedisConfig
    telegram: TelegramConfig
    spam_detection: SpamDetectionConfig
    openai: OpenAIConfig
    external_apis: Dict[str, Any]
    moderation: Dict[str, Any]
    logging: Dict[str, Any]
    http_server: Dict[str, Any]

def load_config(env: str = "development") -> Config:
    """Загрузить конфигурацию для указанного окружения"""
    
    # Определяем путь к конфигурационному файлу
    config_dir = Path(__file__).parent.parent.parent / "config"
    config_file = config_dir / f"{env}.yaml"
    
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file {config_file} not found")
    
    # Загружаем YAML
    with open(config_file, 'r', encoding='utf-8') as f:
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
        admin_users = [int(x.strip()) for x in admin_users.split(",") if x.strip()]
    
    telegram_config = TelegramConfig(
        token=telegram_data["token"],
        admin_chat_id=int(telegram_data["admin_chat_id"]),
        admin_users=admin_users
    )
    
    spam_detection_config = SpamDetectionConfig(**config_data["spam_detection"])
    openai_config = OpenAIConfig(**config_data["openai"])
    
    return Config(
        database=database_config,
        redis=redis_config,
        telegram=telegram_config,
        spam_detection=spam_detection_config,
        openai=openai_config,
        external_apis=config_data["external_apis"],
        moderation=config_data["moderation"],
        logging=config_data["logging"],
        http_server=config_data["http_server"]
    )

def _substitute_env_variables(data: Any) -> Any:
    """Рекурсивно заменяет ${VAR} на значения переменных окружения"""
    if isinstance(data, dict):
        return {key: _substitute_env_variables(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_variables(item) for item in data]
    elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        env_var = data[2:-1]
        return os.getenv(env_var, data)
    else:
        return data
