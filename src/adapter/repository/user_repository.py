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
        INSERT INTO users (telegram_id, username, first_name, last_name, status, message_count, spam_score, daily_spam_count, last_spam_reset_date)
        VALUES ($1, $2, $3, $4, $5, 0, 0.0, 0, NOW())
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

    async def increment_spam_count(self, telegram_id: int) -> int:
        """Увеличить счетчик спама за день и вернуть текущее значение"""
        query = """
        UPDATE users 
        SET 
            daily_spam_count = CASE 
                WHEN last_spam_reset_date IS NULL OR 
                     EXTRACT(EPOCH FROM (NOW() - last_spam_reset_date)) >= 86400 
                THEN 1
                ELSE daily_spam_count + 1
            END,
            last_spam_reset_date = CASE 
                WHEN last_spam_reset_date IS NULL OR 
                     EXTRACT(EPOCH FROM (NOW() - last_spam_reset_date)) >= 86400 
                THEN NOW()
                ELSE last_spam_reset_date
            END
        WHERE telegram_id = $1
        RETURNING daily_spam_count
        """

        async with self.db.acquire() as conn:
            result = await conn.fetchval(query, telegram_id)
            return result or 0

    async def reset_daily_spam_count(self, telegram_id: int) -> None:
        """Сбросить счетчик спама за день"""
        query = """
        UPDATE users 
        SET daily_spam_count = 0, last_spam_reset_date = NOW()
        WHERE telegram_id = $1
        """

        async with self.db.acquire() as conn:
            await conn.execute(query, telegram_id)

    async def get_daily_spam_count(self, telegram_id: int) -> int:
        """Получить текущий счетчик спама за день"""
        query = """
        SELECT 
            CASE 
                WHEN last_spam_reset_date IS NULL OR 
                     EXTRACT(EPOCH FROM (NOW() - last_spam_reset_date)) >= 86400 
                THEN 0
                ELSE daily_spam_count
            END as current_spam_count
        FROM users 
        WHERE telegram_id = $1
        """

        async with self.db.acquire() as conn:
            result = await conn.fetchval(query, telegram_id)
            return result or 0

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

    async def update_user(self, user: User) -> None:
        """Обновить пользователя"""
        query = """
        UPDATE users 
        SET username = $1, first_name = $2, last_name = $3, status = $4,
            message_count = $5, spam_score = $6, daily_spam_count = $7,
            last_spam_reset_date = $8, first_message_at = $9, last_message_at = $10,
            is_admin = $11, bothub_token = $12, system_prompt = $13, bothub_configured = $14
        WHERE telegram_id = $15
        """

        async with self.db.acquire() as conn:
            await conn.execute(
                query,
                user.username,
                user.first_name,
                user.last_name,
                user.status.value,
                user.message_count,
                user.spam_score,
                user.daily_spam_count,
                user.last_spam_reset_date,
                user.first_message_at,
                user.last_message_at,
                user.is_admin,
                user.bothub_token,
                user.system_prompt,
                user.bothub_configured,
                user.telegram_id,
            )

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
            daily_spam_count=row.get("daily_spam_count", 0),
            last_spam_reset_date=row.get("last_spam_reset_date"),
            first_message_at=row["first_message_at"],
            last_message_at=row["last_message_at"],
            created_at=row["created_at"],
            is_admin=row["is_admin"],
            # BotHub настройки
            bothub_token=row.get("bothub_token"),
            system_prompt=row.get("system_prompt"),
            bothub_configured=row.get("bothub_configured", False),
        )
