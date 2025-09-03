#!/usr/bin/env python3
"""
Основная точка входа для антиспам бота
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.config import load_config
from src.lib.clients.postgres_client import PostgresClient
from src.adapter.cache.redis_cache import RedisCache
from src.adapter.repository.message_repository import MessageRepository
from src.adapter.repository.user_repository import UserRepository
from src.adapter.gateway.telegram_gateway import TelegramGateway
from src.adapter.gateway.openai_gateway import OpenAIGateway
from src.adapter.gateway.cas_gateway import CASGateway
from src.adapter.gateway.spamwatch_gateway import SpamWatchGateway
from src.lib.clients.http_client import HttpClient
from src.domain.service.detector.ensemble import EnsembleDetector
from src.domain.usecase.spam_detection.check_message import CheckMessageUseCase
from src.domain.usecase.spam_detection.ban_user import BanUserUseCase
from src.delivery.telegram.bot import AntiSpamBot


async def setup_dependencies(config):
    """Настраивает все зависимости приложения"""
    
    # Настройка логирования
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Создаем клиенты
    postgres_client = PostgresClient(config.database_url)
    redis_cache = RedisCache(config.redis_url)
    http_client = HttpClient()
    
    # Подключаемся к базам данных
    await postgres_client.connect()
    await redis_cache.connect()
    
    # Создаем репозитории
    message_repo = MessageRepository(postgres_client)
    user_repo = UserRepository(postgres_client)
    
    # Создаем spam_samples_repository
    from adapter.repository.spam_samples_repository import SpamSamplesRepository
    spam_samples_repo = SpamSamplesRepository(postgres_client)
    
    # Создаем шлюзы (gateways)
    telegram_gateway = TelegramGateway(None)  # Bot будет передан позже
    
    # OpenAI gateway (если настроен)
    openai_gateway = None
    if config.openai_api_key:
        openai_gateway = OpenAIGateway(
            api_key=config.openai_api_key,
            config={
                "model": config.openai_model,
                "max_tokens": 150,
                "temperature": 0.0
            }
        )
    
    # CAS gateway
    cas_gateway = CASGateway(
        http_client=http_client,
        cache=redis_cache,
        config={
            "cas_api_url": "https://api.cas.chat",
            "timeout": 5,
            "cache_ttl": 3600
        }
    )
    
    # SpamWatch gateway (если настроен)
    spamwatch_gateway = None
    if config.spamwatch_api_key:
        spamwatch_gateway = SpamWatchGateway(
            api_token=config.spamwatch_api_key,
            http_client=http_client,
            cache=redis_cache,
            config={
                "timeout": 5,
                "cache_ttl": 3600
            }
        )
    
    # Создаем детектор спама
    spam_detector = EnsembleDetector()
    spam_detector.add_cas_detector(cas_gateway)
    if spamwatch_gateway:
        spam_detector.add_spamwatch_detector(spamwatch_gateway)
    if openai_gateway:
        spam_detector.add_openai_detector(openai_gateway)
    
    # Настраиваем детектор
    spam_detector.configure({
        "openai_veto": False,  # OpenAI для улучшения детекции, не для veto
        "skip_ml_if_detected": True
    })
    
    # Создаем use cases
    check_message_usecase = CheckMessageUseCase(
        message_repo=message_repo,
        user_repo=user_repo,
        spam_detector=spam_detector,
        spam_threshold=0.6
    )
    
    ban_user_usecase = BanUserUseCase(
        user_repo=user_repo,
        message_repo=message_repo,
        telegram_gateway=telegram_gateway
    )
    
    # Собираем все зависимости
    dependencies = {
        "postgres_client": postgres_client,
        "redis_cache": redis_cache,
        "http_client": http_client,
        "message_repository": message_repo,
        "user_repository": user_repo,
        "spam_samples_repository": spam_samples_repo,
        "telegram_gateway": telegram_gateway,
        "openai_gateway": openai_gateway,
        "cas_gateway": cas_gateway,
        "spamwatch_gateway": spamwatch_gateway,
        "spam_detector": spam_detector,
        "check_message_usecase": check_message_usecase,
        "ban_user_usecase": ban_user_usecase,
        "admin_chat_id": config.admin_chat_id,
    }
    
    return dependencies


async def main():
    """Основная функция приложения"""
    try:
        # Загружаем конфигурацию
        config = load_config()
        
        print(f"🚀 Starting Anti-Spam Bot...")
        print(f"📊 Bot token: {config.bot_token[:20]}...")
        print(f"💾 Database: {config.database_url.split('@')[-1] if '@' in config.database_url else 'SQLite'}")
        print(f"🔑 OpenAI: {'✅ Enabled' if config.openai_api_key else '❌ Disabled'}")
        
        # Настраиваем зависимости
        dependencies = await setup_dependencies(config)
        
        # Создаем и запускаем бота
        bot = AntiSpamBot(
            bot_token=config.bot_token,
            redis_url=config.redis_url,
            dependencies=dependencies
        )
        
        # Устанавливаем bot в telegram_gateway
        dependencies["telegram_gateway"].bot = bot.bot
        
        print("✅ Bot dependencies initialized")
        print("🤖 Starting Telegram bot polling...")
        
        # Запускаем бота
        await bot.start_polling()
        
    except KeyboardInterrupt:
        print("\n⏹️  Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        logging.exception("Fatal error")
        sys.exit(1)
    finally:
        # Очистка ресурсов
        print("🧹 Cleaning up resources...")
        
        # Закрываем соединения если они были созданы
        try:
            if 'dependencies' in locals():
                if dependencies.get("postgres_client"):
                    await dependencies["postgres_client"].disconnect()
                if dependencies.get("redis_cache"):
                    await dependencies["redis_cache"].disconnect()
                if dependencies.get("http_client"):
                    await dependencies["http_client"].close()
        except Exception as e:
            print(f"⚠️  Error during cleanup: {e}")


if __name__ == "__main__":
    # Проверяем наличие необходимых переменных окружения
    required_env_vars = ["BOT_TOKEN"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        print("💡 Copy env.example to .env and fill in the required values")
        sys.exit(1)
    
    # Запускаем приложение
    asyncio.run(main())

