from aiogram import types, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters.command import Command
import aiosqlite

from modules.user_onboarding.services import process_start_command

import logging

logger = logging.getLogger(__name__)

user_onboarding_entry_router = Router()


@user_onboarding_entry_router.message(Command("start"))
async def start_handler(
    message: types.Message = None,
    user_id: int = None,
    state: FSMContext = None,
    db_connection: aiosqlite.Connection = None,
) -> None:
    """
    Handles the /start command and displays the initial menu based on user status.

    Args:
        message: The message object from the user.
        user_id: The user's ID.
        state: The FSM context.
        db_connection: The database connection.
    """
    if state:
        await state.clear()
    await process_start_command(
        message=message, user_id=user_id, state=state, db_connection=db_connection
    )
