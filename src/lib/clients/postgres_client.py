# src/lib/clients/postgres_client.py
"""
Production-Ready PostgreSQL Client
Высокопроизводительный клиент с connection pooling и monitoring
"""

import asyncio
import asyncpg
import logging
import time
from typing import Optional, Dict, Any, List, Union
from contextlib import asynccontextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConnectionPoolStats:
    """Статистика connection pool"""
    size: int
    used: int
    free: int
    min_size: int
    max_size: int
    total_connections_created: int
    total_queries_executed: int
    
    @property
    def utilization_ratio(self) -> float:
        """Коэффициент использования пула"""
        return self.used / self.size if self.size > 0 else 0.0


class PostgresClient:
    """
    Production-ready клиент для работы с PostgreSQL
    
    Features:
    - Connection pooling с автоматическим management
    - Health checking и recovery
    - Query performance monitoring
    - Comprehensive error handling
    - Graceful degradation
    - Connection leak prevention
    """
    
    def __init__(
        self, 
        database_url: str, 
        min_size: int = 10, 
        max_size: int = 20,
        command_timeout: int = 60,
        query_timeout: int = 30,
        server_settings: Dict[str, str] = None
    ):
        """
        Args:
            database_url: URL для подключения к базе данных
            min_size: Минимальный размер пула соединений
            max_size: Максимальный размер пула соединений
            command_timeout: Таймаут для команд (секунды)
            query_timeout: Таймаут для запросов (секунды)
            server_settings: Дополнительные настройки сервера
        """
        self.database_url = database_url
        self.min_size = min_size
        self.max_size = max_size
        self.command_timeout = command_timeout
        self.query_timeout = query_timeout
        self.server_settings = server_settings or {
            "application_name": "antispam-api",
            "jit": "off",  # Отключаем JIT для стабильности
            "shared_preload_libraries": "pg_stat_statements"
        }
        
        self.pool: Optional[asyncpg.Pool] = None
        
        # Performance metrics
        self._total_queries = 0
        self._total_query_time = 0.0
        self._failed_queries = 0
        self._connections_created = 0
        self._connection_errors = 0
        
        logger.info(f"🐘 PostgresClient создан: pool_size={min_size}-{max_size}, timeout={command_timeout}s")
    
    async def connect(self) -> None:
        """Создает пул соединений с базой данных"""
        if self.pool is not None:
            logger.warning("PostgreSQL pool уже создан")
            return
        
        try:
            logger.info("🔌 Подключение к PostgreSQL...")
            
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=self.min_size,
                max_size=self.max_size,
                command_timeout=self.command_timeout,
                server_settings=self.server_settings,
                # Connection lifecycle hooks
                init=self._connection_init_hook,
                setup=self._connection_setup_hook
            )
            
            # Проверяем соединение
            async with self.pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"✅ PostgreSQL подключен: {version[:50]}...")
            
            logger.info(f"✅ Connection pool создан: {self.min_size}-{self.max_size} соединений")
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
            raise RuntimeError(f"Failed to connect to PostgreSQL: {e}")
    
    async def disconnect(self) -> None:
        """Закрывает пул соединений"""
        if self.pool is not None:
            try:
                logger.info("🔌 Закрытие PostgreSQL соединений...")
                await self.pool.close()
                self.pool = None
                logger.info("✅ PostgreSQL отключен")
            except Exception as e:
                logger.error(f"⚠️ Ошибка закрытия PostgreSQL: {e}")
    
    async def _connection_init_hook(self, conn):
        """Hook вызываемый при создании каждого соединения"""
        self._connections_created += 1
        logger.debug(f"🔗 Новое PostgreSQL соединение #{self._connections_created}")
    
    async def _connection_setup_hook(self, conn):
        """Hook для настройки соединения"""
        try:
            # Настраиваем кастомные типы если нужно
            # await conn.set_type_codec('json', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
            pass
        except Exception as e:
            logger.warning(f"⚠️ Connection setup warning: {e}")
    
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
        
        start_time = time.time()
        connection = None
        
        try:
            connection = await asyncio.wait_for(
                self.pool.acquire(),
                timeout=self.query_timeout
            )
            
            yield connection
            
        except asyncio.TimeoutError:
            self._connection_errors += 1
            logger.error("⏰ Timeout при получении PostgreSQL соединения")
            raise RuntimeError("Database connection timeout")
            
        except Exception as e:
            self._connection_errors += 1
            logger.error(f"❌ Ошибка получения PostgreSQL соединения: {e}")
            raise
            
        finally:
            if connection:
                try:
                    await self.pool.release(connection)
                except Exception as e:
                    logger.error(f"⚠️ Ошибка возврата соединения в пул: {e}")
            
            # Записываем время получения соединения
            acquisition_time = time.time() - start_time
            if acquisition_time > 1.0:  # Предупреждаем если > 1 секунды
                logger.warning(f"⚠️ Медленное получение соединения: {acquisition_time:.2f}s")
    
    async def execute(self, query: str, *args, timeout: float = None) -> str:
        """
        Выполняет SQL запрос без возврата результата
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            timeout: Таймаут для запроса
            
        Returns:
            Статус выполнения команды
        """
        start_time = time.time()
        self._total_queries += 1
        
        try:
            async with self.acquire() as conn:
                result = await asyncio.wait_for(
                    conn.execute(query, *args),
                    timeout=timeout or self.query_timeout
                )
                
                query_time = time.time() - start_time
                self._total_query_time += query_time
                
                if query_time > 1.0:  # Медленный запрос
                    logger.warning(f"⚠️ Медленный execute: {query_time:.2f}s - {query[:100]}")
                
                return result
                
        except Exception as e:
            self._failed_queries += 1
            query_time = time.time() - start_time
            logger.error(f"❌ Execute failed ({query_time:.2f}s): {query[:100]} - {e}")
            raise
    
    async def fetchrow(self, query: str, *args, timeout: float = None) -> Optional[asyncpg.Record]:
        """
        Выполняет SQL запрос и возвращает одну строку
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            timeout: Таймаут для запроса
            
        Returns:
            Запись или None если не найдено
        """
        start_time = time.time()
        self._total_queries += 1
        
        try:
            async with self.acquire() as conn:
                result = await asyncio.wait_for(
                    conn.fetchrow(query, *args),
                    timeout=timeout or self.query_timeout
                )
                
                query_time = time.time() - start_time
                self._total_query_time += query_time
                
                if query_time > 0.5:  # Медленный запрос
                    logger.warning(f"⚠️ Медленный fetchrow: {query_time:.2f}s - {query[:100]}")
                
                return result
                
        except Exception as e:
            self._failed_queries += 1
            query_time = time.time() - start_time
            logger.error(f"❌ Fetchrow failed ({query_time:.2f}s): {query[:100]} - {e}")
            raise
    
    async def fetch(self, query: str, *args, timeout: float = None) -> List[asyncpg.Record]:
        """
        Выполняет SQL запрос и возвращает все строки
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            timeout: Таймаут для запроса
            
        Returns:
            Список записей
        """
        start_time = time.time()
        self._total_queries += 1
        
        try:
            async with self.acquire() as conn:
                result = await asyncio.wait_for(
                    conn.fetch(query, *args),
                    timeout=timeout or self.query_timeout
                )
                
                query_time = time.time() - start_time
                self._total_query_time += query_time
                
                if query_time > 1.0 or len(result) > 1000:  # Медленный или большой запрос
                    logger.warning(f"⚠️ Медленный/большой fetch: {query_time:.2f}s, {len(result)} строк - {query[:100]}")
                
                return result
                
        except Exception as e:
            self._failed_queries += 1
            query_time = time.time() - start_time
            logger.error(f"❌ Fetch failed ({query_time:.2f}s): {query[:100]} - {e}")
            raise
    
    async def fetchval(self, query: str, *args, timeout: float = None) -> Any:
        """
        Выполняет SQL запрос и возвращает одно значение
        
        Args:
            query: SQL запрос
            *args: Параметры запроса
            timeout: Таймаут для запроса
            
        Returns:
            Значение первого поля первой строки
        """
        start_time = time.time()
        self._total_queries += 1
        
        try:
            async with self.acquire() as conn:
                result = await asyncio.wait_for(
                    conn.fetchval(query, *args),
                    timeout=timeout or self.query_timeout
                )
                
                query_time = time.time() - start_time
                self._total_query_time += query_time
                
                return result
                
        except Exception as e:
            self._failed_queries += 1
            query_time = time.time() - start_time
            logger.error(f"❌ Fetchval failed ({query_time:.2f}s): {query[:100]} - {e}")
            raise
    
    async def execute_many(self, query: str, args_list: List[tuple], timeout: float = None) -> None:
        """
        Выполняет SQL запрос множество раз с разными параметрами
        
        Args:
            query: SQL запрос
            args_list: Список кортежей с параметрами
            timeout: Таймаут для запроса
        """
        start_time = time.time()
        self._total_queries += len(args_list)
        
        try:
            async with self.acquire() as conn:
                await asyncio.wait_for(
                    conn.executemany(query, args_list),
                    timeout=timeout or (self.query_timeout * 2)  # Больше времени для batch
                )
                
                query_time = time.time() - start_time
                self._total_query_time += query_time
                
                if query_time > 2.0:  # Медленный batch
                    logger.warning(f"⚠️ Медленный executemany: {query_time:.2f}s, {len(args_list)} операций")
                
        except Exception as e:
            self._failed_queries += len(args_list)
            query_time = time.time() - start_time
            logger.error(f"❌ ExecuteMany failed ({query_time:.2f}s): {len(args_list)} ops - {e}")
            raise
    
    @asynccontextmanager
    async def transaction(self):
        """
        Контекстный менеджер для транзакций
        
        Usage:
            async with postgres_client.transaction() as tx:
                await tx.execute("INSERT INTO users ...")
                await tx.execute("UPDATE stats ...")
                # Автоматический COMMIT или ROLLBACK при ошибке
        """
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn
    
    async def execute_in_transaction(self, queries: List[tuple]) -> List[Any]:
        """
        Выполняет множество запросов в одной транзакции
        
        Args:
            queries: Список (query, args) для выполнения
            
        Returns:
            Список результатов
        """
        results = []
        
        try:
            async with self.transaction() as tx:
                for query, args in queries:
                    if query.strip().upper().startswith('SELECT'):
                        result = await tx.fetch(query, *args)
                    else:
                        result = await tx.execute(query, *args)
                    results.append(result)
                
            logger.debug(f"✅ Транзакция выполнена: {len(queries)} запросов")
            return results
            
        except Exception as e:
            logger.error(f"❌ Транзакция failed: {e}")
            raise
    
    def get_pool_stats(self) -> ConnectionPoolStats:
        """Возвращает статистику connection pool"""
        if not self.pool:
            return ConnectionPoolStats(0, 0, 0, 0, 0, 0, 0)
        
        try:
            size = self.pool.get_size()
            used = size - self.pool.get_idle_size()
            free = self.pool.get_idle_size()
            
            return ConnectionPoolStats(
                size=size,
                used=used,
                free=free,
                min_size=self.min_size,
                max_size=self.max_size,
                total_connections_created=self._connections_created,
                total_queries_executed=self._total_queries
            )
            
        except Exception as e:
            logger.error(f"⚠️ Ошибка получения статистики пула: {e}")
            return ConnectionPoolStats(0, 0, 0, 0, 0, 0, 0)
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Возвращает статистику производительности"""
        avg_query_time = (
            self._total_query_time / self._total_queries 
            if self._total_queries > 0 else 0
        )
        
        error_rate = (
            self._failed_queries / self._total_queries 
            if self._total_queries > 0 else 0
        )
        
        connection_error_rate = (
            self._connection_errors / self._connections_created
            if self._connections_created > 0 else 0
        )
        
        return {
            "total_queries": self._total_queries,
            "failed_queries": self._failed_queries,
            "total_query_time_seconds": self._total_query_time,
            "average_query_time_ms": avg_query_time * 1000,
            "error_rate": error_rate,
            "connections_created": self._connections_created,
            "connection_errors": self._connection_errors,
            "connection_error_rate": connection_error_rate,
            "pool_stats": self.get_pool_stats().__dict__
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Comprehensive health check для PostgreSQL
        
        Returns:
            Статус здоровья базы данных
        """
        health_info = {
            "status": "unknown",
            "timestamp": time.time(),
            "database": "postgresql"
        }
        
        try:
            if not self.pool:
                health_info.update({
                    "status": "disconnected",
                    "error": "Connection pool not initialized"
                })
                return health_info
            
            # Тест соединения
            start_time = time.time()
            
            async with self.acquire() as conn:
                # Базовый тест
                await conn.fetchval("SELECT 1")
                
                # Проверяем версию
                version = await conn.fetchval("SELECT version()")
                
                # Проверяем права доступа
                can_create_table = True
                try:
                    await conn.fetchval("SELECT has_table_privilege(current_user, 'users', 'INSERT')")
                except:
                    can_create_table = False
                
                # Проверяем активные соединения
                active_connections = await conn.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                )
                
            response_time_ms = (time.time() - start_time) * 1000
            
            # Статистика пула
            pool_stats = self.get_pool_stats()
            
            health_info.update({
                "status": "healthy",
                "response_time_ms": response_time_ms,
                "database_info": {
                    "version": version.split(',')[0] if version else "unknown",
                    "active_connections": active_connections,
                    "can_create_table": can_create_table
                },
                "pool_info": {
                    "size": pool_stats.size,
                    "used": pool_stats.used,
                    "free": pool_stats.free,
                    "utilization": round(pool_stats.utilization_ratio * 100, 2)
                },
                "performance": self.get_performance_stats()
            })
            
            # Предупреждения
            warnings = []
            if pool_stats.utilization_ratio > 0.8:
                warnings.append("High pool utilization (>80%)")
            if response_time_ms > 100:
                warnings.append(f"Slow response time ({response_time_ms:.1f}ms)")
            if self.get_performance_stats()["error_rate"] > 0.1:
                warnings.append("High error rate (>10%)")
            
            if warnings:
                health_info["warnings"] = warnings
                health_info["status"] = "degraded"
            
        except Exception as e:
            logger.error(f"❌ PostgreSQL health check failed: {e}")
            health_info.update({
                "status": "error",
                "error": str(e),
                "performance": self.get_performance_stats()
            })
        
        return health_info
    
    async def cleanup_idle_connections(self) -> int:
        """
        Очищает idle соединения (maintenance task)
        
        Returns:
            Количество закрытых соединений
        """
        if not self.pool:
            return 0
        
        try:
            initial_size = self.pool.get_size()
            
            # В asyncpg нет прямого способа cleanup, но можем пересоздать пул
            # Для production используйте connection_max_lifetime в настройках пула
            
            logger.info(f"🧹 PostgreSQL cleanup: пул размер {initial_size}")
            return 0  # Placeholder
            
        except Exception as e:
            logger.error(f"⚠️ Cleanup error: {e}")
            return 0
    
    @property
    def is_connected(self) -> bool:
        """Проверяет, установлено ли соединение с базой данных"""
        return self.pool is not None and not self.pool._closed
    
    def reset_stats(self) -> None:
        """Сбрасывает статистику (для тестирования)"""
        self._total_queries = 0
        self._total_query_time = 0.0
        self._failed_queries = 0
        self._connections_created = 0
        self._connection_errors = 0
        logger.info("📊 PostgreSQL статистика сброшена")
