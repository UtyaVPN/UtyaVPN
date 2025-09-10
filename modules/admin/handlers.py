from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.filters.command import Command
from aiogram.exceptions import TelegramAPIError
import aiosqlite

from datetime import datetime, timedelta
import pytz
import logging

from core.bot import bot
from config.settings import ADMIN_ID
from services.db_operations import (
    delete_user,
    get_users_list,
    get_accepted_users,
    get_user_by_id,
    update_user_access,
    add_promo_code,
    delete_promo_code,
    get_all_promo_codes,
    grant_access_and_create_config,
    get_pending_requests,
)
from services.messages_manage import (
    broadcast_message,
    send_sticker_and_message_with_cleanup,
)
from services.forms import Form
from modules.admin.services import get_day_word, update_user_configs
from modules.admin.filters import IsAdmin
from modules.common.services import main_menu
from modules.user_onboarding.services import enter_caption
from config.messages import AdminMessages

logger = logging.getLogger(__name__)

admin_router = Router()


@admin_router.message(Command("admin"), IsAdmin())
async def admin_handler(message: types.Message) -> None:
    """Handles the /admin command."""
    await admin_menu(message)


async def admin_menu(message: types.Message) -> None:
    """
    Displays the main administrative menu.

    Args:
        message: The message object that triggered the menu.
    """
    buttons = [
        types.InlineKeyboardButton(text=AdminMessages.CHECK_REQUESTS_BUTTON, callback_data="check_requests"),
        types.InlineKeyboardButton(text=AdminMessages.DELETE_USER_BUTTON, callback_data="delete_user"),
        types.InlineKeyboardButton(text=AdminMessages.BROADCAST_BUTTON, callback_data="broadcast"),
        types.InlineKeyboardButton(text=AdminMessages.GET_USERS_BUTTON, callback_data="get_users"),
        types.InlineKeyboardButton(text=AdminMessages.PROMO_CODES_BUTTON, callback_data="promo_codes"),
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)])
    await bot.send_message(message.from_user.id, AdminMessages.ADMIN_MENU, reply_markup=markup)


@admin_router.callback_query(lambda call: call.data == "admin_menu", IsAdmin())
async def admin_menu_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """
    Handles the callback query to display the admin menu.

    Args:
        call: The callback query from the user.
        state: The FSM context.
    """
    buttons = [
        types.InlineKeyboardButton(text=AdminMessages.CHECK_REQUESTS_BUTTON, callback_data="check_requests"),
        types.InlineKeyboardButton(text=AdminMessages.DELETE_USER_BUTTON, callback_data="delete_user"),
        types.InlineKeyboardButton(text=AdminMessages.BROADCAST_BUTTON, callback_data="broadcast"),
        types.InlineKeyboardButton(text=AdminMessages.GET_USERS_BUTTON, callback_data="get_users"),
        types.InlineKeyboardButton(text=AdminMessages.PROMO_CODES_BUTTON, callback_data="promo_codes"),
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)])
    await call.message.edit_text(AdminMessages.ADMIN_MENU, reply_markup=markup)
    await state.clear()


@admin_router.callback_query(lambda call: call.data == "check_requests", IsAdmin())
async def check_requests_callback(
    call: types.CallbackQuery, db_connection: aiosqlite.Connection
) -> None:
    """
    Checks for and displays pending user requests for access.

    Args:
        call: The callback query from the admin.
        db_connection: The database connection.
    """
    pending_requests = await get_pending_requests(db_connection)

    if pending_requests:
        for user in pending_requests:
            user_id, username, status, _, _, _, _, _ = user
            response_text = f"{AdminMessages.USER_ID.format(user_id=user_id)}\n"
            if username:
                response_text += f"{AdminMessages.USERNAME.format(username=f'@{username}')}\n"
            response_text += f"{AdminMessages.STATUS.format(status=status)}\n"

            markup = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text=AdminMessages.ACCEPT_BUTTON, callback_data=f"accept_request_{user_id}")]
                ]
            )
            await call.message.answer(response_text, parse_mode="HTML", reply_markup=markup)

        back_markup = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=AdminMessages.BACK_BUTTON, callback_data="admin_menu")]]
        )
        await call.message.answer(AdminMessages.PENDING_USERS_SHOWN, reply_markup=back_markup)
    else:
        markup = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=AdminMessages.BACK_BUTTON, callback_data="admin_menu")]]
        )
        await call.message.edit_text(AdminMessages.NO_PENDING_REQUESTS, reply_markup=markup)
    await call.answer()


@admin_router.callback_query(lambda call: call.data.startswith("accept_request_"), IsAdmin())
async def accept_request_callback(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Accepts a user's request for access, grants them a trial period, and
    creates their VPN configuration.

    Args:
        call: The callback query from the admin.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = int(call.data.split("_")[2])
    trial_days = 30  # Default trial period

    try:
        await grant_access_and_create_config(db_connection, user_id, trial_days)

        await call.message.edit_text(
            AdminMessages.REQUEST_ACCEPTED.format(user_id=user_id, trial_days=trial_days),
            parse_mode="HTML",
        )
        await send_sticker_and_message_with_cleanup(
            user_id=user_id,
            sticker_path="assets/accepted.tgs",
            message_text=f"{enter_caption}\n\n{AdminMessages.ACCESS_GRANTED_MESSAGE}",
            state=state,
        )
        await state.clear()
        await main_menu(user_id=user_id, db_connection=db_connection, state=state)
    except Exception as e:
        await call.message.edit_text(
            AdminMessages.REQUEST_ACCEPT_ERROR.format(user_id=user_id, e=e),
            parse_mode="HTML",
        )
        logger.error(f"Error accepting request for user {user_id}: {e}", exc_info=True)
    await call.answer()


@admin_router.callback_query(lambda call: call.data == "promo_codes", IsAdmin())
async def promo_codes_menu(call: types.CallbackQuery, state: FSMContext) -> None:
    """Displays the promo code management menu."""
    buttons = [
        types.InlineKeyboardButton(text=AdminMessages.ADD_PROMO_BUTTON, callback_data="add_promo"),
        types.InlineKeyboardButton(text=AdminMessages.LIST_PROMOS_BUTTON, callback_data="list_promos_menu"),
        types.InlineKeyboardButton(text=AdminMessages.DELETE_PROMO_BUTTON, callback_data="delete_promo"),
        types.InlineKeyboardButton(text=AdminMessages.BACK_BUTTON, callback_data="admin_menu"),
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)])
    await call.message.edit_text(AdminMessages.PROMO_CODES_MENU, reply_markup=markup)
    await state.clear()


@admin_router.callback_query(lambda call: call.data == "add_promo", IsAdmin())
async def add_promo_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """Handles the callback to add a new promo code."""
    await call.message.answer(AdminMessages.ADD_PROMO_PROMPT, parse_mode="HTML")
    await state.set_state(Form.waiting_for_promo_code_data)
    await call.answer()


@admin_router.message(Form.waiting_for_promo_code_data, IsAdmin())
async def process_promo_code_data(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """Processes the data for a new promo code."""
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(AdminMessages.INVALID_PROMO_FORMAT)
        return

    code, days_str, usage_count_str = parts
    try:
        days = int(days_str)
        usage_count = int(usage_count_str)
        if days <= 0 or usage_count <= 0:
            raise ValueError
    except ValueError:
        await message.answer(AdminMessages.INVALID_PROMO_VALUES)
        return

    if await add_promo_code(db_connection, code, days, usage_count):
        await message.answer(AdminMessages.PROMO_ADDED.format(code=code, days=days, usage_count=usage_count))
    else:
        await message.answer(AdminMessages.PROMO_ADD_FAILED.format(code=code))
    await state.clear()


@admin_router.callback_query(lambda call: call.data == "list_promos_menu", IsAdmin())
async def list_promos_menu_callback(
    call: types.CallbackQuery, db_connection: aiosqlite.Connection
) -> None:
    """Lists all available promo codes."""
    promo_codes = await get_all_promo_codes(db_connection)
    if promo_codes:
        response = AdminMessages.PROMO_LIST_HEADER
        for promo in promo_codes:
            response += AdminMessages.PROMO_LIST_ITEM.format(
                code=promo[0],
                days=promo[1],
                is_active="Yes" if promo[2] == 1 else "No",
                usage_count=promo[3],
            )
    else:
        response = AdminMessages.NO_PROMOS

    await call.message.answer(response, parse_mode="Markdown")
    await call.answer()


@admin_router.callback_query(lambda call: call.data == "delete_promo", IsAdmin())
async def delete_promo_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """Handles the callback to delete a promo code."""
    await call.message.answer(AdminMessages.DELETE_PROMO_PROMPT)
    await state.set_state(Form.waiting_for_promo_code_to_delete)
    await call.answer()


@admin_router.message(Form.waiting_for_promo_code_to_delete, IsAdmin())
async def process_promo_code_to_delete(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """Processes the promo code to be deleted."""
    promo_code = message.text.strip()
    if await delete_promo_code(db_connection, promo_code):
        await message.answer(AdminMessages.PROMO_DELETED.format(promo_code=promo_code))
    else:
        await message.answer(AdminMessages.PROMO_NOT_FOUND.format(promo_code=promo_code))
    await state.clear()


@admin_router.message(Command("renewall"), IsAdmin())
async def renew_configs_handler(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """Handles the command to renew configurations for all users."""
    users_data = await get_accepted_users(db_connection)
    failed_users = []
    for user in users_data:
        user_id, username, access_end_date = user
        try:
            access_end_date = datetime.fromisoformat(access_end_date).astimezone(pytz.UTC)
            remaining_time = access_end_date - datetime.now(pytz.UTC)
            days = int(remaining_time.days)

            if await update_user_configs(user_id):
                day_word = get_day_word(days)
                markup = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text=AdminMessages.HOME_MENU_BUTTON, callback_data="main_menu")]
                    ]
                )
                await send_sticker_and_message_with_cleanup(
                    user_id=user_id,
                    sticker_path="assets/warning.tgs",
                    message_text=f"{AdminMessages.CONFIG_UPDATE_ATTENTION}\n{AdminMessages.CONFIG_UPDATE_BODY}\n{AdminMessages.ACCESS_ENDS_IN.format(days=days, day_word=day_word)}\n{AdminMessages.REPLACE_CONFIG_IMPORTANT}",
                    state=state,
                    markup=markup,
                )
            else:
                failed_users.append(f"{'@' + username if username else user_id}")

        except TelegramAPIError as e:
            logger.error(f"Error updating configurations for user {user_id} ({'@' + username if username else ''}): {e}", exc_info=True)
            failed_users.append(f"{'@' + username if username else user_id}")

    if failed_users:
        await bot.send_message(ADMIN_ID, AdminMessages.RENEW_ALL_FAIL.format(failed_users="\n".join(failed_users)))
    else:
        await bot.send_message(ADMIN_ID, AdminMessages.RENEW_ALL_SUCCESS)


@admin_router.callback_query(lambda call: call.data == "delete_user", IsAdmin())
async def delete_user_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """Handles the callback to delete a user."""
    await call.message.answer(AdminMessages.DELETE_USER_PROMPT)
    await state.set_state(Form.waiting_for_user_id)
    await call.answer()


@admin_router.message(Form.waiting_for_user_id, IsAdmin())
async def process_user_id(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """Processes the user ID for deletion."""
    user_id = message.text.strip()
    if user_id.isdigit():
        if await delete_user(db_connection, int(user_id)):
            await message.answer(AdminMessages.USER_DELETED.format(user_id=user_id))
        else:
            await message.answer(AdminMessages.USER_NOT_FOUND.format(user_id=user_id))
    else:
        await message.answer(AdminMessages.INVALID_USER_ID)
    await state.clear()


@admin_router.callback_query(lambda call: call.data == "broadcast", IsAdmin())
async def broadcast_callback(call: types.CallbackQuery, state: FSMContext) -> None:
    """Handles the callback to start a broadcast."""
    await call.message.answer(AdminMessages.BROADCAST_PROMPT)
    await state.set_state(Form.waiting_for_broadcast_message)


@admin_router.message(Form.waiting_for_broadcast_message, IsAdmin())
async def process_broadcast_message(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """Processes the message for broadcasting."""
    await broadcast_message(db_connection, message)
    await message.answer(AdminMessages.BROADCAST_SENT)
    await state.clear()


@admin_router.callback_query(lambda call: call.data == "get_users", IsAdmin())
async def get_users_callback(
    call: types.CallbackQuery, db_connection: aiosqlite.Connection
) -> None:
    """Handles the callback to get a list of users."""
    file_path = await get_users_list(db_connection)
    if file_path:
        await bot.send_document(ADMIN_ID, types.FSInputFile("users_list.csv"))
    else:
        await bot.send_message(ADMIN_ID, AdminMessages.GET_USERS_ERROR)


@admin_router.message(Command("renew"), IsAdmin())
async def renew_access(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """Handles the /renew command to set or extend a user's access."""
    command_parts = message.text.split()
    if len(command_parts) != 3:
        await message.reply(AdminMessages.RENEW_USAGE)
        return

    try:
        user_id = int(command_parts[1])
        days_str = command_parts[2]
        days_to_add = int(days_str.lstrip("+"))
    except (ValueError, IndexError):
        await message.reply(AdminMessages.RENEW_USAGE)
        return

    try:
        user = await get_user_by_id(db_connection, user_id)
        if not user:
            await message.reply(AdminMessages.USER_NOT_FOUND_IN_DB.format(user_id=user_id))
            return

        current_end_date = datetime.fromisoformat(user[5]).astimezone(pytz.UTC)
        new_end_date = (
            current_end_date + timedelta(days=days_to_add)
            if days_str.startswith("+")
            else datetime.now(pytz.UTC) + timedelta(days=days_to_add)
        )
        access_duration = (new_end_date - datetime.now(pytz.UTC)).days

        if await update_user_configs(user_id):
            await update_user_access(db_connection, user_id, new_end_date.isoformat())
            markup = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text=AdminMessages.HOME_MENU_BUTTON, callback_data="main_menu")]
                ]
            )
            await send_sticker_and_message_with_cleanup(
                user_id=user_id,
                sticker_path="assets/warning.tgs",
                message_text=f"{AdminMessages.SUBSCRIPTION_UPDATED_ATTENTION}\n{AdminMessages.CONFIG_UPDATE_BODY}\n{AdminMessages.ACCESS_ENDS_IN.format(days=access_duration, day_word=get_day_word(access_duration))}\n{AdminMessages.REPLACE_CONFIG_IMPORTANT}",
                state=state,
                markup=markup,
            )
            await message.reply(
                AdminMessages.RENEW_SUCCESS.format(
                    user_id=user_id, access_duration=access_duration, day_word=get_day_word(access_duration)
                )
            )
        else:
            await message.reply(AdminMessages.RENEW_FAIL.format(user_id=user_id))

    except (ValueError, TelegramAPIError) as e:
        logger.error(f"An error occurred while processing the command for user {message.from_user.id}: {e}", exc_info=True)
        await message.reply(AdminMessages.COMMAND_ERROR)
    except Exception as e:
        logger.error(f"An unexpected error occurred while processing the command for user {message.from_user.id}: {e}", exc_info=True)


@admin_router.message(Command("update"), IsAdmin())
async def update_access(
    message: types.Message, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """Handles the /update command to extend a user's access."""
    command_parts = message.text.split()
    if len(command_parts) != 3:
        await message.reply(AdminMessages.UPDATE_USAGE)
        return

    try:
        user_id = int(command_parts[1])
        days_to_add = int(command_parts[2])
    except (ValueError, IndexError):
        await message.reply(AdminMessages.UPDATE_USAGE)
        return

    try:
        user = await get_user_by_id(db_connection, user_id)
        if not user:
            await message.reply(AdminMessages.USER_NOT_FOUND_IN_DB.format(user_id=user_id))
            return

        current_end_date = datetime.fromisoformat(user[5]).astimezone(pytz.UTC)
        new_end_date = current_end_date + timedelta(days=days_to_add)
        access_duration = (new_end_date - datetime.now(pytz.UTC)).days

        await update_user_access(db_connection, user_id, new_end_date.isoformat())
        markup = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text=AdminMessages.HOME_MENU_BUTTON, callback_data="main_menu")]
            ]
        )
        await send_sticker_and_message_with_cleanup(
            user_id=user_id,
            sticker_path="assets/warning.tgs",
            message_text=f"{AdminMessages.SUBSCRIPTION_EXTENDED_ATTENTION}\nAccess to <b>UtyaVPN</b> ends in <b>{access_duration} {get_day_word(access_duration)}</b>.\n\n",
            state=state,
            markup=markup,
        )
        await message.reply(
            AdminMessages.UPDATE_SUCCESS.format(
                user_id=user_id, access_duration=access_duration, day_word=get_day_word(access_duration)
            )
        )

    except (ValueError, TelegramAPIError) as e:
        logger.error(f"An error occurred while processing the command for user {message.from_user.id}: {e}", exc_info=True)
        await message.reply(AdminMessages.COMMAND_ERROR)
    except Exception as e:
        logger.error(f"An unexpected error occurred while processing the command for user {message.from_user.id}: {e}", exc_info=True)


@admin_router.message(Command("refund"), IsAdmin())
async def refund_stars_handler(message: types.Message) -> None:
    """Handles the /refund command to refund a star payment."""
    command_parts = message.text.split()
    if len(command_parts) != 3:
        await message.reply(AdminMessages.REFUND_USAGE)
        return

    try:
        user_id = int(command_parts[1])
        payment_charge_id = command_parts[2]
    except (ValueError, IndexError):
        await message.reply(AdminMessages.REFUND_USAGE)
        return

    try:
        await bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=payment_charge_id)
        await message.reply(AdminMessages.REFUND_SUCCESS.format(user_id=user_id, payment_charge_id=payment_charge_id))
        logger.info(f"Refund request sent for user {user_id} with payment ID {payment_charge_id}")
    except TelegramAPIError as e:
        await message.reply(AdminMessages.REFUND_FAIL.format(user_id=user_id, e=e))
        logger.error(f"Error refunding stars for user {user_id} with payment ID {payment_charge_id}: {e}", exc_info=True)
    except Exception as e:
        await message.reply(AdminMessages.UNEXPECTED_REFUND_ERROR.format(user_id=user_id, e=e))
        logger.error(f"Unexpected error processing /refund for user {user_id}: {e}", exc_info=True)
