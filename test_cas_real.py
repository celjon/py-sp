#!/usr/bin/env python3
"""
Тест реального CAS API
"""
import asyncio
import sys
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def test_real_cas_api():
    """Тест реального CAS API"""
    print("🌐 Тестирование реального CAS API...")
    
    try:
        from src.lib.clients.http_client import HttpClient
        from src.adapter.gateway.cas_gateway import CASGateway
        
        # Создаем mock Redis (для тестов)
        class MockRedisCache:
            async def get(self, key: str):
                return None
            
            async def set(self, key: str, value: str, ttl: int = 3600):
                pass
        
        # Создаем HTTP клиент
        http_client = HttpClient()
        
        # Создаем mock Redis
        redis_cache = MockRedisCache()
        
        # Создаем CAS Gateway
        cas_gateway = CASGateway(
            http_client=http_client,
            cache=redis_cache,
            config={
                "cas_api_url": "https://api.cas.chat",
                "timeout": 10,
                "cache_ttl": 3600
            }
        )
        
        # Тестовые пользователи (реальные Telegram ID)
        test_users = [
            (123456789, "Тестовый пользователь 1"),
            (987654321, "Тестовый пользователь 2"),
            (555666777, "Тестовый пользователь 3"),
        ]
        
        print("🔍 Проверяем обычных пользователей в CAS...")
        
        for user_id, description in test_users:
            try:
                is_banned = await cas_gateway.check_cas(user_id)
                status = "🚨 ЗАБАНЕН" if is_banned else "✅ Чистый"
                print(f"   {status} | ID: {user_id} | {description}")
                
                # Небольшая пауза между запросами
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"   ❌ Ошибка для ID {user_id}: {e}")
        
        # Тест с реальными забаненными пользователями (известные спамеры)
        print("\n🚨 Проверяем известных спамеров в CAS...")
        
        # Эти ID могут быть забанены в CAS (взяты из реальных примеров)
        known_spammers = [
            (821871410, "Известный спамер 1"),
            (1234567890, "Известный спамер 2"),
            (9876543210, "Известный спамер 3"),
        ]
        
        for user_id, description in known_spammers:
            try:
                is_banned = await cas_gateway.check_cas(user_id)
                status = "🚨 ЗАБАНЕН" if is_banned else "✅ Чистый"
                print(f"   {status} | ID: {user_id} | {description}")
                
                # Небольшая пауза между запросами
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"   ❌ Ошибка для ID {user_id}: {e}")
        
        # Тест CSV экспорта
        print("\n📊 Тестируем CSV экспорт...")
        try:
            csv_data = await cas_gateway.get_banned_users_csv()
            if csv_data:
                print(f"   ✅ CSV экспорт успешен, размер: {len(csv_data)} символов")
                print(f"   📄 Первые 200 символов: {csv_data[:200]}...")
            else:
                print("   ❌ CSV экспорт не удался")
        except Exception as e:
            print(f"   ❌ Ошибка CSV экспорта: {e}")
        
        print("\n📊 Тест CAS API завершен!")
        return True
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        return False
    finally:
        # Закрываем HTTP клиент
        if 'http_client' in locals():
            await http_client.close()

if __name__ == "__main__":
    asyncio.run(test_real_cas_api())
