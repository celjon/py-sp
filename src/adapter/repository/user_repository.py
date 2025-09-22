from typing import Optional
import asyncpg
from ...domain.entity.user import User, UserStatus
from ...lib.clients.postgres_client import PostgresClient


class UserRepository:
    def __init__(self, db_client: PostgresClient):
        self.db = db_client

    async def get_user(self, telegram_id: int) -> Optional[User]:
        """Получить пользователя по telegram_id"""
        query = """
        SELECT * FROM users WHERE telegram_id = $1
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, telegram_id)
            return self._row_to_user(row) if row else None

    async def create_user(
        self, telegram_id: int, username: str = None, first_name: str = None, last_name: str = None
    ) -> User:
        """Создать нового пользователя"""
        query = """
        INSERT INTO users (telegram_id, username, first_name, last_name, status, message_count, spam_score)
        VALUES ($1, $2, $3, $4, $5, 0, 0.0)
        RETURNING *
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query, telegram_id, username, first_name, last_name, UserStatus.ACTIVE.value
            )
            return self._row_to_user(row)

    async def update_user_status(self, telegram_id: int, status: UserStatus) -> None:
        """Обновить статус пользователя"""
        query = "UPDATE users SET status = $1 WHERE telegram_id = $2"

        async with self.db.acquire() as conn:
            await conn.execute(query, status.value, telegram_id)

    async def update_user_stats(
        self, telegram_id: int, message_count: int, spam_score: float
    ) -> None:
        """Обновить статистику пользователя"""
        query = """
        UPDATE users 
        SET message_count = $1, spam_score = $2, last_message_at = NOW()
        WHERE telegram_id = $3
        """

        async with self.db.acquire() as conn:
            await conn.execute(query, message_count, spam_score, telegram_id)

    async def is_user_approved(self, telegram_id: int) -> bool:
        """Проверить, одобрен ли пользователь"""
        query = """
        SELECT EXISTS(SELECT 1 FROM approved_users WHERE telegram_id = $1)
        """

        async with self.db.acquire() as conn:
            return await conn.fetchval(query, telegram_id)

    async def add_to_approved(self, telegram_id: int) -> None:
        """Добавить пользователя в список одобренных"""
        query = """
        INSERT INTO approved_users (telegram_id, created_at) 
        VALUES ($1, NOW()) 
        ON CONFLICT (telegram_id) DO NOTHING
        """

        async with self.db.acquire() as conn:
            await conn.execute(query, telegram_id)

    async def is_user_banned(self, user_id: int, chat_id: int) -> bool:
        """Проверить, забанен ли пользователь в чате"""
        # Временная реализация - проверяем статус пользователя
        # В будущем нужно создать таблицу banned_users с chat_id
        user = await self.get_user(user_id)
        if user and user.status == UserStatus.BANNED:
            return True
        return False

    async def get_banned_users(self, chat_id: int) -> list:
        """Получить список забаненных пользователей в чате"""
        # Временная реализация - возвращаем всех забаненных пользователей
        # В будущем нужно фильтровать по chat_id
        query = """
        SELECT telegram_id, username, first_name, last_name, created_at
        FROM users WHERE status = $1
        ORDER BY created_at DESC
        """

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, UserStatus.BANNED.value)
            return [
                {
                    "user_id": row["telegram_id"],
                    "username": row["username"] or f"{row['first_name']} {row['last_name'] or ''}".strip(),
                    "banned_at": row["created_at"].strftime("%Y-%m-%d %H:%M"),
                    "ban_reason": "Spam detection",
                    "last_message": "N/A"
                }
                for row in rows
            ]

    async def get_user_info(self, user_id: int) -> dict:
        """Получить информацию о пользователе"""
        user = await self.get_user(user_id)
        if user:
            return {
                "username": user.username or f"{user.first_name} {user.last_name or ''}".strip(),
                "status": user.status.value,
                "message_count": user.message_count,
                "spam_score": user.spam_score
            }
        return {"username": f"ID {user_id}", "status": "unknown"}

    async def unban_user(self, user_id: int, chat_id: int) -> None:
        """Разбанить пользователя"""
        # Обновляем статус пользователя на ACTIVE
        await self.update_user_status(user_id, UserStatus.ACTIVE)

    def _row_to_user(self, row: asyncpg.Record) -> User:
        """Преобразовать строку БД в объект User"""
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            status=UserStatus(row["status"]),
            message_count=row["message_count"],
            spam_score=row["spam_score"],
            first_message_at=row["first_message_at"],
            last_message_at=row["last_message_at"],
            created_at=row["created_at"],
            is_admin=row["is_admin"],
        )
