from aiogram.fsm.state import State, StatesGroup

# Class for storing user states in FSM (Finite State Machine)


class Form(StatesGroup):
    """
    A class for managing user states in the bot using a Finite State Machine (FSM).

    This class defines the different states a user can be in while interacting
    with the bot, such as waiting for input or confirmation.
    """

    waiting_for_site_names = State()
    waiting_for_promo_code = State()
    waiting_for_promo_code_data = State()
    waiting_for_promo_code_to_deactivate = State()
    waiting_for_promo_code_to_delete = State()

    # State when the bot is waiting for a broadcast message
    waiting_for_broadcast_message = State()

    # State when the bot is waiting for a user ID
    waiting_for_user_id = State()

    # State when the bot is waiting for a number of days
    waiting_for_n_days = State()
    waiting_for_site_confirmation = State()
