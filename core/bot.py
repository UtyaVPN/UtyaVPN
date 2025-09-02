from aiogram import Bot, Dispatcher
from aiogram_sqlite_storage.sqlitestore import SQLStorage
from config.settings import TOKEN, DATABASE_PATH

storage = SQLStorage(db_path=DATABASE_PATH)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)