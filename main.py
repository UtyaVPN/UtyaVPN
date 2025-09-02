import asyncio
import locale
import logging

from core.bot import bot, dp
from core.database import init_conn_db, create_db_connection
from services.scheduler import start_scheduler
from services.vpn_manager import set_server_ip_async
from core.middlewares import CallbackLockMiddleware

# Import handlers from modules
from modules.admin.handlers import admin_router
from modules.vpn_management.handlers import vpn_management_router
from modules.user_onboarding.handlers import user_onboarding_router
from modules.common.handlers import common_router
from modules.user_onboarding.entry import user_onboarding_entry_router

# Устанавливаем локаль для форматирования времени
locale.setlocale(locale.LC_TIME, "ru_RU.UTF8")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Главная асинхронная функция для инициализации бота"""
    db_connection = await create_db_connection()

    await set_server_ip_async()  # Инициализация IP-адреса сервера
    await init_conn_db()  # Инициализация соединения с БД
    await start_scheduler(bot, db_connection)  # Запускаем планировщик задач
    await bot.delete_webhook(
        drop_pending_updates=True
    )  # Удаляем вебхуки, если они есть

    # Register middleware for callback query debouncing
    dp.callback_query.middleware(CallbackLockMiddleware())

    # Register routers from modules
    dp.include_router(user_onboarding_entry_router)
    dp.include_router(admin_router)
    dp.include_router(vpn_management_router)
    dp.include_router(user_onboarding_router)
    dp.include_router(common_router)

    try:
        await dp.start_polling(bot, db_connection=db_connection)  # Запускаем бота
    finally:
        await db_connection.close()
        logger.info("Database connection closed.")


if __name__ == "__main__":
    # Инициализируем соединение с базой данных и запускаем основную функцию
    asyncio.run(main())  # Запуск основной функции
