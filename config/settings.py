"""
Configuration settings for the UtyaVPN bot.

This module loads environment variables and sets up essential configuration
parameters for the bot's operation, including API tokens, administrator IDs,
database paths, and various URLs.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot API Token
TOKEN: str = os.getenv("TOKEN")

# Telegram User ID for the bot administrator
ADMIN_ID: int = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None

# Telegram User ID for support contact
SUPPORT_ID: int = int(os.getenv("SUPPORT_ID")) if os.getenv("SUPPORT_ID") else None

# Path to the SQLite database file
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "users.db")

# Telegram Channel ID for trial period subscription check
TRIAL_CHANNEL_ID: int = int(os.getenv("TRIAL_CHANNEL_ID")) if os.getenv("TRIAL_CHANNEL_ID") else None

# URL of the public Telegram channel for users to subscribe to
PUBLIC_CHANNEL_URL: str = os.getenv("PUBLIC_CHANNEL_URL")

# Base path where VPN configuration files are stored
VPN_CONFIG_PATH: str = os.getenv("VPN_CONFIG_PATH", "/root/vpn")

# URLs for VPN instruction pages (OpenVPN and WireGuard)
OPENVPN_INSTRUCTION_URL: str = os.getenv("OPENVPN_INSTRUCTION_URL", "")
WIREGUARD_INSTRUCTION_URL: str = os.getenv("WIREGUARD_INSTRUCTION_URL", "")

# Timezone for scheduling tasks (e.g., 'Europe/Moscow')
TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Moscow")

# --- Validation --- #
if not TOKEN:
    raise ValueError("TOKEN environment variable is not set or is empty.")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID environment variable is not set or is empty.")
if not SUPPORT_ID:
    raise ValueError("SUPPORT_ID environment variable is not set or is empty.")
if not TRIAL_CHANNEL_ID:
    raise ValueError("TRIAL_CHANNEL_ID environment variable is not set or is empty.")
if not PUBLIC_CHANNEL_URL:
    raise ValueError("PUBLIC_CHANNEL_URL environment variable is not set or is empty.")

try:
    # Ensure ADMIN_ID, SUPPORT_ID, and TRIAL_CHANNEL_ID are integers
    int(ADMIN_ID)
    int(SUPPORT_ID)
    int(TRIAL_CHANNEL_ID)
except ValueError as e:
    raise ValueError(f"Environment variable type error: {e}. Ensure ADMIN_ID, SUPPORT_ID, and TRIAL_CHANNEL_ID are integers.")
