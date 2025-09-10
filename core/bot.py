"""
This module initializes the Telegram Bot and Dispatcher.

It sets up the bot with the provided token and configures the SQLite storage
for managing bot states and data.
"""
from aiogram import Bot, Dispatcher
from aiogram_sqlite_storage.sqlitestore import SQLStorage
from config.settings import TOKEN, DATABASE_PATH

# Initialize SQLite storage for the bot's FSM (Finite State Machine)
storage = SQLStorage(db_path=DATABASE_PATH)

# Initialize the Telegram Bot with the provided token
bot = Bot(token=TOKEN)

# Initialize the Dispatcher, which handles incoming updates and dispatches them to handlers
dp = Dispatcher(storage=storage)
