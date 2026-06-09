import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from src.config import settings
from src.handlers import message_handler, review_handler
from src.services import storage, scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await storage.init_pool(settings.asyncpg_dsn)
    logger.info("DB pool initialized")

    redis_storage = RedisStorage.from_url(settings.redis_url)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=redis_storage)

    dp.include_router(review_handler.router)  # сначала команды и callback
    dp.include_router(message_handler.router)  # потом обычные сообщения

    scheduler.start_scheduler(bot)

    logger.info("Starting polling…")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
        )
    finally:
        scheduler.stop_scheduler()
        await storage.close_pool()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
