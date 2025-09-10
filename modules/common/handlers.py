from aiogram import types, Router, F
from modules.user_onboarding.services import enter_caption, process_start_command
from modules.admin.services import get_day_word
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramAPIError
from datetime import datetime, timedelta
import pytz
import re
import aiosqlite

from core.bot import bot
from services.db_operations import (
    get_user_by_id,
    get_promo_code,
    update_user_access,
    update_promo_code_usage,
    record_promo_code_usage,
    has_user_used_promo_code,
)
from services.messages_manage import (
    non_authorized,
    send_sticker_and_message_with_cleanup,
    delete_previous_messages,
)
from services.forms import Form
from modules.common.services import (
    message_text_vpn_variants,
    message_text_protos_info,
    get_protos_menu_markup,
    main_menu,
)
from modules.user_onboarding.entry import start_handler
from config.settings import ADMIN_ID, PUBLIC_CHANNEL_URL
from services.vpn_manager import create_user
from config.messages import CommonMessages
import logging

logger = logging.getLogger(__name__)

common_router = Router()

SUBSCRIPTION_OPTIONS = {
    "1_month": {"days": 30, "stars": 100},
    "3_months": {"days": 90, "stars": 250},
    "6_months": {"days": 180, "stars": 450},
    "12_months": {"days": 365, "stars": 800},
}


@common_router.callback_query(lambda call: call.data == "main_menu")
async def main_menu_handler(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Handles the callback query for the main menu.

    This function clears any previous state, deletes old messages, and displays
    the main menu to the user. If the user is not authorized, it initiates the
    onboarding process.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    if state:
        await delete_previous_messages(user_id, state)
        data = await state.get_data()
        previous_invoice_message_id = data.get("invoice_message_id")
        if previous_invoice_message_id:
            try:
                await bot.delete_message(chat_id=user_id, message_id=previous_invoice_message_id)
            except TelegramAPIError as e:
                logger.warning(f"Could not delete previous invoice message {previous_invoice_message_id}: {e}")
        await state.clear()

    if user and user[2] == "accepted":
        await main_menu(call=call, user_id=user_id, state=state, db_connection=db_connection)
    else:
        await start_handler(user_id=user_id, state=state, db_connection=db_connection)


@common_router.callback_query(lambda call: call.data == "settings")
async def settings_menu(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Displays the settings menu.

    This function provides options for users to manage their settings, such as
    adding a site to the AntiZapret list.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    await delete_previous_messages(call.from_user.id, state)
    await state.clear()  # Clear state to cancel any ongoing forms

    user = await get_user_by_id(db_connection, call.from_user.id)
    if not (user and user[2] == "accepted"):
        await non_authorized(call.from_user.id, call.message.message_id)
        return

    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=CommonMessages.ADD_SITE_BUTTON, callback_data="add_site")],
            [types.InlineKeyboardButton(text=CommonMessages.BACK_BUTTON_TEXT, callback_data="main_menu")],
        ]
    )

    await send_sticker_and_message_with_cleanup(
        user_id=call.from_user.id,
        sticker_path="assets/settings.tgs",
        message_text=CommonMessages.SETTINGS_CAPTION,
        state=state,
        markup=markup,
        message_type="menu",
    )


@common_router.callback_query(lambda call: call.data == "add_site")
async def ask_for_site_names_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """
    Prompts the user to enter the site(s) they wish to add to AntiZapret.

    Args:
        call: The callback query from the user.
        state: The FSM context.
    """
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=CommonMessages.BACK_BUTTON_TEXT, callback_data="settings")]
        ]
    )

    await send_sticker_and_message_with_cleanup(
        user_id=call.from_user.id,
        sticker_path="assets/settings.tgs",
        message_text=CommonMessages.ADD_SITE_PROMPT,
        state=state,
        markup=markup,
    )
    await state.set_state(Form.waiting_for_site_names)


@common_router.message(Form.waiting_for_site_names)
async def handle_site_names(message: types.Message, state: FSMContext) -> None:
    """
    Processes the site names entered by the user.

    This function validates the entered domain names, separates the valid from
    the invalid, and asks for confirmation before sending the request to the admin.

    Args:
        message: The message containing the site names.
        state: The FSM context.
    """
    data = await state.get_data()
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    bot_message_id = data.get("previous_message_id")
    last_text = data.get("last_text")
    sites = message.text.strip()
    site_list = [site.strip() for site in sites.splitlines() if site.strip()]
    site_pattern = re.compile(
        r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6}$"
    )

    formatted_sites = [site for site in site_list if site_pattern.match(site)]
    invalid_sites = [site for site in site_list if not site_pattern.match(site)]

    if invalid_sites:
        markup = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text=CommonMessages.BACK_BUTTON_TEXT, callback_data="settings")]
            ]
        )
        try:
            new_text = CommonMessages.INVALID_SITE_FORMAT.format(
                invalid_sites_list="\n".join([f"<code>{site}</code>" for site in invalid_sites])
            )
            if new_text != last_text:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=bot_message_id,
                    text=new_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            await state.update_data(last_text=new_text)
        except TelegramAPIError:
            await bot.send_message(
                chat_id=message.chat.id,
                text=CommonMessages.INVALID_SITE_FORMAT.format(
                    invalid_sites_list="\n".join([f"<code>{site}</code>" for site in invalid_sites])
                ),
                parse_mode="HTML",
                reply_markup=markup,
            )
        return

    await state.update_data(formatted_sites=formatted_sites)

    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text=CommonMessages.YES_BUTTON, callback_data="confirm"),
                types.InlineKeyboardButton(text=CommonMessages.CANCEL_BUTTON, callback_data="settings"),
            ]
        ]
    )
    try:
        new_text = CommonMessages.CONFIRM_SITE_ADDITION.format(
            sites_list="\n".join([f"<b>{site}</b>" for site in formatted_sites])
        )
        if last_text != new_text:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_message_id,
                text=new_text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        await state.update_data(last_text=new_text)
        await state.set_state(Form.waiting_for_site_confirmation)
    except TelegramAPIError:
        await bot.send_message(
            chat_id=message.chat.id,
            text=CommonMessages.CONFIRM_SITE_ADDITION.format(
                sites_list="\n".join([f"<b>{site}</b>" for site in formatted_sites])
            ),
            parse_mode="HTML",
            reply_markup=markup,
        )
        await state.set_state(Form.waiting_for_site_confirmation)



@common_router.message(Form.waiting_for_site_confirmation)
async def handle_unrecognized_input_in_site_confirmation(message: types.Message, state: FSMContext) -> None:
    """
    Handles any text input when the bot is waiting for site confirmation.

    This function simply deletes the user's message to avoid clutter and confusion,
    as the user is expected to interact with the inline keyboard buttons.

    Args:
        message: The user's message.
        state: The FSM context.
    """
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)


@common_router.callback_query(lambda call: call.data == "confirm")
async def confirm_action_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """
    Confirms the site addition and sends a request to the administrator.

    Args:
        call: The callback query from the user.
        state: The FSM context.
    """
    data = await state.get_data()
    formatted_sites = data.get("formatted_sites", [])

    admin_message = CommonMessages.ADMIN_REQUEST_NOTIFICATION.format(
        sites_list="\n".join(formatted_sites),
        user_id=call.from_user.id,
        username=f"@{call.from_user.username}" if call.from_user.username else f"user_id:{call.from_user.id}",
    )
    await bot.send_message(ADMIN_ID, admin_message)

    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=CommonMessages.BACK_BUTTON_TEXT, callback_data="settings")]
        ]
    )

    await send_sticker_and_message_with_cleanup(
        user_id=call.from_user.id,
        sticker_path="assets/request.tgs",
        message_text=CommonMessages.REQUEST_SENT.format(
            sites_list="\n".join([f"<b>{site}</b>" for site in formatted_sites])
        ),
        state=state,
        markup=markup,
    )
    await state.update_data(formatted_sites=None, last_text=None)
    await state.set_state(None)



@common_router.callback_query(lambda call: call.data in ("az_about", "gb_about"))
async def info_about_protos_callback(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Provides information about VPN protocols.

    This handler displays a detailed message about the available VPN protocols
    and presents the protocol selection menu again.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    user = await get_user_by_id(db_connection, call.from_user.id)
    if not (user and user[2] == "accepted"):
        await state.clear()
        await bot.delete_message(call.from_user.id, call.message.message_id)
        await start_handler(user_id=call.from_user.id, db_connection=db_connection)
        return

    try:
        info_text = message_text_protos_info
        menu_caption = CommonMessages.CHOOSE_VPN_PROTOCOL
        final_text = f"{info_text}\n\n{menu_caption}"

        markup = await get_protos_menu_markup(call.from_user.id, call.data[:2], db_connection)
        state_data = await state.get_data()
        previous_menu_id = state_data.get("previous_menu_id")
        if previous_menu_id:
            try:
                await bot.delete_message(call.from_user.id, previous_menu_id)
            except TelegramAPIError:
                logger.debug(f"Could not delete message {previous_menu_id} for user {call.from_user.id}")

        await send_sticker_and_message_with_cleanup(
            user_id=call.from_user.id,
            sticker_path="assets/vpn_protos.tgs",
            message_text=final_text,
            state=state,
            markup=markup,
            message_type="menu",
        )
    except TelegramAPIError:
        logger.error("Error processing protocol info request:", exc_info=True)



@common_router.callback_query(lambda call: call.data == "more")
async def info_about_vpn_callback(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Handles the 'More about VPN' button callback.

    This function displays additional information about the VPN service and then
    re-initiates the start command flow to show the main menu.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    try:
        await delete_previous_messages(call.from_user.id, state)
        state_data = await state.get_data()
        previous_code_id = state_data.get("previous_code_id")
        if previous_code_id:
            await bot.delete_message(call.from_user.id, previous_code_id)

        previous_sticker = await bot.send_sticker(
            chat_id=call.from_user.id, sticker=FSInputFile("assets/matrix.tgs")
        )
        message_info = await bot.send_message(
            call.from_user.id, message_text_vpn_variants, parse_mode="HTML"
        )
        await state.update_data(previous_code_id=message_info.message_id)
        await state.update_data(previous_sticker_id=previous_sticker.message_id)
        await process_start_command(
            user_id=call.from_user.id, state=state, issticker=True, db_connection=db_connection
        )
    except TelegramAPIError:
        logger.error("Error processing more info request:", exc_info=True)


@common_router.callback_query(lambda call: call.data == "activate_promo")
async def activate_promo_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """
    Handles the 'Activate Promo Code' button callback.

    This function prompts the user to enter a promotional code.

    Args:
        call: The callback query from the user.
        state: The FSM context.
    """
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=CommonMessages.BACK_BUTTON_TEXT, callback_data="main_menu")]
        ]
    )
    channel_url = PUBLIC_CHANNEL_URL
    caption_text = CommonMessages.ACTIVATE_PROMO_PROMPT.format(channel_url=channel_url)

    await send_sticker_and_message_with_cleanup(
        user_id=call.from_user.id,
        sticker_path="assets/typing.tgs",
        message_text=caption_text,
        state=state,
        markup=markup,
    )
    await state.set_state(Form.waiting_for_promo_code)
    await call.answer()


@common_router.message(Form.waiting_for_promo_code)
async def process_promo_code(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Processes the promotional code entered by the user.

    This function validates the promo code, checks if it has already been used,
    and if valid, extends the user's subscription and updates the database.

    Args:
        message: The message containing the promo code.
        state: The FSM context.
        db_connection: The database connection.
    """
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    promo_code_str = message.text.strip()
    user_id = message.from_user.id

    promo = await get_promo_code(db_connection, promo_code_str)
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=CommonMessages.BACK_BUTTON_TEXT, callback_data="main_menu")]
        ]
    )

    if promo and promo[2] == 1:  # promo[2] is is_active
        if await has_user_used_promo_code(db_connection, user_id, promo_code_str):
            await send_sticker_and_message_with_cleanup(
                user_id=user_id,
                sticker_path="assets/warning.tgs",
                message_text=CommonMessages.PROMO_ALREADY_USED,
                state=state,
                markup=markup,
            )
            return

        days_to_add = promo[1]
        current_usage_count = promo[3]

        if current_usage_count <= 0:
            await send_sticker_and_message_with_cleanup(
                user_id=user_id,
                sticker_path="assets/warning.tgs",
                message_text=CommonMessages.PROMO_UNAVAILABLE,
                state=state,
                markup=markup,
            )
            return

        user = await get_user_by_id(db_connection, user_id)
        if user:
            current_end_date = datetime.fromisoformat(user[5]).astimezone(pytz.UTC)
            new_end_date = current_end_date + timedelta(days=days_to_add)

            await update_user_access(db_connection, user_id, new_end_date.isoformat())
            await update_promo_code_usage(db_connection, promo_code_str, current_usage_count - 1)
            await record_promo_code_usage(db_connection, user_id, promo_code_str)

            success_markup = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
                ]
            )
            await send_sticker_and_message_with_cleanup(
                user_id=user_id,
                sticker_path="assets/accepted.tgs",
                message_text=CommonMessages.PROMO_ACTIVATED.format(
                    promo_code_str=promo_code_str,
                    days_to_add=days_to_add,
                    day_word=get_day_word(days_to_add),
                ),
                state=state,
                markup=success_markup,
            )
        else:
            await send_sticker_and_message_with_cleanup(
                user_id=user_id,
                sticker_path="assets/warning.tgs",
                message_text=CommonMessages.PROMO_ACTIVATION_ERROR,
                state=state,
                markup=markup,
            )
            logger.error(f"User {user_id} not found when activating promo code {promo_code_str}")
    else:
        await send_sticker_and_message_with_cleanup(
            user_id=user_id,
            sticker_path="assets/warning.tgs",
            message_text=CommonMessages.INVALID_PROMO,
            state=state,
            markup=markup,
        )
        await state.set_state(Form.waiting_for_promo_code)


@common_router.callback_query(lambda call: call.data == "buy_subscription")
async def buy_subscription_callback(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Displays the subscription purchase options.

    This handler shows a menu with different subscription durations and their
    prices.
    """
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=CommonMessages.SUBSCRIPTION_OPTION_1_MONTH,
                    callback_data="buy_1_month",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=CommonMessages.SUBSCRIPTION_OPTION_3_MONTHS,
                    callback_data="buy_3_months",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=CommonMessages.SUBSCRIPTION_OPTION_6_MONTHS,
                    callback_data="buy_6_months",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=CommonMessages.SUBSCRIPTION_OPTION_12_MONTHS,
                    callback_data="buy_12_months",
                )
            ],
            [types.InlineKeyboardButton(text=CommonMessages.BACK_BUTTON_TEXT, callback_data="main_menu")],
        ]
    )
    await send_sticker_and_message_with_cleanup(
        user_id=call.from_user.id,
        sticker_path="assets/payment.tgs",
        message_text=CommonMessages.CHOOSE_SUBSCRIPTION_DURATION,
        state=state,
        markup=markup,
        message_type="menu",
    )
    await call.answer()


async def process_buy_subscription(
    call: types.CallbackQuery, subscription_key: str, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Processes the selected subscription option and sends an invoice.

    Args:
        call: The callback query from the user.
        subscription_key: The key identifying the chosen subscription option.
        state: The FSM context.
        db_connection: The database connection.
    """
    option = SUBSCRIPTION_OPTIONS.get(subscription_key)
    if not option:
        await call.message.answer(CommonMessages.INVALID_SUBSCRIPTION_OPTION)
        await call.answer()
        return

    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)
    subscription_days = option["days"]

    if user and user[2] == "accepted":
        access_end_date = datetime.fromisoformat(user[5]).astimezone(pytz.UTC)
        current_date = datetime.now(pytz.UTC)
        remaining_time = access_end_date - current_date
        remaining_days = remaining_time.days

        if remaining_days + subscription_days > 365:
            await call.message.answer(CommonMessages.SUBSCRIPTION_EXCEEDS_YEAR)
            await call.answer()
            return

    price_stars = option["stars"]
    payload = f"subscription_{call.from_user.id}_{subscription_days}days"

    try:
        data = await state.get_data()
        previous_invoice_message_id = data.get("invoice_message_id")
        if previous_invoice_message_id:
            try:
                await bot.delete_message(chat_id=call.from_user.id, message_id=previous_invoice_message_id)
            except TelegramAPIError as e:
                logger.warning(f"Could not delete previous invoice message {previous_invoice_message_id}: {e}")

        sent_invoice = await bot.send_invoice(
            chat_id=call.from_user.id,
            title=f"UtyaVPN Subscription for {subscription_days} {get_day_word(subscription_days)}",
            description=f"You will get access to UtyaVPN for {subscription_days} {get_day_word(subscription_days)}.",
            payload=payload,
            currency="XTR",
            prices=[types.LabeledPrice(label=f"Subscription for {subscription_days} {get_day_word(subscription_days)}", amount=price_stars)],
            start_parameter="utyavpn_subscription",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            send_email_to_provider=False,
            send_phone_number_to_provider=False,
            is_flexible=False,
        )
        await state.update_data(invoice_message_id=sent_invoice.message_id)
    except TelegramAPIError as e:
        logger.error(f"Error sending invoice to user {call.from_user.id}: {e}", exc_info=True)
        await call.message.answer(CommonMessages.INVOICE_ERROR)
    await call.answer()


@common_router.callback_query(lambda call: call.data == "buy_1_month")
async def buy_1_month_callback(call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection) -> None:
    """Handles the callback for the 1-month subscription option."""
    await process_buy_subscription(call, "1_month", state, db_connection)


@common_router.callback_query(lambda call: call.data == "buy_3_months")
async def buy_3_months_callback(call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection) -> None:
    """Handles the callback for the 3-month subscription option."""
    await process_buy_subscription(call, "3_months", state, db_connection)


@common_router.callback_query(lambda call: call.data == "buy_6_months")
async def buy_6_months_callback(call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection) -> None:
    """Handles the callback for the 6-month subscription option."""
    await process_buy_subscription(call, "6_months", state, db_connection)


@common_router.callback_query(lambda call: call.data == "buy_12_months")
async def buy_12_months_callback(call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection) -> None:
    """Handles the callback for the 12-month subscription option."""
    await process_buy_subscription(call, "12_months", state, db_connection)


@common_router.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: types.PreCheckoutQuery, db_connection: aiosqlite.Connection) -> None:
    """
    Handles the pre-checkout query to confirm the transaction.

    Args:
        pre_checkout_query: The pre-checkout query object.
        db_connection: The database connection.
    """
    user_id = pre_checkout_query.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    invoice_payload = pre_checkout_query.invoice_payload
    try:
        parts = invoice_payload.split("_")
        subscription_days = int(parts[2].replace("days", ""))
    except (IndexError, ValueError):
        subscription_days = 0

    if user and user[2] == "accepted":
        access_end_date = datetime.fromisoformat(user[5]).astimezone(pytz.UTC)
        current_date = datetime.now(pytz.UTC)
        remaining_time = access_end_date - current_date
        remaining_days = remaining_time.days

        if remaining_days + subscription_days > 365:
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message=CommonMessages.SUBSCRIPTION_EXCEEDS_YEAR)
            return

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@common_router.message(F.successful_payment)
async def successful_payment_handler(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Handles a successful payment.

    This function processes the successful payment, updates the user's
    subscription period in the database, creates VPN configurations if they
    don't exist, and notifies the user and the administrator.

    Args:
        message: The message object containing payment details.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = message.from_user.id
    total_amount = message.successful_payment.total_amount
    invoice_payload = message.successful_payment.invoice_payload

    try:
        parts = invoice_payload.split("_")
        subscription_days = int(parts[2].replace("days", ""))
    except (IndexError, ValueError):
        logger.error(f"Could not parse subscription days from payload: {invoice_payload}", exc_info=True)
        subscription_days = 0

    if subscription_days <= 0:
        logger.error(f"Invalid subscription days ({subscription_days}) from payload: {invoice_payload}", exc_info=True)
        await bot.send_message(user_id, CommonMessages.PAYMENT_ERROR_INVALID_DAYS)
        return

    user = await get_user_by_id(db_connection, user_id)
    if not user:
        logger.error(f"User {user_id} not found after successful payment.", exc_info=True)
        await bot.send_message(user_id, CommonMessages.PAYMENT_ERROR_USER)
        return

    current_end_date = datetime.fromisoformat(user[5]).astimezone(pytz.UTC)
    new_end_date = current_end_date + timedelta(days=subscription_days)

    if user[2] != "accepted":
        await create_user(user_id)
        logger.info(f"User {user_id} paid {total_amount} stars and new config created for {subscription_days} days.")
    else:
        logger.info(f"User {user_id} successfully paid {total_amount} stars for {subscription_days} days.")

    await update_user_access(db_connection, user_id, new_end_date.isoformat())

    await delete_previous_messages(user_id, state)
    await bot.send_sticker(chat_id=user_id, sticker=types.FSInputFile("assets/accepted.tgs"))
    await bot.send_message(
        chat_id=user_id,
        text=f"{enter_caption}\n\n{CommonMessages.SUBSCRIPTION_SUCCESS_MESSAGE}",
        parse_mode="HTML",
    )
    await main_menu(user_id=user_id, state=state, db_connection=db_connection)

    await bot.send_message(
        ADMIN_ID,
        CommonMessages.ADMIN_PAYMENT_NOTIFICATION.format(
            username=f"@{message.from_user.username}" if message.from_user.username else f"user_id:{user_id}",
            user_id=user_id,
            total_amount=total_amount,
            subscription_days=subscription_days,
            day_word=get_day_word(subscription_days),
        ),
    )
