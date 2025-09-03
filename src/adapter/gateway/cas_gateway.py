import aiohttp
import asyncio
from typing import Optional
from ...lib.clients.http_client import HttpClient
from ...adapter.cache.redis_cache import RedisCache

class CASGateway:
    def __init__(self, http_client: HttpClient, cache: RedisCache, config: dict):
        self.http_client = http_client
        self.cache = cache
        self.api_url = config.get("cas_api_url", "https://api.cas.chat")
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
            url = f"{self.api_url}/check?user_id={user_id}"
            
            response_data = await self.http_client.get(
                url, 
                headers={"User-Agent": "AntiSpamBot/1.0"}
            )
            
            # Согласно документации CAS API:
            # - ok: True если запрос успешен
            # - result: содержит результат проверки
            if response_data and response_data.get("ok", False):
                # Пользователь забанен если result содержит информацию о бане
                result = response_data.get("result", {})
                is_banned = result.get("banned", False)
                
                # Кэшируем результат
                await self.cache.set(
                    cache_key, 
                    "banned" if is_banned else "clean", 
                    ttl=self.cache_ttl
                )
                
                return is_banned
            else:
                # Ошибка API или пользователь не найден
                if response_data:
                    error_desc = response_data.get("description", "Unknown error")
                    error_code = response_data.get("error_code", "Unknown")
                    print(f"CAS API error for user {user_id}: {error_code} - {error_desc}")
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

