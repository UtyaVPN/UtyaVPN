import random
import logging
from datetime import datetime

import aiosqlite
import pytz
from aiogram import types
from aiogram.fsm.context import FSMContext
from babel.dates import format_datetime
from pytils import numeral

from config.messages import ServiceMessages
from config.settings import SUPPORT_ID
from services.db_operations import get_user_by_id
from services.messages_manage import (
    non_authorized,
    send_sticker_and_message_with_cleanup,
)

logger = logging.getLogger(__name__)

message_text_vpn_variants = ServiceMessages.VPN_VARIANTS_INFO
message_text_protos_info = ServiceMessages.PROTOS_INFO


async def get_protos_menu_markup(
    user_id: int, proto: str, db_connection: aiosqlite.Connection
) -> types.InlineKeyboardMarkup | None:
    """
    Generates the inline keyboard markup for the VPN protocols menu.

    This function constructs a dynamic keyboard based on the user's status and
    the selected protocol type ('az' for AntiZapret or 'gl' for Global).

    Args:
        user_id: The ID of the user requesting the menu.
        proto: The protocol variant, typically 'az' or 'gl'.
        db_connection: An active database connection.

    Returns:
        An InlineKeyboardMarkup object, or None if the user is not authorized.
    """
    user = await get_user_by_id(db_connection, user_id)
    if not (user and user[2] == "accepted"):
        return None

    buttons = [
        [types.InlineKeyboardButton(text=ServiceMessages.VLESS_BUTTON, callback_data=f"{proto}_vless")],
        [
            types.InlineKeyboardButton(text=ServiceMessages.AMNEZIAWG_BUTTON, callback_data=f"{proto}_amneziawg"),
            types.InlineKeyboardButton(text=ServiceMessages.WIREGUARD_BUTTON, callback_data=f"{proto}_wireguard"),
        ],
        [types.InlineKeyboardButton(text=ServiceMessages.OPENVPN_BUTTON, callback_data=f"{proto}_openvpn")],
        [types.InlineKeyboardButton(text=ServiceMessages.ABOUT_VPN_PROTOCOLS_BUTTON, callback_data=f"{proto}_about")],
    ]

    if proto == "az":
        buttons.insert(0, [types.InlineKeyboardButton(text=ServiceMessages.NOTE_BUTTON, web_app=types.WebAppInfo(url="https://teletype.in/@utyanews/utya_warning"))])

    buttons.extend([
        [types.InlineKeyboardButton(text=ServiceMessages.INSTRUCTIONS_BUTTON, callback_data=f"{proto}_faq")],
        [types.InlineKeyboardButton(text=ServiceMessages.BACK_BUTTON, callback_data="vpn_variants")],
    ])

    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


async def main_menu(
    call: types.CallbackQuery | None = None,
    user_id: int | None = None,
    state: FSMContext | None = None,
    db_connection: aiosqlite.Connection | None = None,
) -> None:
    """
    Displays the main menu to the user.

    This function handles the presentation of the main menu, which includes
    options to connect to VPN, manage subscriptions, and access settings.
    It checks for user authorization and displays their subscription status.

    Args:
        call: The callback query that triggered this menu.
        user_id: The user's ID.
        state: The FSM context for the user.
        db_connection: An active database connection.
    """
    user_id = user_id or call.from_user.id

    user = await get_user_by_id(db_connection, user_id)
    if not (user and user[2] == "accepted"):
        await non_authorized(user_id, call.message.message_id if call else None)
        return

    access_end_date = datetime.fromisoformat(user[5])
    current_date = datetime.now(pytz.utc)
    remaining_time = access_end_date - current_date
    remaining_days = remaining_time.days
    remaining_hours = remaining_time.total_seconds() // 3600

    end_date_formatted = format_datetime(
        access_end_date.astimezone(pytz.timezone("Europe/Moscow")),
        "d MMMM yyyy 'в' HH:mm",
        locale="ru",
    )

    time_text = (
        f"{numeral.get_plural(int(remaining_hours), 'час, часа, часов')}"
        if remaining_days < 3
        else f"{numeral.get_plural(remaining_days, 'день, дня, дней')}"
    )

    menu = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=ServiceMessages.CONNECT_TO_VPN_BUTTON, callback_data="vpn_variants")],
            [types.InlineKeyboardButton(text=ServiceMessages.RENEW_SUBSCRIPTION_BUTTON, callback_data="buy_subscription")],
            [types.InlineKeyboardButton(text=ServiceMessages.ACTIVATE_PROMO_BUTTON, callback_data="activate_promo")],
            [types.InlineKeyboardButton(text=ServiceMessages.SETTINGS_BUTTON, callback_data="settings")],
            [types.InlineKeyboardButton(text=ServiceMessages.SUPPORT_BUTTON, url=f"tg://user?id={SUPPORT_ID}")],
        ]
    )

    caption_text = f"""
{ServiceMessages.WELCOME_MESSAGE}

{ServiceMessages.REMAINING_TIME.format(time_text=time_text, end_date_formatted=end_date_formatted)}

{ServiceMessages.QUOTE.format(quote=random.choice(ServiceMessages.QUOTES))}
"""

    await send_sticker_and_message_with_cleanup(
        user_id=user_id,
        sticker_path="assets/matrix.tgs",
        message_text=caption_text,
        state=state,
        markup=menu,
        message_type="menu",
    )
