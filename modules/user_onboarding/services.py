import logging
import os
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from core.bot import bot
from services.db_operations import get_user_by_id, add_user
from modules.common.services import main_menu
from config.messages import OnboardingMessages
import aiosqlite

logger = logging.getLogger(__name__)

# Общая подпись для приветственного сообщения
common_caption = OnboardingMessages.COMMON_CAPTION

# Подпись, отображаемая после запроса
enter_caption = OnboardingMessages.ENTER_CAPTION


async def process_start_command(message: types.Message = None, user_id: int = None, state: FSMContext = None, issticker = None, db_connection: aiosqlite.Connection = None):
    """Processes the start command and displays the appropriate menu."""
    user_id = message.from_user.id if message else user_id
    username = f"@{message.from_user.username}" if message and message.from_user.username else f"user_id:{message.from_user.id}"
    user = await get_user_by_id(db_connection, user_id)

    if not user:
        user = await add_user(db_connection, user_id, username)

    status = user[2]

    if status == "accepted":
        await main_menu(user_id=user_id, state=state, db_connection=db_connection)

    elif status in ("pending", "denied", "expired"):
        trial_button = types.InlineKeyboardButton(
            text=OnboardingMessages.TRIAL_PERIOD_BUTTON, callback_data="get_trial"
        )
        buy_button = types.InlineKeyboardButton(
            text=OnboardingMessages.BUY_SUBSCRIPTION_BUTTON, callback_data="buy_subscription"
        )
        more_info_button = types.InlineKeyboardButton(
            text=OnboardingMessages.MORE_ABOUT_VPN_BUTTON, callback_data="more"
        )

        user_markup = types.InlineKeyboardMarkup(
            inline_keyboard=[[trial_button], [buy_button], [more_info_button]]
        )

        caption = common_caption
        if status == "denied":
            caption = OnboardingMessages.REQUEST_DENIED + caption
        elif status == "expired":
            caption = OnboardingMessages.SUBSCRIPTION_EXPIRED + caption
        if not issticker:
            previuos_sticker = await bot.send_sticker(
                chat_id=user_id,
                sticker=FSInputFile("assets/matrix.tgs"),
            )
        previuos_message = await bot.send_message(
            chat_id=user_id,
            text=caption,
            reply_markup=user_markup,
            parse_mode="HTML",
        )
        await state.update_data(previous_message_id=previuos_message.message_id)
        if not issticker:
            await state.update_data(previous_sticker_id=previuos_sticker.message_id)


async def process_get_trial_period(call: types.CallbackQuery, db_connection: aiosqlite.Connection):
    """Обрабатывает запрос на пробный период."""
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
        # Здесь может быть логика для отправки уведомления администратору
        # или автоматической выдачи пробного периода.
