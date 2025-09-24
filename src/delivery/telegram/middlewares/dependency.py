from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
import logging

logger = logging.getLogger(__name__)


class DependencyMiddleware(BaseMiddleware):
    """
    Middleware для передачи зависимостей из dispatcher в хендлеры
    Решает проблему недоступности deps в kwargs хендлеров
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Основной метод middleware - инжектирует зависимости в handlers"""

        # В aiogram 3.x dispatcher доступен через data["dispatcher"]
        dispatcher = data.get("dispatcher")

        if dispatcher:
            try:
                # Согласно официальной документации aiogram 3.x,
                # workflow_data является правильным способом доступа к пользовательским данным
                # Но мы также используем прямой доступ dp["deps"] как fallback
                deps = None

                # Способ 1: Прямой доступ к dispatcher как к словарю (работает в aiogram 3.x)
                try:
                    deps = dispatcher["deps"]
                    logger.debug(f"[DEPS] ✅ Dependencies loaded successfully ({len(deps) if deps else 0} services)")
                except (KeyError, TypeError) as e:
                    logger.debug(f"[DEPS] Direct access failed: {e}")

                # Способ 2: Через workflow_data (если прямой доступ не сработал)
                if deps is None and hasattr(dispatcher, 'workflow_data'):
                    workflow_data = dispatcher.workflow_data
                    if 'deps' in workflow_data:
                        deps = workflow_data['deps']
                        logger.info(f"[DEPS] ✅ Got dependencies via workflow_data: {list(deps.keys()) if deps else 'empty'}")
                    else:
                        logger.warning("[DEPS] ❌ 'deps' not found in workflow_data")

                # Инжектируем зависимости в data для handlers
                if deps:
                    data["deps"] = deps

                    # Получаем пользователя из репозитория для обработчиков
                    if hasattr(event, 'from_user') and event.from_user:
                        user_repo = deps.get("user_repository")
                        chat_repo = deps.get("chat_repository")

                        if user_repo:
                            try:
                                user = await user_repo.get_user(event.from_user.id)
                                if user:
                                    data["user"] = user
                                    logger.debug(f"[DEPS] ✅ User loaded: {event.from_user.id}")

                                    # Проверяем владение группами
                                    if chat_repo:
                                        try:
                                            user_chats = await chat_repo.get_user_chats(event.from_user.id, active_only=True)
                                            data["user_chats"] = user_chats
                                            data["is_group_owner"] = len(user_chats) > 0
                                            logger.debug(f"[DEPS] ✅ User has {len(user_chats)} chats")
                                        except Exception as e:
                                            logger.error(f"[DEPS] Error loading user chats: {e}")
                            except Exception as e:
                                logger.error(f"[DEPS] Error loading user: {e}")
                else:
                    logger.warning("[DEPS] ❌ No dependencies found, setting empty dict")
                    data["deps"] = {}

            except Exception as e:
                logger.error(f"[DEPS] Error accessing dependencies: {e}")
                data["deps"] = {}
        else:
            logger.warning("[DEPS] No dispatcher found in data")
            data["deps"] = {}

        # Продолжаем обработку к следующему middleware/handler
        return await handler(event, data)