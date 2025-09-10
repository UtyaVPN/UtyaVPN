import aiosqlite
import logging
from datetime import datetime, timedelta, timezone
import aiofiles
from services import vpn_manager

logger = logging.getLogger(__name__)


async def get_user_by_id(db: aiosqlite.Connection, user_id: int) -> tuple | None:
    """Retrieves user information by their ID."""
    async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
        return await cursor.fetchone()


async def add_user(db: aiosqlite.Connection, user_id: int, username: str) -> tuple | None:
    """
    Adds a new user to the database or updates the status of an existing user.

    If the user does not exist, a new record is created with a 'pending' status.
    If the user exists with a 'denied' or 'expired' status, their status is
    reset to 'pending'.
    """
    try:
        await db.execute("BEGIN")
        user = await get_user_by_id(db, user_id)
        current_date = datetime.now(timezone.utc).isoformat()

        if user is None:
            await db.execute(
                "INSERT INTO users (id, username, status, access_granted_date, access_duration, access_end_date, has_used_trial) VALUES (?, ?, 'pending', ?, 0, ?, 0)",
                (user_id, username, current_date, current_date),
            )
        elif user[2] in ("denied", "expired"):
            await db.execute("UPDATE users SET status = 'pending' WHERE id = ?", (user_id,))

        await db.commit()
        return await get_user_by_id(db, user_id)
    except aiosqlite.Error as e:
        await db.rollback()
        logger.error(f"Transaction failed while adding/updating user {user_id}: {e}", exc_info=True)
        return None


async def grant_access_and_create_config(db: aiosqlite.Connection, user_id: int, days: int) -> None:
    """
    Grants access to a user and creates their VPN configurations.

    This function updates the user's status to 'accepted' and sets their access
    duration and end date. It then triggers the creation of the actual VPN configs.
    """
    await vpn_manager.create_user(user_id)
    try:
        await db.execute("BEGIN")
        current_date = datetime.now(timezone.utc).isoformat()
        end_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        await db.execute(
            "UPDATE users SET status = ?, access_granted_date = ?, access_duration = ?, access_end_date = ? WHERE id = ?",
            ("accepted", current_date, days, end_date, user_id),
        )
        await db.commit()
    except aiosqlite.Error as e:
        await db.rollback()
        logger.error(f"Transaction failed while granting access to user {user_id}: {e}", exc_info=True)
        raise


async def update_request_status(db: aiosqlite.Connection, user_id: int, status: str) -> None:
    """Updates the status of a user's request."""
    try:
        await db.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        await db.commit()
    except aiosqlite.Error:
        logger.error(f"Error updating request status for user {user_id}:", exc_info=True)


async def get_pending_requests(db: aiosqlite.Connection) -> list:
    """Returns a list of users with a 'pending' or 'expired' status."""
    try:
        async with db.execute("SELECT * FROM users WHERE status = 'pending' OR status = 'expired'") as cursor:
            return await cursor.fetchall()
    except aiosqlite.Error:
        logger.error("Error getting pending requests:", exc_info=True)
        return []


async def get_accepted_users(db: aiosqlite.Connection) -> list:
    """Returns a list of users with an 'accepted' status."""
    try:
        async with db.execute("SELECT id, username, access_end_date FROM users WHERE status = 'accepted'") as cursor:
            return await cursor.fetchall()
    except aiosqlite.Error:
        logger.error("Error getting accepted users:", exc_info=True)
        return []


async def update_user_access(
    db: aiosqlite.Connection, user_id: int, access_end_date: str, has_used_trial: int | None = None
) -> None:
    """Updates a user's access end date and, optionally, their trial status."""
    try:
        await db.execute("BEGIN")
        if has_used_trial is not None:
            await db.execute(
                "UPDATE users SET status = 'accepted', access_end_date = ?, has_used_trial = ? WHERE id = ?",
                (access_end_date, has_used_trial, user_id),
            )
        else:
            await db.execute(
                "UPDATE users SET status = 'accepted', access_end_date = ? WHERE id = ?",
                (access_end_date, user_id),
            )
        await db.commit()
    except aiosqlite.Error:
        await db.rollback()
        logger.error(f"Error updating user access for {user_id}:", exc_info=True)


async def delete_user(db: aiosqlite.Connection, user_id: int) -> bool:
    """Deletes a user from the database and removes their configurations."""
    await vpn_manager.delete_user(user_id)
    try:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
        return True
    except aiosqlite.Error:
        logger.error(f"Error deleting user {user_id}:", exc_info=True)
        return False


async def get_users_list(db: aiosqlite.Connection) -> str | None:
    """Retrieves a list of all users and writes it to a CSV file."""
    try:
        async with db.execute(
            "SELECT id, username, status, access_granted_date, access_duration, access_end_date, last_notification_id, has_used_trial FROM users"
        ) as cursor:
            column_names = [description[0] for description in cursor.description]
            file_name = "users_list.csv"
            async with aiofiles.open(file_name, "w", encoding="utf-8") as file:
                if column_names:
                    await file.write(",".join(f'"{col}"' for col in column_names) + "\n")
                    async for row in cursor:
                        formatted_row = [f'"{str(item).replace("\"", "")}"' if item is not None else '""' for item in row]
                        await file.write(",".join(formatted_row) + "\n")
                else:
                    await file.write("No users found in the database.\n")
        return file_name
    except (aiosqlite.Error, IOError, OSError):
        logger.error("Error getting user list:", exc_info=True)
        return None


async def add_promo_code(
    db: aiosqlite.Connection, code: str, days_duration: int, usage_count: int
) -> bool:
    """Adds a new promo code to the database."""
    try:
        await db.execute(
            "INSERT INTO promo_codes (code, days_duration, is_active, usage_count) VALUES (?, ?, 1, ?)",
            (code, days_duration, usage_count),
        )
        await db.commit()
        logger.info(f"Promo code {code} added.")
        return True
    except aiosqlite.IntegrityError:
        logger.warning(f"Promo code {code} already exists.")
        return False
    except aiosqlite.Error as e:
        logger.error(f"Error adding promo code {code}: {e}", exc_info=True)
        return False


async def get_promo_code(db: aiosqlite.Connection, code: str) -> tuple | None:
    """Retrieves information about a promo code by its code."""
    async with db.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)) as cursor:
        return await cursor.fetchone()


async def delete_promo_code(db: aiosqlite.Connection, code: str) -> bool:
    """Deletes a promo code from the database."""
    try:
        await db.execute("DELETE FROM user_promo_codes WHERE promo_code = ?", (code,))
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
        await db.commit()
        logger.info(f"Promo code {code} and all its usages have been deleted.")
        return True
    except aiosqlite.Error as e:
        logger.error(f"Error deleting promo code {code}: {e}", exc_info=True)
        return False


async def record_promo_code_usage(db: aiosqlite.Connection, user_id: int, promo_code: str) -> None:
    """Records the usage of a promo code by a user."""
    try:
        await db.execute(
            "INSERT INTO user_promo_codes (user_id, promo_code) VALUES (?, ?)", (user_id, promo_code)
        )
        await db.commit()
        logger.info(f"User {user_id} used promo code {promo_code}.")
    except aiosqlite.IntegrityError:
        logger.warning(f"User {user_id} has already used promo code {promo_code}.")
    except aiosqlite.Error as e:
        logger.error(f"Error recording promo code usage for user {user_id}: {e}", exc_info=True)


async def has_user_used_promo_code(db: aiosqlite.Connection, user_id: int, promo_code: str) -> bool:
    """Checks if a user has already used a specific promo code."""
    async with db.execute(
        "SELECT 1 FROM user_promo_codes WHERE user_id = ? AND promo_code = ?", (user_id, promo_code)
    ) as cursor:
        return await cursor.fetchone() is not None


async def get_all_promo_codes(db: aiosqlite.Connection) -> list:
    """Returns a list of all promo codes."""
    try:
        async with db.execute("SELECT * FROM promo_codes") as cursor:
            return await cursor.fetchall()
    except aiosqlite.Error:
        logger.error("Error getting promo code list:", exc_info=True)
        return []


async def update_promo_code_usage(db: aiosqlite.Connection, code: str, new_usage_count: int) -> bool:
    """Updates the usage count of a promo code and deactivates it if the count reaches zero."""
    try:
        is_active = 1 if new_usage_count > 0 else 0
        await db.execute(
            "UPDATE promo_codes SET usage_count = ?, is_active = ? WHERE code = ?",
            (new_usage_count, is_active, code),
        )
        await db.commit()
        logger.info(f"Promo code {code} usage updated to {new_usage_count}. Active: {bool(is_active)}.")
        return True
    except aiosqlite.Error as e:
        logger.error(f"Error updating promo code usage for {code}: {e}", exc_info=True)
        return False


async def update_last_notification_id(db: aiosqlite.Connection, user_id: int, message_id: int) -> None:
    """Updates the ID of the last notification sent to the user."""
    try:
        await db.execute("UPDATE users SET last_notification_id = ? WHERE id = ?", (message_id, user_id))
        await db.commit()
    except aiosqlite.Error:
        logger.error(f"Error updating last notification ID for user {user_id}:", exc_info=True)


async def get_users_with_notifications(db: aiosqlite.Connection) -> list:
    """Returns a list of users who should receive notifications."""
    try:
        async with db.execute("SELECT id, access_end_date, last_notification_id FROM users WHERE status = 'accepted'") as cursor:
            return await cursor.fetchall()
    except aiosqlite.Error:
        logger.error("Error getting user list for notifications:", exc_info=True)
        return []


async def get_all_users(db: aiosqlite.Connection) -> list[int]:
    """Returns a list of all user IDs."""
    try:
        async with db.execute("SELECT id FROM users") as cursor:
            return [row[0] for row in await cursor.fetchall()]
    except aiosqlite.Error:
        logger.error("Error getting all users:", exc_info=True)
        return []
