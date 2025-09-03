import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from .handlers import message, admin, callback
from .middlewares.throttling import ThrottlingMiddleware
from .middlewares.auth import AuthMiddleware

class AntiSpamBot:
    def __init__(self, bot_token: str, redis_url: str, dependencies: dict):
        self.bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        # Redis storage for FSM
        storage = RedisStorage.from_url(redis_url)
        self.dp = Dispatcher(storage=storage)
        
        # Сохраняем зависимости для использования в handlers
        self.dp["deps"] = dependencies
        
        # Регистрируем middlewares
        self.dp.message.middleware(ThrottlingMiddleware())
        self.dp.message.middleware(AuthMiddleware())
        
        # Регистрируем handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Настройка обработчиков"""
        # Основные обработчики сообщений
        message.register_handlers(self.dp)
        
        # Админ команды
        admin.register_handlers(self.dp)
        
        # Callback buttons
        callback.register_handlers(self.dp)
    
    async def start_polling(self):
        """Запуск бота в режиме polling"""
        try:
            print("Starting bot...")
            await self.dp.start_polling(self.bot, skip_updates=True)
        finally:
            await self.bot.session.close()

