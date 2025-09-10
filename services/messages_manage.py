import logging

import aiosqlite
from aiogram import types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

from core.bot import bot

logger = logging.getLogger(__name__)


async def non_authorized(
    call_id: int, mess_id: int, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Handles unauthorized users by deleting the current message and showing the main menu.

    Args:
        call_id: The user's ID.
        mess_id: The ID of the message to delete.
        state: The FSM context.
        db_connection: The database connection.
    """
    if mess_id:
        try:
            await bot.delete_message(call_id, mess_id)
        except TelegramAPIError:
            logger.error(f"Failed to delete message {mess_id} for user {call_id}", exc_info=True)

    from modules.user_onboarding.services import process_start_command

    await process_start_command(user_id=call_id, state=state, db_connection=db_connection)


async def delete_previous_messages(user_id: int, state: FSMContext) -> None:
    """Deletes previous bot messages (sticker and main message) if they exist."""
    if state is None:
        return

    state_data = await state.get_data()
    if state_data is None:
        return

    for key in ["previous_sticker_id", "previous_message_id", "previous_menu_id", "previous_code_id"]:
        message_id = state_data.pop(key, None)
        if message_id:
            try:
                await bot.delete_message(user_id, message_id)
            except TelegramAPIError:
                logger.debug(f"Failed to delete message {message_id} for user {user_id}")

    await state.set_data(state_data)


async def send_sticker_and_message_with_cleanup(
    user_id: int,
    sticker_path: str,
    message_text: str,
    state: FSMContext,
    markup: types.InlineKeyboardMarkup | None = None,
    message_type: str | None = None,
) -> None:
    """
    Sends a sticker and a message, cleaning up previous ones, and saves the new
    message IDs to the state.

    Args:
        user_id: The user's ID.
        sticker_path: The path to the sticker file.
        message_text: The text of the message to send.
        state: The FSM context.
        markup: The inline keyboard markup.
        message_type: The type of message ('menu', 'code', or None).
    """
    await delete_previous_messages(user_id, state)

    sticker_message = await bot.send_sticker(user_id, sticker=types.FSInputFile(sticker_path))
    main_message = await bot.send_message(user_id, message_text, reply_markup=markup, parse_mode="HTML")

    update_data = {"previous_sticker_id": sticker_message.message_id}
    if message_type == "menu":
        update_data["previous_menu_id"] = main_message.message_id
    elif message_type == "code":
        update_data["previous_code_id"] = main_message.message_id
    else:
        update_data["previous_message_id"] = main_message.message_id

    await state.update_data(**update_data)


async def send_message_with_cleanup(
    user_id: int,
    message_text: str,
    state: FSMContext,
    markup: types.InlineKeyboardMarkup | None = None,
    message_type: str | None = None,
) -> types.Message:
    """
    Sends a message to the user, cleaning up the previous message and sticker,
    and saves the new message ID to the state.

    Args:
        user_id: The user's ID.
        message_text: The text of the message to send.
        state: The FSM context.
        markup: The inline keyboard markup.
        message_type: The type of message ('menu', 'code', or None).

    Returns:
        The sent message object.
    """
    await delete_previous_messages(user_id, state)

    bot_message = await bot.send_message(user_id, message_text, reply_markup=markup, parse_mode="HTML")

    update_data = {}
    if message_type == "menu":
        update_data["previous_menu_id"] = bot_message.message_id
    elif message_type == "code":
        update_data["previous_code_id"] = bot_message.message_id
    else:
        update_data["previous_message_id"] = bot_message.message_id

    await state.update_data(**update_data)

    return bot_message


async def broadcast_message(db: aiosqlite.Connection, message: types.Message) -> None:
    """Broadcasts a message to all users."""
    try:
        async with db.execute("SELECT id FROM users") as cursor:
            users = await cursor.fetchall()

        for user in users:
            try:
                await bot.copy_message(
                    chat_id=user[0],
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            except TelegramAPIError:
                logger.error(f"Failed to forward message to user {user[0]}:", exc_info=True)
    except aiosqlite.Error:
        logger.error("Error during message broadcast:", exc_info=True)
