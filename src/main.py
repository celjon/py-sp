#!/usr/bin/env python3
"""
Основная точка входа для антиспам бота с публичным API
Production-ready код с современной архитектурой: CAS + RUSpam + OpenAI
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
from src.adapter.repository.api_key_repository import ApiKeyRepository
from src.adapter.repository.usage_repository import UsageRepository
from src.adapter.gateway.telegram_gateway import TelegramGateway
from src.adapter.gateway.openai_gateway import OpenAIGateway
from src.adapter.gateway.cas_gateway import CASGateway
from src.lib.clients.http_client import HttpClient
from src.domain.service.detector.ensemble import EnsembleDetector
from src.domain.usecase.spam_detection.check_message import CheckMessageUseCase
from src.domain.usecase.spam_detection.ban_user import BanUserUseCase
from src.delivery.telegram.bot import AntiSpamBot


async def setup_dependencies(config):
    """
    Настраивает все зависимости для production системы
    Современная архитектура: CAS + RUSpam + OpenAI (БЕЗ эвристик и ML)
    """
    
    # Настройка логирования
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("🔧 Настройка production зависимостей...")
    print("🎯 Современная архитектура: CAS + RUSpam + OpenAI")
    print("❌ Удалены устаревшие: эвристики + ML классификаторы")
    
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
    api_key_repo = ApiKeyRepository(postgres_client)
    usage_repo = UsageRepository(postgres_client)
    
    # Создаем spam_samples_repository
    from src.adapter.repository.spam_samples_repository import SpamSamplesRepository
    spam_samples_repo = SpamSamplesRepository(postgres_client)
    
    # Создаем шлюзы (gateways)
    telegram_gateway = TelegramGateway(None)  # Bot будет передан позже
    
    # === OPENAI GATEWAY ===
    openai_gateway = None
    if config.openai_api_key and not config.openai_api_key.startswith("${"):
        print("🧠 Инициализация OpenAI LLM...")
        openai_gateway = OpenAIGateway(
            api_key=config.openai_api_key,
            config={
                "model": config.openai.model,
                "max_tokens": config.openai.max_tokens,
                "temperature": getattr(config.openai, 'temperature', 0.0),
                "system_prompt": getattr(config.openai, 'system_prompt', None)
            }
        )
        print("✅ OpenAI LLM готов")
    else:
        print("⚠️ OpenAI API ключ не настроен")
    
    # === CAS GATEWAY ===
    print("🛡️ Инициализация CAS системы...")
    cas_gateway = CASGateway(
        http_client=http_client,
        cache=redis_cache,
        config={
            "cas_api_url": config.external_apis.get("cas", {}).get("api_url", "https://api.cas.chat/check"),
            "timeout": config.external_apis.get("cas", {}).get("timeout", 5),
            "cache_ttl": config.external_apis.get("cas", {}).get("cache_ttl", 3600),
            "retry_attempts": config.external_apis.get("cas", {}).get("retry_attempts", 2)
        }
    )
    print("✅ CAS система готова")
    
    # === СОЗДАЕМ СОВРЕМЕННЫЙ АНСАМБЛЕВЫЙ ДЕТЕКТОР ===
    print("🎯 Инициализация современного спам-детектора...")
    ensemble_config = config.spam_detection.ensemble
    
    # Добавляем дополнительные настройки из других секций
    if hasattr(config, 'ruspam') and config.ruspam:
        ensemble_config.update({
            "ruspam_model_name": config.ruspam.model_name,
            "ruspam_cache_results": config.ruspam.cache_results,
            "ruspam_cache_ttl": config.ruspam.cache_ttl
        })
    
    spam_detector = EnsembleDetector(ensemble_config)
    
    # === ДОБАВЛЯЕМ ДЕТЕКТОРЫ ===
    
    # 1. CAS детектор (обязательный)
    spam_detector.add_cas_detector(cas_gateway)
    print("✅ CAS детектор добавлен")
    
    # 2. RUSpam BERT детектор
    try:
        spam_detector.add_ruspam_detector()
        print("✅ RUSpam BERT детектор добавлен")
    except Exception as e:
        print(f"⚠️ RUSpam BERT не загружен: {e}")
        print("💡 Установите: pip install torch transformers ruSpam")
    
    # 3. OpenAI детектор (если настроен)
    if openai_gateway:
        spam_detector.add_openai_detector(openai_gateway)
        print("✅ OpenAI LLM детектор добавлен")
    else:
        print("⚠️ OpenAI детектор не настроен (нет API ключа)")
    
    # ВАЖНО: Убираем все ссылки на устаревшие компоненты!
    # ❌ spam_detector.add_ml_detector() - УДАЛЕНО
    # ❌ HeuristicDetector - УДАЛЕН
    # ❌ MLClassifier - УДАЛЕН
    
    # === ПРОВЕРЯЕМ СОСТОЯНИЕ СИСТЕМЫ ===
    print("🔍 Проверка состояния детекторов...")
    health = await spam_detector.health_check()
    available_detectors = await spam_detector.get_available_detectors()
    
    print(f"📊 Архитектура: {health.get('architecture', 'modern')}")
    print(f"🔧 Доступные детекторы: {', '.join(available_detectors)}")
    print(f"🎯 Общий статус: {health['status']}")
    
    # Детальная проверка каждого детектора
    for detector_name, detector_health in health["detectors"].items():
        if detector_health["status"] == "healthy":
            status_icon = "✅"
        elif detector_health["status"] == "degraded":
            status_icon = "⚠️"
        else:
            status_icon = "❌"
        
        print(f"   {status_icon} {detector_name}: {detector_health['status']}")
        if "error" in detector_health:
            print(f"      Ошибка: {detector_health['error']}")
        if detector_health.get("type"):
            print(f"      Тип: {detector_health['type']}")
    
    # Выводим рекомендации если есть проблемы
    if "recommendations" in health:
        print("💡 Рекомендации:")
        for rec in health["recommendations"]:
            print(f"   - {rec}")
    
    # === СОЗДАЕМ USE CASES ===
    
    # Telegram use cases
    check_message_usecase = CheckMessageUseCase(
        message_repo=message_repo,
        user_repo=user_repo,
        spam_detector=spam_detector,
        spam_threshold=config.spam_detection.ensemble.get("spam_threshold", 0.6)
    )
    
    ban_user_usecase = BanUserUseCase(
        user_repo=user_repo,
        message_repo=message_repo
    )
    
    # API use cases
    try:
        from src.domain.usecase.api.detect_spam import DetectSpamUseCase
        from src.domain.usecase.api.batch_detect import BatchDetectUseCase  
        from src.domain.usecase.api.manage_api_keys import ManageApiKeysUseCase
        
        detect_spam_usecase = DetectSpamUseCase(
            spam_detector=spam_detector,
            usage_repo=usage_repo,
            api_key_repo=api_key_repo
        )
        
        batch_detect_usecase = BatchDetectUseCase(
            spam_detector=spam_detector,
            usage_repo=usage_repo,
            api_key_repo=api_key_repo,
            max_batch_size=config.api.get("max_batch_size", 100) if config.api else 100
        )
        
        manage_api_keys_usecase = ManageApiKeysUseCase(
            api_key_repo=api_key_repo,
            usage_repo=usage_repo
        )
        
        print("✅ API use cases инициализированы")
        
    except ImportError as e:
        print(f"⚠️ API use cases не загружены: {e}")
        detect_spam_usecase = None
        batch_detect_usecase = None
        manage_api_keys_usecase = None
    
    # === СОБИРАЕМ ВСЕ ЗАВИСИМОСТИ ===
    dependencies = {
        # Клиенты и инфраструктура
        "postgres_client": postgres_client,
        "redis_cache": redis_cache,
        "http_client": http_client,
        
        # Репозитории
        "message_repository": message_repo,
        "user_repository": user_repo,
        "spam_samples_repository": spam_samples_repo,
        "api_key_repository": api_key_repo,
        "usage_repository": usage_repo,
        
        # Шлюзы
        "telegram_gateway": telegram_gateway,
        "openai_gateway": openai_gateway,
        "cas_gateway": cas_gateway,
        
        # Современный детектор (БЕЗ эвристик и ML)
        "spam_detector": spam_detector,
        
        # Use cases (Telegram)
        "check_message_usecase": check_message_usecase,
        "ban_user_usecase": ban_user_usecase,
        
        # Use cases (API)
        "detect_spam_usecase": detect_spam_usecase,
        "batch_detect_usecase": batch_detect_usecase,
        "manage_api_keys_usecase": manage_api_keys_usecase,
        
        # Конфигурация
        "admin_chat_id": config.admin_chat_id,
        "config": config,
        
        # Состояние системы
        "system_health": health,
        "available_detectors": available_detectors
    }
    
    print("✅ Production зависимости настроены")
    print(f"🚀 Система готова! Детекторы: {len(available_detectors)}")
    
    return dependencies


async def start_telegram_bot(dependencies):
    """Запуск Telegram бота"""
    try:
        from aiogram import Bot, Dispatcher
        
        config = dependencies["config"]
        bot = Bot(token=config.bot_token)
        dp = Dispatcher()
        
        # Обновляем telegram_gateway с ботом
        telegram_gateway = dependencies["telegram_gateway"]
        telegram_gateway.bot = bot
        
        # Создаем антиспам бот
        antispam_bot = AntiSpamBot(
            bot=bot,
            dispatcher=dp,
            check_message_usecase=dependencies["check_message_usecase"],
            ban_user_usecase=dependencies["ban_user_usecase"],
            admin_chat_id=config.admin_chat_id
        )
        
        print("🤖 Запуск Telegram бота...")
        await antispam_bot.start()
        
    except ImportError as e:
        print(f"❌ Не удалось запустить Telegram бот: {e}")
        print("💡 Установите: pip install aiogram")
    except Exception as e:
        print(f"❌ Ошибка запуска Telegram бота: {e}")
        raise


async def start_http_server(dependencies):
    """Запуск HTTP API сервера"""
    try:
        import uvicorn
        from src.delivery.http.app import create_app
        
        config = dependencies["config"]
        
        # Создаем FastAPI приложение
        app = create_app(dependencies)
        
        print("🌐 Запуск HTTP API сервера...")
        server_config = uvicorn.Config(
            app,
            host=config.http_server.get("host", "0.0.0.0"),
            port=config.http_server.get("port", 8080),
            workers=config.http_server.get("workers", 1),
            log_level=config.log_level.lower()
        )
        
        server = uvicorn.Server(server_config)
        await server.serve()
        
    except ImportError as e:
        print(f"❌ Не удалось запустить HTTP сервер: {e}")
        print("💡 Установите: pip install fastapi uvicorn")
    except Exception as e:
        print(f"❌ Ошибка запуска HTTP сервера: {e}")
        raise


async def create_default_api_key(dependencies):
    """Создает дефолтный API ключ для тестирования"""
    try:
        manage_keys_usecase = dependencies.get("manage_api_keys_usecase")
        api_key_repo = dependencies.get("api_key_repository")
        
        if not manage_keys_usecase or not api_key_repo:
            print("⚠️ API keys use case недоступен")
            return
        
        # Проверяем, есть ли уже API ключи
        existing_keys = await api_key_repo.get_active_api_keys()
        if existing_keys:
            print(f"ℹ️ Найдено {len(existing_keys)} активных API ключей")
            return
        
        # Создаем дефолтный ключ для тестирования
        from src.domain.usecase.api.manage_api_keys import CreateApiKeyRequest
        from src.domain.entity.api_key import ApiKeyPlan
        
        request = CreateApiKeyRequest(
            client_name="Default Test Client",
            contact_email="test@example.com",
            plan=ApiKeyPlan.BASIC,
            requests_per_minute=60,
            requests_per_day=5000,
            metadata={"created_by": "auto_setup", "purpose": "testing"}
        )
        
        result = await manage_keys_usecase.create_api_key(request)
        
        print("🔑 Создан дефолтный API ключ для тестирования:")
        print(f"   Client: {result.api_key.client_name}")
        print(f"   API Key: {result.raw_key}")
        print(f"   Plan: {result.api_key.plan.value}")
        print(f"   ⚠️ Сохраните этот ключ - он больше не будет показан!")
        
    except Exception as e:
        print(f"⚠️ Не удалось создать дефолтный API ключ: {e}")


async def main():
    """Основная функция приложения"""
    try:
        # Загружаем конфигурацию
        config = load_config()
        
        print("🚀 Запуск Anti-Spam Bot v2.0")
        print("🎯 Современная архитектура: CAS + RUSpam + OpenAI")
        print("=" * 60)
        print(f"📊 Bot token: {config.bot_token[:20] if config.bot_token else 'НЕ НАСТРОЕН'}...")
        print(f"💾 Database: {config.database_url.split('@')[-1] if '@' in config.database_url else 'Local'}")
        print(f"🔑 OpenAI: {'✅ Enabled' if config.openai_api_key and not config.openai_api_key.startswith('${') else '❌ Disabled'}")
        print(f"🛡️ CAS: {'✅ Enabled' if config.external_apis.get('cas') else '❌ Disabled'}")
        print(f"🤖 RUSpam: {'✅ Enabled' if config.spam_detection.ensemble.get('use_ruspam', True) else '❌ Disabled'}")
        print(f"🌐 HTTP API: {'✅ Enabled' if config.http_server.get('enabled', True) else '❌ Disabled'}")
        
        # Определяем режим запуска
        run_mode = os.getenv("RUN_MODE", "both").lower()
        print(f"🎯 Режим запуска: {run_mode}")
        
        # Настраиваем зависимости
        dependencies = await setup_dependencies(config)
        
        # Создаем дефолтный API ключ для тестирования
        await create_default_api_key(dependencies)
        
        print("\n🎉 Инициализация завершена!")
        
        # Запускаем сервисы в зависимости от режима
        if run_mode == "telegram":
            print("\n🤖 Запуск только Telegram бота...")
            await start_telegram_bot(dependencies)
        elif run_mode == "http":
            print("\n🌐 Запуск только HTTP API...")
            await start_http_server(dependencies)
        elif run_mode == "both":
            print("\n🚀 Запуск Telegram бота + HTTP API...")
            # Запускаем параллельно
            await asyncio.gather(
                start_telegram_bot(dependencies),
                start_http_server(dependencies)
            )
        else:
            print(f"❌ Неизвестный режим: {run_mode}")
            print("💡 Используйте: telegram, http, или both")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⏹️ Остановка по запросу пользователя")
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
        raise
    finally:
        print("👋 Завершение работы...")


def check_environment():
    """Проверка production окружения (БЕЗ эвристик и ML)"""
    
    print("🔍 Проверка production окружения...")
    
    # Основные зависимости
    try:
        import aiogram
        import asyncpg
        print("✅ Основные зависимости: aiogram, asyncpg")
    except ImportError as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        print("💡 Установите: pip install aiogram asyncpg")
        sys.exit(1)
    
    # HTTP API зависимости
    try:
        import fastapi
        import uvicorn
        print("✅ HTTP API: fastapi, uvicorn")
    except ImportError as e:
        print(f"❌ HTTP API недоступен: {e}")
        print("💡 Для API установите: pip install fastapi uvicorn")
    
    # Современные детекторы
    production_deps = {
        "transformers": "RUSpam BERT модель",
        "torch": "PyTorch для BERT",
        "openai": "OpenAI LLM интеграция",
        "redis": "Redis кэширование для production"
    }
    
    critical_missing = []
    
    for dep, description in production_deps.items():
        try:
            __import__(dep)
            print(f"✅ {dep}: {description}")
        except ImportError:
            print(f"⚠️ {dep} отсутствует - {description}")
            if dep in ["redis"]:  # Критические для production
                critical_missing.append(dep)
    
    if critical_missing:
        print(f"❌ КРИТИЧЕСКИЕ зависимости отсутствуют: {critical_missing}")
        print("💡 Установите для production работы")
    
    # УДАЛЯЕМ проверку устаревших зависимостей:
    # ❌ scikit-learn, pandas, scipy, joblib - больше НЕ НУЖНЫ!
    
    print("✅ Проверка окружения завершена")


if __name__ == "__main__":
    print("🔍 Проверка окружения...")
    check_environment()
    
    # Запускаем приложение
    asyncio.run(main())