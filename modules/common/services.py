import random
from aiogram import types
from aiogram.fsm.context import FSMContext
from services.db_operations import get_user_by_id
from core.bot import bot
from aiogram.exceptions import TelegramAPIError
from config.settings import SUPPORT_ID
from pytils import numeral
from babel.dates import format_datetime
import pytz
from datetime import datetime
from services.messages_manage import non_authorized, send_sticker_and_message_with_cleanup
from config.messages import ServiceMessages
import logging
import aiosqlite

logger = logging.getLogger(__name__)

message_text_vpn_variants = ServiceMessages.VPN_VARIANTS_INFO

message_text_protos_info = ServiceMessages.PROTOS_INFO


async def get_protos_menu_markup(
    user_id: int, proto: str, db_connection: aiosqlite.Connection
) -> types.InlineKeyboardMarkup:
    # This function will generate the markup for protos_menu
    # It will be called from handlers and potentially other services
    user = await get_user_by_id(db_connection, user_id)
    if not (user and user[2] == "accepted"):
        return None

    inline_keyboard = [
        [
            types.InlineKeyboardButton(
                text=ServiceMessages.VLESS_BUTTON,
                callback_data=f"{proto}_vless",
            ),
        ],
        [
            types.InlineKeyboardButton(
                text=ServiceMessages.AMNEZIAWG_BUTTON,
                callback_data=f"{proto}_amneziawg",
            ),
            types.InlineKeyboardButton(
                text=ServiceMessages.WIREGUARD_BUTTON,
                callback_data=f"{proto}_wireguard",
            ),
        ],
        [
            types.InlineKeyboardButton(
                text=ServiceMessages.OPENVPN_BUTTON,
                callback_data=f"{proto}_openvpn",
            )
        ],
        [
            types.InlineKeyboardButton(
                text=ServiceMessages.ABOUT_VPN_PROTOCOLS_BUTTON,
                callback_data=f"{proto}_about",
            )
        ],
    ]
    if (proto) == "az":
        inline_keyboard.insert(
            0,
            [
                types.InlineKeyboardButton(
                    text=ServiceMessages.NOTE_BUTTON,
                    web_app=types.WebAppInfo(
                        url="https://teletype.in/@utyanews/utya_warning"
                    ),
                )
            ],
        )
    inline_keyboard.append(
        [
            types.InlineKeyboardButton(
                text=ServiceMessages.INSTRUCTIONS_BUTTON,
                callback_data=f"{proto}_faq",
            )
        ]
    )
    inline_keyboard.append(
        [
            types.InlineKeyboardButton(
                text=ServiceMessages.BACK_BUTTON, callback_data="vpn_variants"
            )
        ]
    )

    return types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def main_menu(call: types.CallbackQuery = None, user_id: int = None, state: FSMContext = None, db_connection: aiosqlite.Connection = None):
    """Обработчик для главного меню VPN."""

    user_id = user_id or call.from_user.id

    user = await get_user_by_id(db_connection, user_id)
    if not (user and user[2] == "accepted"):
        await non_authorized(user_id, call.message.message_id if call else None)
        return

    access_end_date = user[5]

    access_end_date = datetime.fromisoformat(access_end_date)
    current_date = datetime.now(pytz.utc)

    remaining_time = access_end_date - current_date
    remaining_days = remaining_time.days
    remaining_hours = remaining_time.total_seconds() // 3600

    end_date_formatted = format_datetime(
        access_end_date.replace(tzinfo=pytz.utc).astimezone(
            pytz.timezone("Europe/Moscow")
        ),
        "d MMMM yyyy 'в' HH:mm",
        locale="ru",
    )

    if remaining_days < 3:
        time_text = f"{numeral.get_plural(int(remaining_hours), 'час, часа, часов')}"
    else:
        time_text = f"{numeral.get_plural(remaining_days, 'день, дня, дней')}"

    menu = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=ServiceMessages.CONNECT_TO_VPN_BUTTON,
                    callback_data="vpn_variants",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=ServiceMessages.RENEW_SUBSCRIPTION_BUTTON,
                    callback_data="buy_subscription",  # New button
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=ServiceMessages.ACTIVATE_PROMO_BUTTON,
                    callback_data="activate_promo",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=ServiceMessages.SETTINGS_BUTTON, callback_data="settings"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=ServiceMessages.SUPPORT_BUTTON,
                    url=f"tg://user?id={SUPPORT_ID}",
                ),
            ],
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
