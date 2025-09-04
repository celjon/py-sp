import asyncpg
from typing import Optional
from contextlib import asynccontextmanager


class PostgresClient:
    """Клиент для работы с PostgreSQL"""
    
    def __init__(self, database_url: str, min_size: int = 10, max_size: int = 20):
        """
        Args:
            database_url: URL для подключения к базе данных
            min_size: Минимальный размер пула соединений
            max_size: Максимальный размер пула соединений
        """
        self.database_url = database_url
        self.min_size = min_size
        self.max_size = max_size
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Создает пул соединений с базой данных"""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=self.min_size,
                max_size=self.max_size,
                command_timeout=60
            )
    
    async def disconnect(self):
        """Закрывает пул соединений"""
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
    
    @asynccontextmanager
    async def acquire(self):
        """
        Контекстный менеджер для получения соединения из пула
        
        Usage:
            async with postgres_client.acquire() as conn:
                result = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        """
        if self.pool is None:
            await self.connect()
        
        async with self.pool.acquire() as connection:
            yield connection
    
    async def execute(self, query: str, *args) -> str:
        """
        Выполняет SQL запрос без возврата результата
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            
        Returns:
            Статус выполнения команды
        """
        async with self.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """
        Выполняет SQL запрос и возвращает одну строку
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            
        Returns:
            Запись или None если не найдено
        """
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        """
        Выполняет SQL запрос и возвращает все строки
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            
        Returns:
            Список записей
        """
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchval(self, query: str, *args):
        """
        Выполняет SQL запрос и возвращает одно значение
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            
        Returns:
            Значение первого поля первой строки
        """
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    async def execute_many(self, query: str, args_list: list) -> None:
        """
        Выполняет SQL запрос множество раз с разными параметрами
        
        Args:
            query: SQL запрос
            args_list: Список кортежей с параметрами
        """
        async with self.acquire() as conn:
            await conn.executemany(query, args_list)
    
    async def transaction(self):
        """
        Возвращает контекстный менеджер для транзакции
        
        Usage:
            async with postgres_client.transaction() as tx:
                await tx.execute("INSERT INTO users ...")
                await tx.execute("UPDATE stats ...")
        """
        return self.acquire()
    
    @property
    def is_connected(self) -> bool:
        """Проверяет, установлено ли соединение с базой данных"""
        return self.pool is not None and not self.pool._closed

