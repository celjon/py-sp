import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from .handlers import message, admin, callback, detector_integration, modern_features, bothub_settings, chat_management, auto_chat_detection
from .middlewares.throttling import ThrottlingMiddleware
from .middlewares.auth import AuthMiddleware
from .middlewares.dependency import DependencyMiddleware
from .middlewares.chat_isolation import ChatOwnershipMiddleware
from .middlewares.flood_control import FloodControlMiddleware


class AntiSpamBot:
    def __init__(self, bot_token: str, redis_url: str, dependencies: dict):
        self.bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        storage = RedisStorage.from_url(redis_url)
        self.dp = Dispatcher(storage=storage)

        from ...adapter.gateway.telegram_chat_gateway import TelegramChatGateway
        telegram_chat_gateway = TelegramChatGateway(self.bot)

        from ...adapter.gateway.telegram_gateway import TelegramGateway
        telegram_gateway = TelegramGateway(self.bot)

        if "ban_user_usecase" in dependencies:
            dependencies["ban_user_usecase"].telegram_gateway = telegram_gateway

        self.dp["deps"] = dependencies
        self.dp["deps"]["telegram_chat_gateway"] = telegram_chat_gateway
        self.dp["deps"]["telegram_gateway"] = telegram_gateway

        config = dependencies.get("config", {})
        admin_users = []

        if isinstance(config, dict):
            admin_users = config.get("admin_users", [])
        elif hasattr(config, "telegram") and hasattr(config.telegram, "admin_users"):
            admin_users = config.telegram.admin_users

        self.dp.message.middleware(DependencyMiddleware())
        self.dp.message.middleware(FloodControlMiddleware(max_messages=5, time_window=5, mute_duration=30))
        self.dp.message.middleware(ThrottlingMiddleware())
        self.dp.message.middleware(AuthMiddleware(admin_user_ids=admin_users))

        self.dp.callback_query.middleware(DependencyMiddleware())
        self.dp.callback_query.middleware(ThrottlingMiddleware())
        self.dp.callback_query.middleware(AuthMiddleware(admin_user_ids=admin_users))

        self.dp.my_chat_member.middleware(DependencyMiddleware())

        self._setup_handlers()

    def _setup_handlers(self):
        """Настройка обработчиков"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            logger.info("🔧 Регистрация обработчиков...")
            
            message.register_handlers(self.dp)
            logger.info("✅ Message handlers зарегистрированы")

            admin.register_handlers(self.dp)
            logger.info("✅ Admin handlers зарегистрированы")

            callback.register_handlers(self.dp)
            logger.info("✅ Callback handlers зарегистрированы")

            detector_integration.register_handlers(self.dp)
            logger.info("✅ Detector integration handlers зарегистрированы")

            bothub_settings.register_bothub_settings_handlers(self.dp)
            logger.info("✅ BotHub settings handlers зарегистрированы")

            chat_management.register_chat_management_handlers(
                self.dp, 
                self.dp["deps"]["user_repository"], 
                self.dp["deps"]["chat_repository"]
            )
            logger.info("✅ Chat management handlers зарегистрированы")

            auto_chat_detection.register_auto_chat_detection_handlers(
                self.dp,
                self.dp["deps"]["user_repository"],
                self.dp["deps"]["chat_repository"],
                self.dp["deps"]["telegram_chat_gateway"]
            )
            logger.info("✅ Auto chat detection handlers зарегистрированы")

            modern_features.register_handlers(self.dp)
            logger.info("✅ Modern features handlers зарегистрированы")
            
            logger.info("🎉 Все обработчики успешно зарегистрированы!")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при регистрации обработчиков: {e}")
            raise

    async def start_polling(self):
        """Запуск бота в режиме polling"""
        try:
            try:
                await self.bot.delete_webhook(drop_pending_updates=True)
            except Exception as e:
                pass

            await self.dp.start_polling(self.bot, skip_updates=True)
        finally:
            await self.bot.session.close()
