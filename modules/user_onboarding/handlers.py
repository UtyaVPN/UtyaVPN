import re
from aiogram import types, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from services.db_operations import (
    get_user_by_id,
    update_user_access,
    grant_access_and_create_config,
)
from aiogram.exceptions import TelegramAPIError
from services.messages_manage import non_authorized, send_sticker_and_message_with_cleanup, delete_previous_messages
from config.settings import TRIAL_CHANNEL_ID, PUBLIC_CHANNEL_URL
from core.bot import bot
from modules.common.services import main_menu
from modules.user_onboarding.services import enter_caption
from config.messages import OnboardingMessages
import aiosqlite

import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

user_onboarding_router = Router()


@user_onboarding_router.callback_query(lambda call: call.data == "get_trial")
async def get_trial_callback(call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection) -> None: 
    user_id = call.from_user.id

    user = await get_user_by_id(db_connection, user_id)

    if not user:
        await call.message.answer(OnboardingMessages.DB_ERROR)
        logger.error(f"User {user_id} not found in DB when trying to get trial.")
        return

    if user[7] == 1:
        caption = OnboardingMessages.COMMON_CAPTION + "\n\n"+ OnboardingMessages.TRIAL_USED
        if user[2] == "denied":
            caption = OnboardingMessages.REQUEST_DENIED + caption
        elif user[2] == "expired":
            caption = OnboardingMessages.SUBSCRIPTION_EXPIRED + caption
        current_caption = (
            call.message.caption if call.message.caption else call.message.text
        )

        feedback_text = re.sub(r"<[^>]+>", "", OnboardingMessages.TRIAL_USED)
        if feedback_text not in current_caption:
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
            await call.message.edit_text(text = caption, parse_mode="HTML", reply_markup=user_markup)
            return
        else:
            return

    try:
        chat_member = await bot.get_chat_member(TRIAL_CHANNEL_ID, user_id)
        if chat_member.status in ["member", "administrator", "creator"]:
            await delete_previous_messages(user_id, state)

            trial_days = 3
            access_end_date = datetime.now(pytz.UTC) + timedelta(days=trial_days)

            await grant_access_and_create_config(db_connection, user_id, trial_days)
            await update_user_access(
                db_connection, user_id, access_end_date.isoformat(), has_used_trial=1
            )

            await bot.send_sticker(
                chat_id=user_id,
                sticker=FSInputFile("assets/accepted.tgs"),
            )
            await bot.send_message(
                chat_id=user_id,
                text=(enter_caption + "\n\n" + OnboardingMessages.TRIAL_STARTED),
                parse_mode="HTML",
            )
            await main_menu(user_id=user_id, state=state, db_connection=db_connection)

        else:
            new_caption = OnboardingMessages.SUBSCRIBE_PROMPT

            channel_link_markup = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text=OnboardingMessages.SUBSCRIBE_BUTTON,
                            url=PUBLIC_CHANNEL_URL,
                        )
                    ],
                    [
                        types.InlineKeyboardButton(
                            text=OnboardingMessages.CHECK_SUBSCRIPTION_BUTTON,
                            callback_data="check_subscription",
                        )
                    ],
                    [
                        types.InlineKeyboardButton(
                            text=OnboardingMessages.BACK_BUTTON,
                            callback_data="main_menu",
                        )
                    ],
                ]
            )

            await send_sticker_and_message_with_cleanup(
                user_id=user_id,
                sticker_path="assets/matrix.tgs",
                message_text=new_caption,
                state=state,
                markup=channel_link_markup,
            )

    except Exception as e:
        logger.error(
            f"Error checking channel subscription for user {user_id}: {e}",
            exc_info=True,
        )
        await call.message.answer(OnboardingMessages.SUBSCRIPTION_CHECK_ERROR)


@user_onboarding_router.callback_query(lambda call: call.data == "check_subscription")
async def check_subscription_callback(call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection) -> None:
    user_id = call.from_user.id
    try:
        chat_member = await bot.get_chat_member(TRIAL_CHANNEL_ID, user_id)
        if chat_member.status in ["member", "administrator", "creator"]:
            await get_trial_callback(
                call, state, db_connection
            )  # Re-run the get_trial_callback to proceed with granting access
        else:
            # Get the current caption of the message
            current_caption = (
                call.message.caption if call.message.caption else call.message.text
            )

            # Define the feedback message
            feedback_text = re.sub(r"<[^>]+>", "", OnboardingMessages.NOT_SUBSCRIBED)

            # Check if feedback_text is already present in the current caption
            if feedback_text not in current_caption:
                new_caption_with_feedback = f"{OnboardingMessages.SUBSCRIBE_PROMPT}\n\n{OnboardingMessages.NOT_SUBSCRIBED}"

                # Edit the message with the updated caption
                try:
                    await call.message.edit_text(
                        text=new_caption_with_feedback,
                        parse_mode="HTML",
                        reply_markup=call.message.reply_markup,  # Preserve existing buttons
                    )
                except TelegramAPIError:
                    # Fallback if editing caption fails (e.g., message is not a photo/animation)
                    await call.message.answer(
                        feedback_text
                    )  # Send as a new message if cannot edit

    except Exception as e:
        logger.error(
            f"Error in check_subscription_callback for user {user_id}: {e}",
            exc_info=True,
        )
        await call.message.answer(OnboardingMessages.SUBSCRIPTION_CHECK_ERROR)


@user_onboarding_router.callback_query(lambda call: call.data in ("az_faq", "gb_faq"))
async def instructions_callback(call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection) -> None:
    """Обработчик для предоставления инструкций по протоколам VPN"""
    user = await get_user_by_id(db_connection, call.from_user.id)

    if user and user[2] == "accepted":
        markup = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=OnboardingMessages.VLESS_INSTRUCTIONS_BUTTON,
                        web_app=types.WebAppInfo(
                            url="https://teletype.in/@utyanews/utya_vless"
                        ),
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text=OnboardingMessages.OPENVPN_INSTRUCTIONS_BUTTON,
                        web_app=types.WebAppInfo(
                            url="https://teletype.in/@utyanews/utya_ovpn"
                        ),
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text=OnboardingMessages.WG_AMWG_INSTRUCTIONS_BUTTON,
                        web_app=types.WebAppInfo(
                            url="https://teletype.in/@utyanews/utya_wg"
                        ),
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text=OnboardingMessages.BACK_BUTTON,
                        callback_data=f"choose_proto_{call.data[:2]}",
                    )
                ],
            ]
        )
        await send_sticker_and_message_with_cleanup(
            user_id=call.from_user.id,
            sticker_path="assets/instructions.tgs",
            message_text=OnboardingMessages.INSTRUCTIONS_CAPTION,
            state=state,
            markup=markup,
            message_type="menu",
        )

    else:
        await non_authorized(call.from_user.id, call.message.message_id)
