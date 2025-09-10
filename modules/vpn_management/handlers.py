import os
import asyncio
import aiofiles
import aiosqlite

from aiogram import types, Router
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramAPIError

from core.bot import bot
from services.db_operations import get_user_by_id
from services.messages_manage import (
    non_authorized,
    send_sticker_and_message_with_cleanup,
    delete_previous_messages,
)
from modules.common.services import message_text_vpn_variants
from modules.vpn_management.services import (
    send_vpn_config,
    get_vpn_variants_menu_markup,
    config_texts,
)
from modules.common.services import get_protos_menu_markup
from config.settings import VPN_CONFIG_PATH
from config.messages import VpnManagementMessages
import logging

logger = logging.getLogger(__name__)

vpn_management_router = Router()


@vpn_management_router.callback_query(lambda call: call.data in config_texts.keys())
async def send_configs_callback(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Handles sending VPN configurations to the user based on their request.

    This function retrieves the appropriate VPN configuration file and caption,
    sends it to the user, and then displays the protocol selection menu again.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    if not (user and user[2] == "accepted"):
        await non_authorized(call.from_user.id, call.message.message_id, state, db_connection)
        return

    file_path, caption, markup = await send_vpn_config(call, db_connection)

    if file_path:
        await delete_previous_messages(user_id, state)
        state_data = await state.get_data()
        previous_menu_id = state_data.get("previous_menu_id")
        previous_code_id = state_data.get("previous_code_id")

        if previous_menu_id:
            try:
                await bot.delete_message(user_id, previous_menu_id)
            except TelegramAPIError:
                logger.debug(f"Could not delete message {previous_menu_id} for user {user_id}")
        if previous_code_id:
            try:
                await bot.delete_message(user_id, previous_code_id)
            except TelegramAPIError:
                logger.debug(f"Could not delete message {previous_code_id} for user {user_id}")

        sticker_message = await bot.send_sticker(user_id, sticker=FSInputFile("assets/vpn_protos.tgs"))
        config_message = await bot.send_document(
            user_id,
            FSInputFile(file_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=markup,
        )

        config = config_texts[call.data]
        proto = "az" if "AZ" in config["prefix"] else "gb"
        menu_markup = await get_protos_menu_markup(user_id, proto, db_connection)
        menu_caption = VpnManagementMessages.CHOOSE_VPN_PROTOCOL
        menu_id = await bot.send_message(
            user_id,
            menu_caption,
            reply_markup=menu_markup,
            parse_mode="HTML",
        )
        await state.update_data(
            previous_sticker_id=sticker_message.message_id,
            previous_message_id=config_message.message_id,
            previous_menu_id=menu_id.message_id,
        )


@vpn_management_router.callback_query(
    lambda call: call.data in ("choose_proto_az", "choose_proto_gb")
)
async def protos_menu_handler(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Displays the VPN protocol selection menu.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = call.from_user.id
    proto = call.data[-2:]
    user = await get_user_by_id(db_connection, user_id)

    if not (user and user[2] == "accepted"):
        await non_authorized(user_id, call.message.message_id, state, db_connection)
        return

    markup = await get_protos_menu_markup(user_id, proto, db_connection)
    caption = VpnManagementMessages.CHOOSE_VPN_PROTOCOL
    await send_sticker_and_message_with_cleanup(
        user_id=user_id,
        sticker_path="assets/vpn_protos.tgs",
        message_text=caption,
        state=state,
        markup=markup,
    )


@vpn_management_router.callback_query(lambda call: call.data == "vpn_variants")
async def vpn_variants_menu_handler(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Displays the VPN variants selection menu.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    if not (user and user[2] == "accepted"):
        await non_authorized(user_id, call.message.message_id, state, db_connection)
        return

    markup = await get_vpn_variants_menu_markup()
    caption = VpnManagementMessages.CHOOSE_VPN_VARIANT
    await send_sticker_and_message_with_cleanup(
        user_id=user_id,
        sticker_path="assets/vpn_variants.tgs",
        message_text=caption,
        state=state,
        markup=markup,
    )


@vpn_management_router.callback_query(lambda call: call.data == "more_variants")
async def vpn_info_callback_handler(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Displays information about VPN variants and the selection menu.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    if not (user and user[2] == "accepted"):
        await non_authorized(user_id, call.message.message_id, state, db_connection)
        return

    markup = await get_vpn_variants_menu_markup()
    caption = VpnManagementMessages.CHOOSE_VPN_VARIANT
    info_text = message_text_vpn_variants
    final_text = f"{info_text}\n\n{caption}"

    await send_sticker_and_message_with_cleanup(
        user_id=user_id,
        sticker_path="assets/vpn_variants.tgs",
        message_text=final_text,
        state=state,
        markup=markup,
    )


@vpn_management_router.callback_query(
    lambda call: call.data in ("az_vless_text", "gb_vless_text")
)
async def send_vless_text_config(
    call: types.CallbackQuery, state: FSMContext, db_connection: aiosqlite.Connection
) -> None:
    """
    Sends the VLESS configuration as plain text to the user.

    This function retrieves the VLESS configuration file (JSON or TXT) based on
    the user's request, reads its content, and sends it as a pre-formatted
    text message. It also cleans up previous messages and updates the state.

    Args:
        call: The callback query from the user.
        state: The FSM context.
        db_connection: The database connection.
    """
    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    if not (user and user[2] == "accepted"):
        await non_authorized(user_id, call.message.message_id, state, db_connection)
        return

    config_type = call.data.split("_")[0]
    file_prefix = "AZ-XR" if config_type == "az" else "GL-XR"
    file_type = "json" if config_type == "az" else "txt"

    client_name = f"n{user_id}"
    config_dir_path = os.path.join(VPN_CONFIG_PATH, client_name)

    found_file_path = None
    if await asyncio.to_thread(os.path.exists, config_dir_path):
        files_in_dir = await asyncio.to_thread(os.listdir, config_dir_path)
        for file_name in files_in_dir:
            if file_name.startswith(file_prefix) and file_name.endswith(f".{file_type}"):
                found_file_path = os.path.join(config_dir_path, file_name)
                break

    if not found_file_path:
        await call.message.answer(VpnManagementMessages.VLESS_TEXT_CONFIG_NOT_FOUND)
        await call.answer()
        return

    async with aiofiles.open(found_file_path, "r") as f:
        config_content = await f.read()

    state_data = await state.get_data()
    previous_menu_id = state_data.get("previous_menu_id")

    if previous_menu_id:
        try:
            await bot.delete_message(user_id, previous_menu_id)
            logger.info(f"send_vless_text_config: Successfully deleted previous_menu_id: {previous_menu_id}")
        except TelegramAPIError as e:
            logger.error(f"Failed to delete message {previous_menu_id} for user {user_id}: {e}")

    previous_code_id = await bot.send_message(user_id, f"<pre><code>{config_content}</code></pre>", parse_mode="HTML")
    proto = "az" if call.data.startswith("az") else "gb"
    markup = await get_protos_menu_markup(user_id, proto, db_connection)
    caption = VpnManagementMessages.CHOOSE_VPN_PROTOCOL

    message_vless = await bot.send_message(user_id, caption, reply_markup=markup, parse_mode="HTML")
    await call.message.edit_reply_markup(reply_markup=None)
    await state.update_data(
        previous_menu_id=message_vless.message_id,
        previous_code_id=previous_code_id.message_id,
    )
    await call.answer()
