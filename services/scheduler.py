import aiosqlite
from pytils import numeral
from aiogram import Bot, types
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import FSInputFile
from datetime import datetime, timezone, timedelta
from babel.dates import format_datetime
import pytz
import logging
import os

from config.settings import ADMIN_ID, TIMEZONE
from services.messages_manage import delete_previous_messages
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services import vpn_manager
from config.messages import SchedulerMessages, OnboardingMessages
from core.bot import storage

logger = logging.getLogger(__name__)


async def safe_send_message(
    bot: Bot,
    db: aiosqlite.Connection,
    user_id: int,
    message: str,
    parse_mode: str = "HTML",
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> int | None:
    """
    Safely sends a message to a user, deleting the previous notification.

    This function retrieves the ID of the last notification message, deletes it,
    sends the new message, and updates the database with the new message ID.

    Args:
        bot: The Bot instance.
        db: The database connection.
        user_id: The ID of the user to send the message to.
        message: The message text to send.
        parse_mode: The parse mode for the message.
        reply_markup: The inline keyboard markup for the message.

    Returns:
        The ID of the sent message, or None if sending failed.
    """
    try:
        async with db.execute("SELECT last_notification_id FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            last_message_id = row[0] if row else None

        if last_message_id:
            try:
                await bot.delete_message(chat_id=user_id, message_id=last_message_id)
            except TelegramAPIError:
                logger.warning(f"Could not delete message {last_message_id} for user {user_id}")

        sent_message = await bot.send_message(user_id, message, parse_mode=parse_mode, reply_markup=reply_markup)

        await db.execute("UPDATE users SET last_notification_id = ? WHERE id = ?", (sent_message.message_id, user_id))
        await db.commit()

        return sent_message.message_id

    except TelegramForbiddenError:
        logger.warning(f"User {user_id} has blocked the bot.")
        return None
    except TelegramAPIError:
        logger.error(f"Telegram API error while sending message to user {user_id}:", exc_info=True)
        return None


async def safe_send_sticker(bot: Bot, user_id: int, sticker: types.FSInputFile) -> int | None:
    """
    Safely sends a sticker to a user.

    Args:
        bot: The Bot instance.
        user_id: The ID of the user to send the sticker to.
        sticker: The sticker to send.

    Returns:
        The ID of the sent sticker message, or None if sending failed.
    """
    try:
        sent_sticker = await bot.send_sticker(user_id, sticker)
        return sent_sticker.message_id
    except TelegramForbiddenError:
        logger.warning(f"User {user_id} has blocked the bot.")
        return None
    except TelegramAPIError:
        logger.error(f"Telegram API error while sending sticker to user {user_id}:", exc_info=True)
        return None


async def notify_pay_days(bot: Bot, db: aiosqlite.Connection) -> None:
    """Notifies users about their upcoming subscription expiration (days)."""
    try:
        current_date = datetime.now(timezone.utc)
        days_thresholds = [3, 1]

        for days in days_thresholds:
            notification_date = current_date + timedelta(days=days)
            async with db.execute(
                "SELECT id, username, access_end_date FROM users WHERE status = 'accepted' AND date(access_end_date) = date(?)",
                (notification_date.isoformat(),),
            ) as cursor:
                users = await cursor.fetchall()

            for user in users:
                user_id, _, access_end_date_str = user
                access_end_date = datetime.fromisoformat(access_end_date_str)
                end_date_formatted = format_datetime(
                    access_end_date.astimezone(pytz.timezone(TIMEZONE)),
                    "d MMMM yyyy 'в' HH:mm",
                    locale="ru",
                )

                message = SchedulerMessages.PAYMENT_REMINDER_DAYS.format(
                    days_text=numeral.get_plural(days, "день, дня, дней"),
                    end_date_formatted=end_date_formatted,
                )
                user_markup = types.InlineKeyboardMarkup(
                    inline_keyboard=[[types.InlineKeyboardButton(text=OnboardingMessages.BUY_SUBSCRIPTION_BUTTON, callback_data="buy_subscription")]]
                )
                previous_message = await safe_send_message(bot, db, user_id, message, reply_markup=user_markup)
                if previous_message:
                    user_state = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id))
                    await user_state.update_data(previous_message_id=previous_message)
    except (aiosqlite.Error, TelegramAPIError):
        logger.error("Error notifying users about upcoming expiration (days):", exc_info=True)


async def notify_pay_hour(bot: Bot, db: aiosqlite.Connection) -> None:
    """Notifies users about their upcoming subscription expiration (hours)."""
    try:
        current_date = datetime.now(timezone.utc)
        hours_thresholds = [12, 1]

        for hours in hours_thresholds:
            notification_date = current_date + timedelta(hours=hours)
            async with db.execute(
                "SELECT id, username, access_end_date FROM users WHERE status = 'accepted' AND datetime(access_end_date) <= datetime(?, '+1 hour') AND datetime(access_end_date) > datetime(?)",
                (notification_date.isoformat(), notification_date.isoformat()),
            ) as cursor:
                users = await cursor.fetchall()

            for user in users:
                user_id, _, access_end_date_str = user
                access_end_date = datetime.fromisoformat(access_end_date_str)
                end_date_formatted = format_datetime(
                    access_end_date.astimezone(pytz.timezone(TIMEZONE)),
                    "d MMMM yyyy 'в' HH:mm",
                    locale="ru",
                )

                message = SchedulerMessages.PAYMENT_REMINDER_HOURS.format(
                    hours_text=numeral.get_plural(hours, "час, часа, часов"),
                    end_date_formatted=end_date_formatted,
                )
                user_markup = types.InlineKeyboardMarkup(
                    inline_keyboard=[[types.InlineKeyboardButton(text=OnboardingMessages.BUY_SUBSCRIPTION_BUTTON, callback_data="buy_subscription")]]
                )
                previous_message = await safe_send_message(bot, db, user_id, message, reply_markup=user_markup)
                if previous_message:
                    user_state = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id))
                    await user_state.update_data(previous_message_id=previous_message)
    except (aiosqlite.Error, TelegramAPIError):
        logger.error("Error notifying users about upcoming expiration (hours):", exc_info=True)


async def make_daily_backup(bot: Bot, db: aiosqlite.Connection) -> None:
    """Creates a daily backup of the database and sends it to the admin."""
    backup_path = f"backup_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')}.db"
    try:
        async with aiosqlite.connect(backup_path) as backup_db:
            await db.backup(backup_db)
        await bot.send_document(
            ADMIN_ID,
            FSInputFile(backup_path),
            caption=SchedulerMessages.BACKUP_CAPTION.format(date=datetime.now(timezone.utc).isoformat()),
        )
        os.remove(backup_path)
    except (IOError, OSError, TelegramAPIError, aiosqlite.Error):
        logger.error("Error creating database backup:", exc_info=True)


async def check_users_if_expired(bot: Bot, db: aiosqlite.Connection) -> None:
    """Checks for expired users, updates their status, and notifies them."""
    try:
        await db.execute("BEGIN")
        current_date = datetime.now(timezone.utc).isoformat()

        async with db.execute(
            "SELECT id, username FROM users WHERE access_end_date IS NOT NULL AND status = 'accepted' AND access_end_date < ?",
            (current_date,),
        ) as cursor:
            expired_users = await cursor.fetchall()

        for user in expired_users:
            user_id, username = user

            await db.execute(
                "UPDATE users SET status = 'expired', access_granted_date = NULL, access_duration = NULL WHERE id = ?",
                (user_id,),
            )
            await vpn_manager.delete_user(user_id)

            message = SchedulerMessages.SUBSCRIPTION_EXPIRED.format(username=username)
            sticker_message_id = await safe_send_sticker(bot, user_id, FSInputFile("assets/expired.tgs"))
            user_markup = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text=OnboardingMessages.BUY_SUBSCRIPTION_BUTTON, callback_data="buy_subscription")]]
            )
            button_message_id = await safe_send_message(bot, db, user_id, message, reply_markup=user_markup)

            user_state = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id))
            await delete_previous_messages(user_id, user_state)

            if sticker_message_id and button_message_id:
                await user_state.update_data(
                    previous_sticker_id=sticker_message_id, previous_message_id=button_message_id
                )

            markup = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text=SchedulerMessages.APPROVE_REQUEST_BUTTON, callback_data=f"accept_request_{user_id}")]
                ]
            )
            await bot.send_message(
                ADMIN_ID,
                SchedulerMessages.USER_EXPIRED_ADMIN_NOTIFICATION.format(username=username, user_id=user_id),
                reply_markup=markup,
            )
        await db.commit()
    except aiosqlite.Error:
        await db.rollback()
        logger.error("Database error while updating user statuses:", exc_info=True)
    except TelegramAPIError:
        await db.rollback()
        logger.error("Telegram API error while updating user statuses:", exc_info=True)
    except Exception as e:
        await db.rollback()
        logger.error(f"An unexpected error occurred while updating user statuses: {e}", exc_info=True)


async def start_scheduler(bot: Bot, db_connection: aiosqlite.Connection) -> None:
    """Starts the scheduler for periodic bot tasks."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    scheduler.add_job(
        notify_pay_days,
        trigger="cron",
        hour=16,
        minute=0,
        args=[bot, db_connection],
        id="notify_pay_days_job",
        replace_existing=True,
    )

    scheduler.add_job(
        notify_pay_hour,
        trigger="cron",
        hour="*",
        args=[bot, db_connection],
        id="notify_pay_hour_job",
        replace_existing=True,
    )

    scheduler.add_job(
        check_users_if_expired,
        trigger="interval",
        minutes=10,
        args=[bot, db_connection],
        id="check_users_if_expired_job",
        replace_existing=True,
    )

    scheduler.add_job(
        make_daily_backup,
        trigger="cron",
        hour=22,
        minute=0,
        args=[bot, db_connection],
        id="make_daily_backup_job",
        replace_existing=True,
    )

    scheduler.start()
