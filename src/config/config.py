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
        return self.logging.get("level", "INFO")

def load_config(env: str = None) -> Config:
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
    # Исправление: если admin_users не подставился из env, делаем список пустым
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
        elif not admin_chat_id.strip():
            admin_chat_id = 0
        else:
            try:
                admin_chat_id = int(admin_chat_id)
            except ValueError as e:
                print(f"❌ Ошибка парсинга ADMIN_CHAT_ID: {admin_chat_id} ({e})")
                admin_chat_id = 0
    else:
        admin_chat_id = int(admin_chat_id)

    telegram_config = TelegramConfig(
        token=telegram_data["token"],
        admin_chat_id=admin_chat_id,
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

def _parse_admin_users(admin_users_str: str) -> List[int]:
    """Парсит строку с ID администраторов"""
    if not admin_users_str or not admin_users_str.strip():
        return []
    
    # Если строка содержит запятые, разбиваем по запятым
    if "," in admin_users_str:
        return [int(x.strip()) for x in admin_users_str.split(",") if x.strip()]
    else:
        # Если один ID, создаем список из одного элемента
        return [int(admin_users_str.strip())] if admin_users_str.strip() else []

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

def _create_default_config() -> Config:
    """Создать конфигурацию по умолчанию из переменных окружения"""
    return Config(
        database=DatabaseConfig(
            url=os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/antispam_bot")
        ),
        redis=RedisConfig(
            url=os.getenv("REDIS_URL", "redis://localhost:6379/0")
        ),
        telegram=TelegramConfig(
            token=os.getenv("BOT_TOKEN", ""),
            admin_chat_id=int(os.getenv("ADMIN_CHAT_ID", "0")),
            admin_users=_parse_admin_users(os.getenv("ADMIN_USERS", ""))
        ),
        spam_detection=SpamDetectionConfig(
            heuristic={"spam_threshold": 0.6, "max_emoji": 3},
            ml={"spam_threshold": 0.6, "use_bert": True},
            ensemble={"spam_threshold": 0.6}
        ),
        openai=OpenAIConfig(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model="gpt-4o-mini",
            max_tokens=150,
            enabled=bool(os.getenv("OPENAI_API_KEY"))
        ),
        external_apis={"cas": {"api_url": "https://api.cas.chat/check"}},
        moderation={"auto_ban_threshold": 0.9},
        logging={"level": "INFO"},
        http_server={"enabled": False}
    )
