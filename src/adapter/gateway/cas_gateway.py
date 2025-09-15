import aiohttp
import asyncio
from typing import Optional
from ...lib.clients.http_client import HttpClient
from ...adapter.cache.redis_cache import RedisCache

class CASGateway:
    def __init__(self, http_client: HttpClient, cache: RedisCache, config: dict):
        self.http_client = http_client
        self.cache = cache
        self.api_url = config.get("api_url")
        self.timeout = config.get("timeout", 5)
        self.cache_ttl = config.get("cache_ttl", 3600)  # 1 час

    async def check_cas(self, user_id: int) -> bool:
        """
        Проверить пользователя в CAS (Combot Anti-Spam)
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            bool: True если пользователь забанен в CAS, False если нет
        """
        cache_key = f"cas_check:{user_id}"
          # Проверяем кэш
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result == "banned"

        try:
            # Делаем запрос к CAS API согласно документации
            url = f"{self.api_url}?user_id={user_id}"
            
            response_data = await self.http_client.get(
                url, 
                headers={"User-Agent": "AntiSpamBot/1.0"}
            )
            
            # Согласно реальному поведению CAS API:
            # - ok: True означает пользователь ЗАБАНЕН (найден в базе CAS)
            # - ok: False означает пользователь НЕ ЗАБАНЕН (не найден в базе, "Record not found")
            if response_data:
                is_banned = response_data.get("ok", False)
                
                # Кэшируем результат
                await self.cache.set(
                    cache_key, 
                    "banned" if is_banned else "clean", 
                    ttl=self.cache_ttl
                )
                
                return is_banned
            else:
                # Нет ответа от API
                print(f"CAS API no response for user {user_id}")
                return False
            
        except asyncio.TimeoutError:
            print(f"CAS API timeout for user {user_id}")
            return False
        except Exception as e:
            print(f"CAS API error for user {user_id}: {e}")
            return False

    async def get_banned_users_csv(self) -> Optional[str]:
        """
        Получить CSV файл со всеми забаненными пользователями
        
        Returns:
            str: CSV содержимое или None при ошибке
        """
        try:
            url = f"{self.api_url}/export.csv"
            
            response_data = await self.http_client.get_text(
                url, 
                headers={"User-Agent": "AntiSpamBot/1.0"}
            )
            
            if response_data:
                return response_data
            else:
                print("CAS API: Failed to get CSV export")
                return None
                
        except Exception as e:
            print(f"CAS CSV export error: {e}")
            return None

    async def health_check(self) -> dict:
        """
        Проверка здоровья CAS Gateway
        
        Returns:
            dict: Статус здоровья системы
        """
        try:
            # Проверяем доступность API с тестовым запросом
            test_user_id = 304392973  # Тестовый ID
            start_time = asyncio.get_event_loop().time()
            
            # Делаем тестовый запрос
            is_banned = await self.check_cas(test_user_id)
            
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            
            return {
                "status": "healthy",
                "api_available": True,
                "response_time_ms": response_time,
                "test_result": {"user_id": test_user_id, "is_banned": is_banned},
                "config": {
                    "api_url": self.api_url,
                    "timeout": self.timeout,
                    "cache_ttl": self.cache_ttl
                }
            }
            
        except Exception as e:
            return {
                "status": "error",
                "api_available": False,
                "error": str(e),
                "config": {
                    "api_url": self.api_url,
                    "timeout": self.timeout,
                    "cache_ttl": self.cache_ttl
                }
            }




