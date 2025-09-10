import aiosqlite
import logging
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)


async def create_db_connection() -> aiosqlite.Connection:
    """
    Creates and returns a database connection with WAL mode enabled.

    Returns:
        An aiosqlite.Connection object.

    Raises:
        aiosqlite.Error: If the database connection fails.
    """
    try:
        db = await aiosqlite.connect(DATABASE_PATH, timeout=10)
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.commit()
        logger.info("Database connection created with WAL mode.")
        return db
    except aiosqlite.Error:
        logger.error("Error creating database connection:", exc_info=True)
        raise


async def init_conn_db() -> None:
    """
    Initializes the database by creating necessary tables if they do not exist.

    This function ensures that the 'users', 'promo_codes', and 'user_promo_codes'
    tables are present in the database. It also enables WAL mode for better
    concurrency and performance.
    """
    try:
        async with aiosqlite.connect(DATABASE_PATH, timeout=10) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.commit()
            logger.info("WAL mode enabled for the database.")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    status TEXT DEFAULT 'pending',
                    access_granted_date TEXT,
                    access_duration INTEGER,
                    access_end_date TEXT,
                    last_notification_id INTEGER,
                    has_used_trial INTEGER DEFAULT 0
                )
                """
            )

            cursor = await db.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in await cursor.fetchall()]
            if "has_used_trial" not in columns:
                await db.execute("ALTER TABLE users ADD COLUMN has_used_trial INTEGER DEFAULT 0")
                logger.info("Added 'has_used_trial' column to 'users' table.")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,
                    days_duration INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    usage_count INTEGER DEFAULT 1
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_promo_codes (
                    user_id INTEGER NOT NULL,
                    promo_code TEXT NOT NULL,
                    PRIMARY KEY (user_id, promo_code),
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (promo_code) REFERENCES promo_codes(code)
                )
                """
            )
            await db.commit()
        logger.info("Database tables successfully created or already exist.")
    except aiosqlite.Error:
        logger.error("Error during database initialization:", exc_info=True)
