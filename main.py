import asyncio
import locale
import logging

from core.bot import bot, dp
from core.database import create_db_connection, init_conn_db
from core.middlewares import CallbackLockMiddleware
from modules.admin.handlers import admin_router
from modules.common.handlers import common_router
from modules.user_onboarding.entry import user_onboarding_entry_router
from modules.user_onboarding.handlers import user_onboarding_router
from modules.vpn_management.handlers import vpn_management_router
from services.scheduler import start_scheduler
from services.vpn_manager import set_server_ip_async

# Set the locale for time formatting
locale.setlocale(locale.LC_TIME, "ru_RU.UTF8")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """
    The main asynchronous function to initialize and run the bot.

    This function sets up the database connection, initializes the server IP,
    starts the task scheduler, configures middleware, registers all the
    necessary routers, and starts the bot polling.
    """
    db_connection = await create_db_connection()

    await set_server_ip_async()  # Initialize the server IP address
    await init_conn_db()  # Initialize the database connection
    await start_scheduler(bot, db_connection)  # Start the task scheduler
    await bot.delete_webhook(drop_pending_updates=True)  # Remove any existing webhooks

    # Register middleware for callback query debouncing
    dp.callback_query.middleware(CallbackLockMiddleware())

    # Register routers from modules
    dp.include_router(user_onboarding_entry_router)
    dp.include_router(admin_router)
    dp.include_router(vpn_management_router)
    dp.include_router(user_onboarding_router)
    dp.include_router(common_router)

    try:
        await dp.start_polling(bot, db_connection=db_connection)  # Start the bot
    finally:
        await db_connection.close()
        logger.info("Database connection closed.")


if __name__ == "__main__":
    # Initialize the database connection and run the main function
    asyncio.run(main())
