#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работоспособности AntiSpam Bot
"""
import asyncio
import sys
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def test_config():
    """Тест загрузки конфигурации"""
    print("🔧 Тестирование конфигурации...")
    try:
        from config.config import load_config
        config = load_config("development")
        print(f"✅ Конфигурация загружена: {config.database.url}")
        return True
    except Exception as e:
        print(f"❌ Ошибка конфигурации: {e}")
        return False

async def test_detectors():
    """Тест детекторов"""
    print("\n🔍 Тестирование детекторов...")
    
    try:
        # Тест эвристического детектора
        from domain.service.detector.heuristic import HeuristicDetector
        from domain.entity.message import Message
        
        heuristic = HeuristicDetector()
        
        # Тестовые сообщения
        test_messages = [
            ("Привет, как дела?", False),  # Должно пройти
            ("🔥🔥🔥 URGENT! Make $500 per day! 💰💰💰", True),  # Должно быть заблокировано
            ("Купите дешевые товары по ссылке: http://spam.com", True),  # Должно быть заблокировано
            ("Спасибо за информацию", False),  # Должно пройти
        ]
        
        for text, expected_spam in test_messages:
            message = Message(
                id=1,
                user_id=123,
                chat_id=456,
                text=text,
                role="user"
            )
            
            result = await heuristic.check_message(message, None)
            status = "✅" if result.is_spam == expected_spam else "❌"
            print(f"{status} '{text[:30]}...' → Спам: {result.is_spam} (ожидалось: {expected_spam})")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования детекторов: {e}")
        return False

async def test_ml_classifier():
    """Тест ML классификатора"""
    print("\n🤖 Тестирование ML классификатора...")
    
    try:
        from domain.service.detector.ml_classifier import MLClassifier
        
        # Создаем временную директорию для моделей
        models_dir = Path("models")
        models_dir.mkdir(exist_ok=True)
        
        ml = MLClassifier(models_dir, {"use_bert": False})  # Отключаем BERT для быстрого теста
        
        # Тестируем fallback модель
        result = await ml.classify("🔥🔥🔥 URGENT! Make $500 per day! 💰💰💰")
        print(f"✅ ML классификатор работает: {result.is_spam} (confidence: {result.confidence:.2f})")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка ML классификатора: {e}")
        return False

async def test_ensemble():
    """Тест ансамблевого детектора"""
    print("\n🎯 Тестирование ансамблевого детектора...")
    
    try:
        from domain.service.detector.ensemble import EnsembleDetector
        
        ensemble = EnsembleDetector({
            "spam_threshold": 0.6,
            "high_confidence_threshold": 0.8
        })
        
        print(f"✅ Ансамблевый детектор создан")
        print(f"   Доступные детекторы: {await ensemble.get_available_detectors()}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка ансамблевого детектора: {e}")
        return False

async def test_database_connection():
    """Тест подключения к базе данных"""
    print("\n🗄️ Тестирование подключения к БД...")
    
    try:
        from lib.clients.postgres_client import PostgresClient
        from config.config import load_config
        
        config = load_config("development")
        client = PostgresClient(config.database.url)
        
        await client.connect()
        print("✅ Подключение к PostgreSQL успешно")
        
        await client.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        print("💡 Убедитесь, что PostgreSQL запущен и доступен")
        return False

async def test_redis_connection():
    """Тест подключения к Redis"""
    print("\n🔴 Тестирование подключения к Redis...")
    
    try:
        from lib.clients.redis_client import RedisClient
        from config.config import load_config
        
        config = load_config("development")
        client = RedisClient(config.redis.url)
        
        await client.connect()
        print("✅ Подключение к Redis успешно")
        
        await client.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Ошибка подключения к Redis: {e}")
        print("💡 Убедитесь, что Redis запущен и доступен")
        return False

async def main():
    """Основная функция тестирования"""
    print("🧪 Тестирование AntiSpam Bot...")
    print("=" * 50)
    
    tests = [
        test_config,
        test_detectors,
        test_ml_classifier,
        test_ensemble,
        test_database_connection,
        test_redis_connection
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"❌ Критическая ошибка в тесте {test.__name__}: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("📊 Результаты тестирования:")
    
    passed = sum(results)
    total = len(results)
    
    for i, (test, result) in enumerate(zip(tests, results)):
        status = "✅" if result else "❌"
        print(f"{status} {test.__name__}")
    
    print(f"\n🎯 Итого: {passed}/{total} тестов прошли успешно")
    
    if passed == total:
        print("🎉 Все тесты прошли! Бот готов к работе!")
        print("\n🚀 Следующие шаги:")
        print("1. Настройте BOT_TOKEN в .env файле")
        print("2. Запустите базы данных: docker-compose up -d postgres redis")
        print("3. Инициализируйте БД: make init-db")
        print("4. Запустите бота: make run")
    else:
        print("⚠️ Некоторые тесты не прошли. Проверьте настройки и зависимости.")
        print("\n🔧 Рекомендации:")
        print("1. Установите зависимости: pip install -r requirements.txt")
        print("2. Проверьте конфигурацию в config/development.yaml")
        print("3. Убедитесь, что PostgreSQL и Redis запущены")

if __name__ == "__main__":
    asyncio.run(main())
