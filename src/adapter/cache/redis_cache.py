import json
import redis.asyncio as redis
from typing import Any, Optional


class RedisCache:
    """Redis кэш для хранения временных данных"""
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis = None
    
    async def connect(self):
        """Устанавливает соединение с Redis"""
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
    
    async def disconnect(self):
        """Закрывает соединение с Redis"""
        if self.redis:
            await self.redis.close()
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Получает значение из кэша
        
        Args:
            key: Ключ для получения значения
            
        Returns:
            Значение или None если ключ не найден
        """
        if not self.redis:
            await self.connect()
        
        try:
            value = await self.redis.get(key)
            if value is None:
                return None
            
            # Пытаемся декодировать JSON, если не получается - возвращаем как строку
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception as e:
            print(f"Error getting key {key} from Redis: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """
        Сохраняет значение в кэш
        
        Args:
            key: Ключ для сохранения
            value: Значение для сохранения
            ttl: Время жизни в секундах (опционально)
            
        Returns:
            True если успешно сохранено, False в случае ошибки
        """
        if not self.redis:
            await self.connect()
        
        try:
            # Сериализуем значение в JSON если это не строка
            if isinstance(value, str):
                serialized_value = value
            else:
                serialized_value = json.dumps(value)
            
            if ttl:
                await self.redis.setex(key, ttl, serialized_value)
            else:
                await self.redis.set(key, serialized_value)
            
            return True
        except Exception as e:
            print(f"Error setting key {key} in Redis: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """
        Удаляет ключ из кэша
        
        Args:
            key: Ключ для удаления
            
        Returns:
            True если ключ был удален, False в случае ошибки
        """
        if not self.redis:
            await self.connect()
        
        try:
            result = await self.redis.delete(key)
            return result > 0
        except Exception as e:
            print(f"Error deleting key {key} from Redis: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """
        Проверяет существование ключа в кэше
        
        Args:
            key: Ключ для проверки
            
        Returns:
            True если ключ существует, False иначе
        """
        if not self.redis:
            await self.connect()
        
        try:
            result = await self.redis.exists(key)
            return result > 0
        except Exception as e:
            print(f"Error checking existence of key {key} in Redis: {e}")
            return False
    
    async def increment(self, key: str, amount: int = 1, ttl: int = None) -> Optional[int]:
        """
        Увеличивает счетчик
        
        Args:
            key: Ключ счетчика
            amount: На сколько увеличить (по умолчанию 1)
            ttl: Время жизни в секундах (только при создании)
            
        Returns:
            Новое значение счетчика или None в случае ошибки
        """
        if not self.redis:
            await self.connect()
        
        try:
            # Проверяем, существует ли ключ
            if not await self.exists(key) and ttl:
                # Если ключ не существует и задан TTL, устанавливаем его
                await self.redis.setex(key, ttl, "0")
            
            result = await self.redis.incrby(key, amount)
            return result
        except Exception as e:
            print(f"Error incrementing key {key} in Redis: {e}")
            return None
    
    async def get_keys_by_pattern(self, pattern: str) -> list:
        """
        Получает список ключей по паттерну
        
        Args:
            pattern: Паттерн для поиска (например, "user:*")
            
        Returns:
            Список ключей
        """
        if not self.redis:
            await self.connect()
        
        try:
            keys = await self.redis.keys(pattern)
            return keys
        except Exception as e:
            print(f"Error getting keys by pattern {pattern} from Redis: {e}")
            return []
    
    async def clear_pattern(self, pattern: str) -> int:
        """
        Удаляет все ключи по паттерну
        
        Args:
            pattern: Паттерн для удаления
            
        Returns:
            Количество удаленных ключей
        """
        if not self.redis:
            await self.connect()
        
        try:
            keys = await self.get_keys_by_pattern(pattern)
            if keys:
                deleted_count = await self.redis.delete(*keys)
                return deleted_count
            return 0
        except Exception as e:
            print(f"Error clearing pattern {pattern} from Redis: {e}")
            return 0

