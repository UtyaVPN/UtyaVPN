import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from core.bot import bot
from services.db_operations import get_user_by_id, add_user
from modules.common.services import main_menu
from config.messages import OnboardingMessages
import aiosqlite

logger = logging.getLogger(__name__)

# Common caption for the welcome message
common_caption = OnboardingMessages.COMMON_CAPTION

# Caption displayed after a request is made
enter_caption = OnboardingMessages.ENTER_CAPTION


async def process_start_command(
    message: types.Message = None,
    user_id: int = None,
    state: FSMContext = None,
    is_sticker: bool = False,
    db_connection: aiosqlite.Connection = None,
) -> None:
    """
    Processes the start command and displays the appropriate menu based on user status.

    If the user is new, they are added to the database. Depending on their status
    (e.g., 'accepted', 'pending'), either the main menu or the onboarding menu
    with trial/purchase options is displayed.

    Args:
        message: The message object from the user.
        user_id: The user's ID.
        state: The FSM context.
        is_sticker: A flag to indicate if a sticker has already been sent.
        db_connection: The database connection.
    """
    user_id = message.from_user.id if message else user_id
    username = (
        f"@{message.from_user.username}"
        if message and message.from_user.username
        else f"user_id:{user_id}"
    )
    user = await get_user_by_id(db_connection, user_id)

    if not user:
        user = await add_user(db_connection, user_id, username)

    status = user[2]

    if status == "accepted":
        await main_menu(user_id=user_id, state=state, db_connection=db_connection)
    elif status in ("pending", "denied", "expired"):
        user_markup = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text=OnboardingMessages.TRIAL_PERIOD_BUTTON, callback_data="get_trial")],
                [types.InlineKeyboardButton(text=OnboardingMessages.BUY_SUBSCRIPTION_BUTTON, callback_data="buy_subscription")],
                [types.InlineKeyboardButton(text=OnboardingMessages.MORE_ABOUT_VPN_BUTTON, callback_data="more")],
            ]
        )

        caption = common_caption
        if status == "denied":
            caption = OnboardingMessages.REQUEST_DENIED + caption
        elif status == "expired":
            caption = OnboardingMessages.SUBSCRIPTION_EXPIRED + caption

        if not is_sticker:
            previous_sticker = await bot.send_sticker(
                chat_id=user_id, sticker=FSInputFile("assets/matrix.tgs")
            )
            await state.update_data(previous_sticker_id=previous_sticker.message_id)

        previous_message = await bot.send_message(
            chat_id=user_id, text=caption, reply_markup=user_markup, parse_mode="HTML"
        )
        await state.update_data(previous_message_id=previous_message.message_id)


async def process_get_trial_period(
    call: types.CallbackQuery, db_connection: aiosqlite.Connection
) -> None:
    """
    Processes a request for a trial period.

    This function checks the user's status and informs them if they have already
    sent a request. Otherwise, it confirms that their request has been received.

    Args:
        call: The callback query from the user.
        db_connection: The database connection.
    """
    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    if user and user[2] == "pending":
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text=OnboardingMessages.REQUEST_ALREADY_SENT,
            parse_mode="HTML",
        )
    else:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text=enter_caption,
            parse_mode="HTML",
        )
        # Logic for notifying the admin or automatically granting a trial period can be added here.
