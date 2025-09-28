"""
Background задачи для очистки данных
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from .message_cleanup import MessageCleanupService

logger = logging.getLogger(__name__)


class BackgroundCleanupService:
    """Сервис для запуска фоновых задач очистки"""

    def __init__(self, message_cleanup: MessageCleanupService):
        self.message_cleanup = message_cleanup
        self.cleanup_task: asyncio.Task = None
        self.is_running = False

    async def start_cleanup_scheduler(self, interval_hours: int = 6) -> None:
        """
        Запускает планировщик очистки

        Args:
            interval_hours: Интервал между очистками в часах
        """
        if self.is_running:
            logger.warning("Cleanup scheduler is already running")
            return

        self.is_running = True
        self.cleanup_task = asyncio.create_task(self._cleanup_loop(interval_hours))
        logger.info(f"🕐 Started cleanup scheduler with {interval_hours}h interval")

    async def stop_cleanup_scheduler(self) -> None:
        """Останавливает планировщик очистки"""
        if not self.is_running or not self.cleanup_task:
            return

        self.is_running = False
        self.cleanup_task.cancel()

        try:
            await self.cleanup_task
        except asyncio.CancelledError:
            pass

        logger.info("🛑 Stopped cleanup scheduler")

    async def _cleanup_loop(self, interval_hours: int) -> None:
        """Основной цикл очистки"""
        interval_seconds = interval_hours * 3600

        while self.is_running:
            try:
                logger.info("🧹 Running scheduled cleanup...")

                old_messages_result = await self.message_cleanup.cleanup_old_messages(hours=48)

                deleted_messages_result = await self.message_cleanup.cleanup_deleted_messages(hours=24)

                logger.info(
                    f"🧹 Cleanup completed: "
                    f"old_messages={old_messages_result['deleted_count']}, "
                    f"deleted_messages={deleted_messages_result['deleted_count']}"
                )

                await asyncio.sleep(interval_seconds)

            except asyncio.CancelledError:
                logger.info("Cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(3600)

    async def run_manual_cleanup(self,
                                old_messages_hours: int = 48,
                                deleted_messages_hours: int = 24) -> Dict[str, Any]:
        """
        Запускает ручную очистку

        Args:
            old_messages_hours: Возраст сообщений для удаления
            deleted_messages_hours: Возраст помеченных как удаленные для физического удаления

        Returns:
            Результаты очистки
        """
        logger.info("🧹 Starting manual cleanup...")

        results = {
            "manual_cleanup": True,
            "started_at": datetime.now().isoformat(),
            "old_messages": {},
            "deleted_messages": {}
        }

        try:
            results["old_messages"] = await self.message_cleanup.cleanup_old_messages(
                hours=old_messages_hours
            )

            results["deleted_messages"] = await self.message_cleanup.cleanup_deleted_messages(
                hours=deleted_messages_hours
            )

            total_deleted = (results["old_messages"]["deleted_count"] +
                           results["deleted_messages"]["deleted_count"])

            results["total_deleted"] = total_deleted
            results["completed_at"] = datetime.now().isoformat()
            results["status"] = "success"

            logger.info(f"🧹 Manual cleanup completed: {total_deleted} messages deleted")

        except Exception as e:
            logger.error(f"Error in manual cleanup: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["completed_at"] = datetime.now().isoformat()

        return results