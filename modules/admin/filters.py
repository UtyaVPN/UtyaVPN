from aiogram import types
from aiogram.filters import Filter

from config.settings import ADMIN_ID


class IsAdmin(Filter):
    """
    A filter to check if a user is the designated administrator.

    This filter is used in message handlers to restrict access to administrative
    commands and functionality.
    """

    async def __call__(self, message: types.Message) -> bool:
        """
        Checks if the message sender's ID matches the admin ID.

        Args:
            message: The message object to check.

        Returns:
            True if the user is the admin, False otherwise.
        """
        return message.from_user.id == ADMIN_ID
