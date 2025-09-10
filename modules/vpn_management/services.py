import asyncio
import json
import logging
import os

import aiosqlite
from aiogram import types

from config.messages import VpnManagementMessages
from config.settings import VPN_CONFIG_PATH
from core.bot import bot
from services.db_operations import get_user_by_id

logger = logging.getLogger(__name__)

# Load VPN config texts from JSON file
with open("config/vpn_configs.json", "r", encoding="utf-8") as f:
    config_texts = json.load(f)


async def send_vpn_config(
    call: types.CallbackQuery, db_connection: aiosqlite.Connection
) -> tuple[str | None, str | None, types.InlineKeyboardMarkup | None]:
    """
    Sends the appropriate VPN configuration file to the user.

    This function determines the correct configuration file based on the callback
    data, retrieves it from the file system, and prepares it for sending along
    with a caption and an optional inline keyboard markup.

    Args:
        call: The callback query from the user, containing the config key.
        db_connection: The database connection.

    Returns:
        A tuple containing the file path, caption, and inline keyboard markup.
        Returns (None, None, None) if the user is not accepted or if an error occurs.
    """
    user_id = call.from_user.id
    user = await get_user_by_id(db_connection, user_id)

    if not (user and user[2] == "accepted"):
        return None, None, None

    config_key = call.data
    config = config_texts[config_key]

    if "WG" in config["prefix"] or "AM" in config["prefix"]:
        file_type = "conf"
    elif "AZ-XR" in config["prefix"]:
        file_type = "json"
    elif "GL-XR" in config["prefix"]:
        file_type = "txt"
    else:
        file_type = "ovpn"

    file_prefix = config["prefix"]

    try:
        config_dir_path = os.path.join(VPN_CONFIG_PATH, f"n{user_id}")
        files_in_dir = await asyncio.to_thread(os.listdir, config_dir_path)

        for file_name in files_in_dir:
            if file_name.startswith(file_prefix) and file_name.endswith(f".{file_type}"):
                full_file_path = os.path.join(config_dir_path, file_name)

                if not await asyncio.to_thread(os.path.exists, full_file_path):
                    logger.warning(
                        VpnManagementMessages.CONFIG_NOT_FOUND.format(
                            full_file_path=full_file_path, user_id=user_id
                        )
                    )
                    continue

                caption = config["text"]
                markup_buttons = []
                if file_type in ("json", "txt") and "AZ-XR" in file_prefix:
                    markup_buttons.append(
                        types.InlineKeyboardButton(
                            text=VpnManagementMessages.SHOW_TEXT_CONFIG_BUTTON,
                            callback_data="az_vless_text",
                        )
                    )
                elif file_type in ("json", "txt") and "GL-XR" in file_prefix:
                    markup_buttons.append(
                        types.InlineKeyboardButton(
                            text=VpnManagementMessages.SHOW_TEXT_CONFIG_BUTTON,
                            callback_data="gb_vless_text",
                        )
                    )

                markup = (
                    types.InlineKeyboardMarkup(inline_keyboard=[markup_buttons])
                    if markup_buttons
                    else None
                )
                return full_file_path, caption, markup

    except FileNotFoundError:
        logger.warning(f"Configuration directory not found for user {user_id}: {config_dir_path}")
        await bot.send_message(user_id, VpnManagementMessages.CONFIG_DIR_NOT_FOUND, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Unexpected error while searching or sending configuration for user {user_id}: {e}", exc_info=True)
        await bot.send_message(user_id, VpnManagementMessages.GET_CONFIG_ERROR)

    return None, None, None


async def get_vpn_variants_menu_markup() -> types.InlineKeyboardMarkup:
    """
    Generates the inline keyboard markup for the VPN variants menu.

    Returns:
        An InlineKeyboardMarkup object for VPN variant selection.
    """
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=VpnManagementMessages.ANTIZAPRET_BUTTON,
                    callback_data="choose_proto_az",
                ),
                types.InlineKeyboardButton(
                    text=VpnManagementMessages.GLOBAL_BUTTON,
                    callback_data="choose_proto_gb",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=VpnManagementMessages.MORE_ABOUT_VARIANTS_BUTTON,
                    callback_data="more_variants",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=VpnManagementMessages.BACK_BUTTON, callback_data="main_menu"
                )
            ],
        ]
    )
