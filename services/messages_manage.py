from aiogram.fsm.context import FSMContext
import aiosqlite
from core.bot import bot
from config.settings import DATABASE_PATH
import logging
from aiogram.exceptions import TelegramAPIError
from aiogram import types

logger = logging.getLogger(__name__)


async def non_authorized(call_id: int, mess_id: int, state, db_connection: aiosqlite.Connection) -> None:
    """Удаляет сообщение и показывает главное меню для неавторизованных пользователей."""
    if mess_id:
        try:
            await bot.delete_message(call_id, mess_id)
        except TelegramAPIError:
            logger.error(f"Не удалось удалить сообщение {mess_id} для пользователя {call_id}", exc_info=True)
    from modules.user_onboarding.services import process_start_command

    await process_start_command(user_id=call_id, state=state, db_connection=db_connection)


async def delete_previous_messages(user_id: int, state: FSMContext) -> None:
    """Удаляет предыдущие сообщения бота (стикер и основное сообщение), если они существуют."""
    if state is not None:
        state_data = await state.get_data()
        if state_data is None:
            return
    else:
        return
    previous_sticker_id = state_data.get("previous_sticker_id") 
    previous_message_id = state_data.get("previous_message_id")
    previous_menu_id = state_data.get("previous_menu_id") # New
    previous_code_id = state_data.get("previous_code_id") # New

    if previous_sticker_id:
        try:
            await bot.delete_message(user_id, previous_sticker_id)
        except TelegramAPIError:
            logger.debug(f"Не удалось удалить стикер {previous_sticker_id} для пользователя {user_id}")

    if previous_message_id:
        try:
            await bot.delete_message(user_id, previous_message_id)
        except TelegramAPIError:
            logger.debug(f"Не удалось удалить сообщение {previous_message_id} для пользователя {user_id}")

    if previous_menu_id: # New
        try:
            await bot.delete_message(user_id, previous_menu_id)
        except TelegramAPIError:
            logger.debug(f"Не удалось удалить сообщение {previous_menu_id} для пользователя {user_id}")

    if previous_code_id: # New
        try:
            await bot.delete_message(user_id, previous_code_id)
        except TelegramAPIError:
            logger.debug(f"Не удалось удалить сообщение {previous_code_id} для пользователя {user_id}")

    # Clear these specific keys after attempting deletion
    # This prevents re-deletion attempts on subsequent calls if the message was already gone
    if "previous_sticker_id" in state_data: del state_data["previous_sticker_id"]
    if "previous_message_id" in state_data: del state_data["previous_message_id"]
    if "previous_menu_id" in state_data: del state_data["previous_menu_id"]
    if "previous_code_id" in state_data: del state_data["previous_code_id"]
    await state.set_data(state_data) # Update the state after deletion


async def send_sticker_and_message_with_cleanup(
    user_id: int,
    sticker_path: str,
    message_text: str,
    state: FSMContext,
    markup: types.InlineKeyboardMarkup = None,
    message_type: str = None, # New parameter
) -> None:
    """
    Отправляет стикер и сообщение, очищая предыдущие,
    и сохраняет идентификаторы новых сообщений в состоянии.
    """
    await delete_previous_messages(user_id, state)

    sticker_message = await bot.send_sticker(
        user_id, sticker=types.FSInputFile(sticker_path)
    )
    main_message = await bot.send_message(
        user_id, message_text, reply_markup=markup, parse_mode="HTML"
    )

    update_data = {
        "previous_sticker_id": sticker_message.message_id,
    }
    if message_type == "menu":
        update_data["previous_menu_id"] = main_message.message_id
        update_data["previous_message_id"] = None # Ensure old message_id is cleared
    elif message_type == "code":
        update_data["previous_code_id"] = main_message.message_id
        update_data["previous_message_id"] = None # Ensure old message_id is cleared
    else:
        update_data["previous_message_id"] = main_message.message_id
        update_data["previous_menu_id"] = None # Ensure old menu_id is cleared
        update_data["previous_code_id"] = None # Ensure old code_id is cleared

    await state.update_data(**update_data)


async def send_message_with_cleanup(
    user_id: int, message_text: str, state: FSMContext, markup: any = None, message_type: str = None # New parameter
) -> object:
    """
    Отправляет сообщение пользователю, очищая предыдущее сообщение и стикер,
    и сохраняет идентификатор нового сообщения в состоянии.
    """
    await delete_previous_messages(user_id, state)

    bot_message = await bot.send_message(
        user_id, message_text, reply_markup=markup, parse_mode="HTML"
    )

    update_data = {
        "previous_sticker_id": None, # No sticker in this function
    }
    if message_type == "menu":
        update_data["previous_menu_id"] = bot_message.message_id
        update_data["previous_message_id"] = None # Ensure old message_id is cleared
    elif message_type == "code":
        update_data["previous_code_id"] = bot_message.message_id
        update_data["previous_message_id"] = None # Ensure old message_id is cleared
    else:
        update_data["previous_message_id"] = bot_message.message_id
        update_data["previous_menu_id"] = None # Ensure old menu_id is cleared
        update_data["previous_code_id"] = None # Ensure old code_id is cleared

    await state.update_data(**update_data)


    return bot_message


async def broadcast_message(db: aiosqlite.Connection, message: types.Message) -> None:
    """Рассылка сообщения всем пользователям."""
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
                logger.error(
                    f"Не удалось переслать сообщение пользователю {user[0]}:",
                    exc_info=True,
                )
    except aiosqlite.Error:
        logger.error("Ошибка при рассылке сообщений:", exc_info=True)
