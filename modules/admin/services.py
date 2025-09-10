import logging

from services import vpn_manager

logger = logging.getLogger(__name__)


def get_day_word(days: int) -> str:
    """
    Returns the correct grammatical form of the word "day" in Russian.

    This function handles the pluralization of the word "день" (day) based on
    the provided number, following Russian grammatical rules.

    Args:
        days: The number of days.

    Returns:
        The correctly pluralized word for "day".
    """
    if 10 <= days % 100 <= 20:
        return "дней"
    if days % 10 == 1:
        return "день"
    if 2 <= days % 10 <= 4:
        return "дня"
    return "дней"


async def update_user_configs(user_id: int) -> bool:
    """
    Updates or recreates VPN configurations for a specific user.

    This function calls the core `vpn_manager.create_user` function, which is
    designed to safely handle both new and existing users. If the user already
    exists, their configurations will be regenerated.

    Args:
        user_id: The unique identifier of the user.

    Returns:
        True if the configurations were updated successfully, False otherwise.
    """
    try:
        await vpn_manager.create_user(user_id)
        logger.info(f"Configurations updated for user {user_id}.")
        return True
    except Exception as e:
        logger.error(
            f"Error updating configurations for user {user_id}: {e}",
            exc_info=True,
        )
        return False
