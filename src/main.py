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
    
    print("🔧 Настройка зависимостей...")
    
    # Создаем клиенты
    postgres_client = PostgresClient(config.database_url)
    redis_cache = RedisCache(config.redis_url)
    http_client = HttpClient()
    
    # Подключаемся к базам данных
    print("📊 Подключение к базам данных...")
    await postgres_client.connect()
    await redis_cache.connect()
    
    # Создаем репозитории
    message_repo = MessageRepository(postgres_client)
    user_repo = UserRepository(postgres_client)
    
    # Создаем spam_samples_repository
    from src.adapter.repository.spam_samples_repository import SpamSamplesRepository
    spam_samples_repo = SpamSamplesRepository(postgres_client)
    
    # Создаем шлюзы (gateways)
    telegram_gateway = TelegramGateway(None)  # Bot будет передан позже
    
    # OpenAI gateway (если настроен)
    openai_gateway = None
    if config.openai_api_key:
        print("🤖 Инициализация OpenAI...")
        openai_gateway = OpenAIGateway(
            api_key=config.openai_api_key,
            config={
                "model": config.openai.model,
                "max_tokens": config.openai.max_tokens,
                "temperature": 0.0
            }
        )
    else:
        print("⚠️ OpenAI API ключ не настроен")
    
    # CAS gateway
    print("🛡️ Инициализация CAS...")
    cas_gateway = CASGateway(
        http_client=http_client,
        cache=redis_cache,
        config={
            "cas_api_url": config.external_apis.get("cas", {}).get("api_url", "https://api.cas.chat"),
            "timeout": config.external_apis.get("cas", {}).get("timeout", 5),
            "cache_ttl": config.external_apis.get("cas", {}).get("cache_ttl", 3600)
        }
    )
    
    # Создаем ансамблевый детектор спама
    print("🔍 Инициализация детекторов спама...")
    ensemble_config = config.spam_detection.ensemble
    ensemble_config.update({
        "heuristic": config.spam_detection.heuristic,
        "use_ruspam": config.spam_detection.get("use_ruspam", True),
        "ruspam_min_length": config.spam_detection.get("ruspam_min_length", 10)
    })
    
    spam_detector = EnsembleDetector(ensemble_config)
    
    # Добавляем CAS детектор
    spam_detector.add_cas_detector(cas_gateway)
    print("✅ CAS детектор добавлен")
    
    # Добавляем RUSpam детектор
    try:
        spam_detector.add_ruspam_detector()
        print("✅ RUSpam детектор добавлен")
    except Exception as e:
        print(f"⚠️ RUSpam детектор не загружен: {e}")
    
    # Добавляем ML детектор (если доступен)
    ml_config = config.spam_detection.get("ml", {})
    if ml_config.get("enabled", True):
        try:
            model_path = ml_config.get("model_path", "models")
            spam_detector.add_ml_detector(model_path, ml_config)
            print("✅ ML детектор добавлен")
        except Exception as e:
            print(f"⚠️ ML детектор не загружен: {e}")
    
    # Добавляем OpenAI детектор
    if openai_gateway:
        spam_detector.add_openai_detector(openai_gateway)
        print("✅ OpenAI детектор добавлен")
    
    # Настраиваем детектор
    spam_detector.configure({
        "openai_veto": ensemble_config.get("openai_veto", False),
        "skip_ml_if_detected": ensemble_config.get("skip_ml_if_detected", True),
        "spam_threshold": ensemble_config.get("spam_threshold", 0.6),
        "high_confidence_threshold": ensemble_config.get("high_confidence_threshold", 0.8)
    })
    
    # Создаем use cases
    print("📋 Инициализация use cases...")
    check_message_usecase = CheckMessageUseCase(
        message_repo=message_repo,
        user_repo=user_repo,
        spam_detector=spam_detector,
        spam_threshold=ensemble_config.get("spam_threshold", 0.6)
    )
    
    ban_user_usecase = BanUserUseCase(
        user_repo=user_repo,
        message_repo=message_repo,
        telegram_gateway=telegram_gateway
    )
    
    # Проверяем состояние детекторов
    print("🔍 Проверка состояния детекторов...")
    health = await spam_detector.health_check()
    available_detectors = await spam_detector.get_available_detectors()
    
    print(f"📊 Состояние системы: {health['status']}")
    print(f"🔧 Доступные детекторы: {', '.join(available_detectors)}")
    
    for detector_name, detector_health in health["detectors"].items():
        status = "✅" if detector_health["status"] == "healthy" else "⚠️" if detector_health["status"] == "degraded" else "❌"
        print(f"   {status} {detector_name}: {detector_health['status']}")
        if "error" in detector_health:
            print(f"      Ошибка: {detector_health['error']}")
    
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
        "spam_detector": spam_detector,
        "check_message_usecase": check_message_usecase,
        "ban_user_usecase": ban_user_usecase,
        "admin_chat_id": config.admin_chat_id,
        "config": config,
        "health": health
    }
    
    return dependencies


async def run_telegram_bot(config, dependencies):
    """Запуск Telegram бота"""
    print("🤖 Запуск Telegram бота...")
    
    # Создаем и запускаем бота
    bot = AntiSpamBot(
        bot_token=config.bot_token,
        redis_url=config.redis_url,
        dependencies=dependencies
    )
    
    # Устанавливаем bot в telegram_gateway
    dependencies["telegram_gateway"].bot = bot.bot
    
    print("✅ Telegram bot инициализирован")
    print("🔄 Запуск polling...")
    
    # Запускаем бота
    await bot.start_polling()


async def run_http_server(config, dependencies):
    """Запуск HTTP сервера"""
    print("🌐 Запуск HTTP сервера...")
    
    try:
        import uvicorn
        from src.delivery.http.app import create_app
        
        # Создаем FastAPI приложение с зависимостями
        app = create_app(dependencies)
        
        # Настройки сервера из конфигурации
        server_config = uvicorn.Config(
            app=app,
            host=config.http_server.get("host", "0.0.0.0"),
            port=config.http_server.get("port", 8080),
            workers=1,  # Для async приложения используем 1 воркер
            loop="asyncio",
            log_level=config.log_level.lower(),
            access_log=True
        )
        
        print(f"🌐 HTTP сервер запускается на {server_config.host}:{server_config.port}")
        print(f"📚 API документация будет доступна на http://{server_config.host}:{server_config.port}/docs")
        
        # Создаем и запускаем сервер
        server = uvicorn.Server(server_config)
        await server.serve()
        
    except ImportError:
        print("❌ uvicorn не установлен. Установите: pip install uvicorn")
        print("⚠️ HTTP сервер не может быть запущен")
        return
    except Exception as e:
        print(f"❌ Ошибка запуска HTTP сервера: {e}")
        raise


async def main():
    """Основная функция приложения"""
    try:
        # Загружаем конфигурацию
        config = load_config()
        
        print("🚀 Запуск Anti-Spam Bot v2.0")
        print("=" * 50)
        print(f"📊 Bot token: {config.bot_token[:20]}...")
        print(f"💾 Database: {config.database_url.split('@')[-1] if '@' in config.database_url else 'Local SQLite'}")
        print(f"🔑 OpenAI: {'✅ Enabled' if config.openai_api_key else '❌ Disabled'}")
        print(f"🛡️ CAS: {'✅ Enabled' if config.external_apis.get('cas') else '❌ Disabled'}")
        print(f"🤖 RUSpam: {'✅ Enabled' if config.spam_detection.get('use_ruspam', True) else '❌ Disabled'}")
        
        # Определяем режим запуска
        run_mode = os.getenv("RUN_MODE", "telegram").lower()
        print(f"🎯 Режим запуска: {run_mode}")
        
        # Настраиваем зависимости
        dependencies = await setup_dependencies(config)
        
        print("\n🎉 Инициализация завершена!")
        print("=" * 50)
        
        # Запускаем в зависимости от режима
        if run_mode == "telegram":
            await run_telegram_bot(config, dependencies)
        elif run_mode == "http":
            await run_http_server(config, dependencies)
        elif run_mode == "both":
            # Запуск обоих сервисов параллельно
            print("🔄 Запуск в dual режиме (Telegram + HTTP)...")
            
            telegram_task = asyncio.create_task(run_telegram_bot(config, dependencies))
            http_task = asyncio.create_task(run_http_server(config, dependencies))
            
            # Ждем завершения любой из задач
            done, pending = await asyncio.wait(
                [telegram_task, http_task], 
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Отменяем оставшиеся задачи
            for task in pending:
                task.cancel()
        else:
            print(f"❌ Неизвестный режим запуска: {run_mode}")
            print("💡 Доступные режимы: telegram, http, both")
            sys.exit(1)
        
    except KeyboardInterrupt:
        print("\n⏹️ Bot остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка при запуске: {e}")
        logging.exception("Fatal error")
        sys.exit(1)
    finally:
        # Очистка ресурсов
        print("🧹 Очистка ресурсов...")
        
        # Закрываем соединения если они были созданы
        try:
            if 'dependencies' in locals():
                if dependencies.get("postgres_client"):
                    await dependencies["postgres_client"].disconnect()
                    print("✅ PostgreSQL соединение закрыто")
                if dependencies.get("redis_cache"):
                    await dependencies["redis_cache"].disconnect()
                    print("✅ Redis соединение закрыто")
                if dependencies.get("http_client"):
                    await dependencies["http_client"].close()
                    print("✅ HTTP клиент закрыт")
        except Exception as e:
            print(f"⚠️ Ошибка при очистке ресурсов: {e}")


def check_environment():
    """Проверка окружения перед запуском"""
    required_env_vars = ["BOT_TOKEN"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")
        print("💡 Скопируйте env.example в .env и заполните необходимые значения")
        sys.exit(1)
    
    # Проверяем доступность базовых зависимостей
    try:
        import aiogram
        import asyncpg
        import aioredis
        print("✅ Основные зависимости найдены")
    except ImportError as e:
        print(f"❌ Отсутствует зависимость: {e}")
        print("💡 Установите зависимости: pip install -r requirements.txt")
        sys.exit(1)
    
    # Проверяем HTTP зависимости
    try:
        import fastapi
        import uvicorn
        print("✅ HTTP зависимости найдены")
    except ImportError as e:
        print(f"⚠️ HTTP зависимости не найдены: {e}")
        print("💡 Для HTTP API установите: pip install fastapi uvicorn")
    
    # Проверяем опциональные зависимости
    optional_deps = {
        "transformers": "RUSpam и ML классификатор",
        "torch": "BERT модели",
        "openai": "OpenAI интеграция",
        "ruSpamLib": "RUSpam библиотека"
    }
    
    for dep, description in optional_deps.items():
        try:
            __import__(dep)
            print(f"✅ {dep} доступен ({description})")
        except ImportError:
            print(f"⚠️ {dep} не найден - {description} не будет работать")


if __name__ == "__main__":
    print("🔍 Проверка окружения...")
    check_environment()
    
    # Запускаем приложение
    asyncio.run(main())