"""
Service для очистки старых сообщений из базы данных
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from ....adapter.repository.message_repository import MessageRepository

logger = logging.getLogger(__name__)


class MessageCleanupService:
    """Сервис для очистки старых сообщений"""

    def __init__(self, message_repo: MessageRepository):
        self.message_repo = message_repo

    async def cleanup_old_messages(self, hours: int = 48) -> Dict[str, Any]:
        """
        Удаляет сообщения старше указанного времени

        Args:
            hours: Возраст сообщений в часах (по умолчанию 48)

        Returns:
            Словарь со статистикой очистки
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        logger.info(f"🧹 Starting cleanup of messages older than {hours} hours (before {cutoff_time})")

        try:
            count_query = """
            SELECT COUNT(*) FROM messages
            WHERE created_at < $1
            """

            delete_query = """
            DELETE FROM messages
            WHERE created_at < $1
            """

            async with self.message_repo.db.acquire() as conn:
                messages_to_delete = await conn.fetchval(count_query, cutoff_time)

                if messages_to_delete == 0:
                    logger.info("🧹 No old messages to clean up")
                    return {
                        "deleted_count": 0,
                        "cutoff_hours": hours,
                        "cutoff_time": cutoff_time.isoformat(),
                        "status": "success"
                    }

                result = await conn.execute(delete_query, cutoff_time)

                deleted_count = int(result.split()[-1]) if result.split() else 0

                logger.info(f"🧹 Successfully deleted {deleted_count} old messages")

                return {
                    "deleted_count": deleted_count,
                    "cutoff_hours": hours,
                    "cutoff_time": cutoff_time.isoformat(),
                    "status": "success"
                }

        except Exception as e:
            logger.error(f"🚨 Error during message cleanup: {e}")
            return {
                "deleted_count": 0,
                "cutoff_hours": hours,
                "cutoff_time": cutoff_time.isoformat(),
                "status": "error",
                "error": str(e)
            }

    async def cleanup_deleted_messages(self, hours: int = 24) -> Dict[str, Any]:
        """
        Удаляет сообщения которые были помечены как удаленные более N часов назад

        Args:
            hours: Сколько часов должно пройти после пометки deleted_at

        Returns:
            Статистика очистки
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        logger.info(f"🗑️ Starting cleanup of deleted messages older than {hours} hours (deleted before {cutoff_time})")

        try:
            count_query = """
            SELECT COUNT(*) FROM messages
            WHERE deleted_at IS NOT NULL AND deleted_at < $1
            """

            delete_query = """
            DELETE FROM messages
            WHERE deleted_at IS NOT NULL AND deleted_at < $1
            """

            async with self.message_repo.db.acquire() as conn:
                messages_to_delete = await conn.fetchval(count_query, cutoff_time)

                if messages_to_delete == 0:
                    logger.info("🗑️ No old deleted messages to clean up")
                    return {
                        "deleted_count": 0,
                        "cutoff_hours": hours,
                        "cutoff_time": cutoff_time.isoformat(),
                        "status": "success"
                    }

                result = await conn.execute(delete_query, cutoff_time)
                deleted_count = int(result.split()[-1]) if result.split() else 0

                logger.info(f"🗑️ Successfully cleaned up {deleted_count} old deleted messages")

                return {
                    "deleted_count": deleted_count,
                    "cutoff_hours": hours,
                    "cutoff_time": cutoff_time.isoformat(),
                    "status": "success"
                }

        except Exception as e:
            logger.error(f"🚨 Error during deleted messages cleanup: {e}")
            return {
                "deleted_count": 0,
                "cutoff_hours": hours,
                "cutoff_time": cutoff_time.isoformat(),
                "status": "error",
                "error": str(e)
            }

    async def get_cleanup_stats(self) -> Dict[str, Any]:
        """Получить статистику для планирования очистки"""
        try:
            now = datetime.now(timezone.utc)

            stats_query = """
            SELECT
                COUNT(*) as total_messages,
                COUNT(*) FILTER (WHERE created_at < $1) as older_than_48h,
                COUNT(*) FILTER (WHERE created_at < $2) as older_than_24h,
                COUNT(*) FILTER (WHERE deleted_at IS NOT NULL) as marked_deleted,
                COUNT(*) FILTER (WHERE deleted_at IS NOT NULL AND deleted_at < $2) as old_deleted,
                MIN(created_at) as oldest_message,
                MAX(created_at) as newest_message,
                pg_size_pretty(pg_total_relation_size('messages')) as table_size
            FROM messages
            """

            cutoff_48h = now - timedelta(hours=48)
            cutoff_24h = now - timedelta(hours=24)

            async with self.message_repo.db.acquire() as conn:
                stats = await conn.fetchrow(stats_query, cutoff_48h, cutoff_24h)

                return {
                    "total_messages": stats["total_messages"],
                    "older_than_48h": stats["older_than_48h"],
                    "older_than_24h": stats["older_than_24h"],
                    "marked_deleted": stats["marked_deleted"],
                    "old_deleted_messages": stats["old_deleted"],
                    "oldest_message": stats["oldest_message"].isoformat() if stats["oldest_message"] else None,
                    "newest_message": stats["newest_message"].isoformat() if stats["newest_message"] else None,
                    "table_size": stats["table_size"],
                    "generated_at": now.isoformat()
                }

        except Exception as e:
            logger.error(f"Error getting cleanup stats: {e}")
            return {"error": str(e)}