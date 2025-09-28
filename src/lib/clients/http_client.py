import aiohttp
import asyncio
from typing import Optional, Dict, Any


class HttpClient:
    """HTTP клиент для выполнения запросов к внешним API"""

    def __init__(self, timeout: int = 30, max_connections: int = 100):
        """
        Args:
            timeout: Таймаут запросов в секундах
            max_connections: Максимальное количество соединений
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.connector = aiohttp.TCPConnector(limit=max_connections)
        self.session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self):
        """Создает сессию если она еще не создана"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout, connector=self.connector)

    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Выполняет GET запрос

        Args:
            url: URL для запроса
            headers: HTTP заголовки
            params: GET параметры

        Returns:
            JSON ответ или None в случае ошибки
        """
        await self._ensure_session()

        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            return None

    async def post(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Выполняет POST запрос

        Args:
            url: URL для запроса
            data: Данные формы
            json: JSON данные
            headers: HTTP заголовки

        Returns:
            JSON ответ или None в случае ошибки
        """
        await self._ensure_session()

        try:
            async with self.session.post(url, data=data, json=json, headers=headers) as response:
                if response.status in [200, 201]:
                    return await response.json()
                else:
                    return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            return None

    async def get_text(self, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Выполняет GET запрос и возвращает текст

        Args:
            url: URL для запроса
            headers: HTTP заголовки

        Returns:
            Текст ответа или None в случае ошибки
        """
        await self._ensure_session()

        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            return None

    async def get_status(self, url: str, headers: Optional[Dict[str, str]] = None) -> int:
        """
        Выполняет GET запрос и возвращает только статус код

        Args:
            url: URL для запроса
            headers: HTTP заголовки

        Returns:
            HTTP статус код
        """
        await self._ensure_session()

        try:
            async with self.session.get(url, headers=headers) as response:
                return response.status
        except asyncio.TimeoutError:
            return 408
        except Exception as e:
            return 500

    async def close(self):
        """Закрывает HTTP сессию"""
        if self.session and not self.session.closed:
            await self.session.close()

        if self.connector:
            await self.connector.close()

    async def __aenter__(self):
        """Поддержка async context manager"""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Поддержка async context manager"""
        await self.close()
