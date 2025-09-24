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


class AntiSpamBot:
    def __init__(self, bot_token: str, redis_url: str, dependencies: dict):
        self.bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        # Redis storage for FSM
        storage = RedisStorage.from_url(redis_url)
        self.dp = Dispatcher(storage=storage)

        # Создаем TelegramChatGateway
        from ...adapter.gateway.telegram_chat_gateway import TelegramChatGateway
        telegram_chat_gateway = TelegramChatGateway(self.bot)

        # Создаем TelegramGateway для BanUserUseCase
        from ...adapter.gateway.telegram_gateway import TelegramGateway
        telegram_gateway = TelegramGateway(self.bot)

        # Устанавливаем telegram_gateway в ban_user_usecase
        if "ban_user_usecase" in dependencies:
            dependencies["ban_user_usecase"].telegram_gateway = telegram_gateway

        # Сохраняем зависимости для использования в handlers
        self.dp["deps"] = dependencies
        self.dp["deps"]["telegram_chat_gateway"] = telegram_chat_gateway
        self.dp["deps"]["telegram_gateway"] = telegram_gateway

        # Извлекаем admin_users из зависимостей
        config = dependencies.get("config", {})
        admin_users = []

        if isinstance(config, dict):
            admin_users = config.get("admin_users", [])
        elif hasattr(config, "telegram") and hasattr(config.telegram, "admin_users"):
            admin_users = config.telegram.admin_users

        # СНАЧАЛА регистрируем middlewares (порядок важен!)
        # 1. Сначала dependency injection
        self.dp.message.middleware(DependencyMiddleware())
        # 2. Потом throttling
        self.dp.message.middleware(ThrottlingMiddleware())
        # 3. Потом авторизация
        self.dp.message.middleware(AuthMiddleware(admin_user_ids=admin_users))
        # 4. Потом проверка владения чатом (временно отключено для тестирования)
        # self.dp.message.middleware(ChatOwnershipMiddleware(self.dp["deps"]["chat_repository"]))

        # Также регистрируем для callback queries
        self.dp.callback_query.middleware(DependencyMiddleware())
        self.dp.callback_query.middleware(ThrottlingMiddleware())
        self.dp.callback_query.middleware(AuthMiddleware(admin_user_ids=admin_users))
        # self.dp.callback_query.middleware(ChatOwnershipMiddleware(self.dp["deps"]["chat_repository"]))

        # Регистрируем для my_chat_member (события добавления/удаления бота)
        self.dp.my_chat_member.middleware(DependencyMiddleware())

        # ПОТОМ регистрируем handlers (после middlewares и зависимостей)
        self._setup_handlers()

    def _setup_handlers(self):
        """Настройка обработчиков"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            logger.info("🔧 Регистрация обработчиков...")
            
            # Основные обработчики сообщений
            message.register_handlers(self.dp)
            logger.info("✅ Message handlers зарегистрированы")

            # Админ команды
            admin.register_handlers(self.dp)
            logger.info("✅ Admin handlers зарегистрированы")

            # Callback buttons
            callback.register_handlers(self.dp)
            logger.info("✅ Callback handlers зарегистрированы")

            # Интеграция с основными детекторами (CAS, RuSpam, BotHub)
            detector_integration.register_handlers(self.dp)
            logger.info("✅ Detector integration handlers зарегистрированы")

            # Управление настройками BotHub
            bothub_settings.register_bothub_settings_handlers(self.dp)
            logger.info("✅ BotHub settings handlers зарегистрированы")

            # Управление группами
            chat_management.register_chat_management_handlers(
                self.dp, 
                self.dp["deps"]["user_repository"], 
                self.dp["deps"]["chat_repository"]
            )
            logger.info("✅ Chat management handlers зарегистрированы")

            # Автоматическое определение чатов
            auto_chat_detection.register_auto_chat_detection_handlers(
                self.dp,
                self.dp["deps"]["user_repository"],
                self.dp["deps"]["chat_repository"],
                self.dp["deps"]["telegram_chat_gateway"]
            )
            logger.info("✅ Auto chat detection handlers зарегистрированы")

            # Современные возможности Telegram API
            modern_features.register_handlers(self.dp)
            logger.info("✅ Modern features handlers зарегистрированы")
            
            logger.info("🎉 Все обработчики успешно зарегистрированы!")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при регистрации обработчиков: {e}")
            raise

    async def start_polling(self):
        """Запуск бота в режиме polling"""
        try:
            print("Starting bot...")

            # Удаляем webhook если он активен
            try:
                await self.bot.delete_webhook(drop_pending_updates=True)
                print("✅ Webhook удален")
            except Exception as e:
                print(f"⚠️ Ошибка при удалении webhook: {e}")

            await self.dp.start_polling(self.bot, skip_updates=True)
        finally:
            await self.bot.session.close()
