#!/bin/bash

# --- Configuration Variables ---
PROJECT_ROOT="/root/bot"
SERVICE_NAME="bot"
PYTHON_EXEC="python3"
VENV_DIR="venv"
REQUIREMENTS_FILE="requirements.txt"
MAIN_APP_FILE="main.py"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="${PROJECT_ROOT}/.env"

echo "--------------------------------------------------"
echo "UtyaVPN Setup Script"
echo "This script will guide you through setting up your UtyaVPN bot."
echo "It will configure environment variables, set up a Python virtual"
echo "environment, install dependencies, and create a systemd service."
echo "--------------------------------------------------"
echo ""

# --- Prompt for Environment Variables ---

echo "--- Basic Bot Configuration ---"
echo "Please provide the following essential information:"
echo ""

# TOKEN
read -p "Enter your Telegram Bot Token (from BotFather): " TOKEN_INPUT
echo "TOKEN="${TOKEN_INPUT}"" > "${ENV_FILE}"

# ADMIN_ID
read -p "Enter your Telegram Admin User ID (numeric): " ADMIN_ID_INPUT
echo "ADMIN_ID="${ADMIN_ID_INPUT}"" >> "${ENV_FILE}"

# SUPPORT_ID
read -p "Enter the Telegram User ID for support (numeric): " SUPPORT_ID_INPUT
echo "SUPPORT_ID="${SUPPORT_ID_INPUT}"" >> "${ENV_FILE}"

# PUBLIC_CHANNEL_URL
read -p "Enter the public Telegram Channel URL (e.g., https://t.me/UtyaNewsRU): " PUBLIC_CHANNEL_URL_INPUT
echo "PUBLIC_CHANNEL_URL="${PUBLIC_CHANNEL_URL_INPUT}"" >> "${ENV_FILE}"

# TRIAL_CHANNEL_ID
read -p "Enter the Telegram Channel ID for trial subscription (numeric, e.g., -1001234567890): " TRIAL_CHANNEL_ID_INPUT
echo "TRIAL_CHANNEL_ID="${TRIAL_CHANNEL_ID_INPUT}"" >> "${ENV_FILE}"

echo ""
echo "--- Advanced Configuration ---"
read -p "Do you want to customize advanced settings (paths, timezone, etc.)? (y/N): " CUSTOMIZE_ADVANCED
CUSTOMIZE_ADVANCED=${CUSTOMIZE_ADVANCED:-n}

if [[ "${CUSTOMIZE_ADVANCED,,}" == "y" ]]; then
  echo ""
  echo "Please provide the following information (press Enter to use the default value)."
  echo ""

  # TIMEZONE
  read -p "Enter the timezone [default: Europe/Moscow]: " TIMEZONE_INPUT
  TIMEZONE_INPUT=${TIMEZONE_INPUT:-Europe/Moscow}
  echo "TIMEZONE="${TIMEZONE_INPUT}"" >> "${ENV_FILE}"

  # DATABASE_PATH
  read -p "Enter the bot's database path [default: users.db]: " DATABASE_PATH_INPUT
  DATABASE_PATH_INPUT=${DATABASE_PATH_INPUT:-"users.db"}
  echo "DATABASE_PATH="${DATABASE_PATH_INPUT}"" >> "${ENV_FILE}"

  # ROOT_DIR
  read -p "Enter the root directory for VPN files [default: /root/antizapret]: " ROOT_DIR_INPUT
  ROOT_DIR_INPUT=${ROOT_DIR_INPUT:-/root/antizapret}
  echo "ROOT_DIR="${ROOT_DIR_INPUT}"" >> "${ENV_FILE}"

  # VPN_CONFIG_PATH
  read -p "Enter the path to generated VPN configs [default: /root/antizapret/client]: " VPN_CONFIG_PATH_INPUT
  VPN_CONFIG_PATH_INPUT=${VPN_CONFIG_PATH_INPUT:-"/root/antizapret/client"}
  echo "VPN_CONFIG_PATH="${VPN_CONFIG_PATH_INPUT}"" >> "${ENV_FILE}"

  # EASYRSA_DIR
  read -p "Enter the Easy-RSA directory path [default: /etc/openvpn/easyrsa3]: " EASYRSA_DIR_INPUT
  EASYRSA_DIR_INPUT=${EASYRSA_DIR_INPUT:-/etc/openvpn/easyrsa3}
  echo "EASYRSA_DIR="${EASYRSA_DIR_INPUT}"" >> "${ENV_FILE}"

  # OPENVPN_DIR
  read -p "Enter the OpenVPN directory path [default: /etc/openvpn]: " OPENVPN_DIR_INPUT
  OPENVPN_DIR_INPUT=${OPENVPN_DIR_INPUT:-/etc/openvpn}
  echo "OPENVPN_DIR="${OPENVPN_DIR_INPUT}"" >> "${ENV_FILE}"

  # WIREGUARD_DIR
  read -p "Enter the WireGuard directory path [default: /etc/wireguard]: " WIREGUARD_DIR_INPUT
  WIREGUARD_DIR_INPUT=${WIREGUARD_DIR_INPUT:-/etc/wireguard}
  echo "WIREGUARD_DIR="${WIREGUARD_DIR_INPUT}"" >> "${ENV_FILE}"

  # XRAY_DB_PATH
  read -p "Enter the path for the Xray database [default: /root/antizapret/xray.db]: " XRAY_DB_PATH_INPUT
  XRAY_DB_PATH_INPUT=${XRAY_DB_PATH_INPUT:-/root/antizapret/xray.db}
  echo "XRAY_DB_PATH="${XRAY_DB_PATH_INPUT}"" >> "${ENV_FILE}"

  # XRAY_API_HOST
  read -p "Enter the Xray API host [default: 127.0.0.1]: " XRAY_API_HOST_INPUT
  XRAY_API_HOST_INPUT=${XRAY_API_HOST_INPUT:-127.0.0.1}
  echo "XRAY_API_HOST="${XRAY_API_HOST_INPUT}"" >> "${ENV_FILE}"

  # XRAY_API_PORT
  read -p "Enter the Xray API port [default: 10085]: " XRAY_API_PORT_INPUT
  XRAY_API_PORT_INPUT=${XRAY_API_PORT_INPUT:-10085}
  echo "XRAY_API_PORT="${XRAY_API_PORT_INPUT}"" >> "${ENV_FILE}"

else
  echo ""
  echo "Using default values for advanced settings."
  echo "TIMEZONE=\"Europe/Moscow\"" >> "${ENV_FILE}"
  echo "DATABASE_PATH=\"users.db\"" >> "${ENV_FILE}"
  echo "ROOT_DIR=\"/root/antizapret\"" >> "${ENV_FILE}"
  echo "VPN_CONFIG_PATH=\"/root/antizapret/client\"" >> "${ENV_FILE}"
  echo "EASYRSA_DIR=\"/etc/openvpn/easyrsa3\"" >> "${ENV_FILE}"
  echo "OPENVPN_DIR=\"/etc/openvpn\"" >> "${ENV_FILE}"
  echo "WIREGUARD_DIR=\"/etc/wireguard\"" >> "${ENV_FILE}"
  echo "XRAY_DB_PATH=\"/root/antizapret/xray.db\"" >> "${ENV_FILE}"
  echo "XRAY_API_HOST=\"127.0.0.1\"" >> "${ENV_FILE}"
  echo "XRAY_API_PORT=\"10085\"" >> "${ENV_FILE}"
fi

echo ""
echo "Environment variables saved to ${ENV_FILE}"
echo "--------------------------------------------------"
echo ""

# --- Virtual Environment Setup ---

# --- Locale Setup ---
echo "Setting up locale ru_RU.UTF-8..."
sudo apt-get update && sudo apt-get install -y locales || { echo "Error: Failed to install locales package."; exit 1; }
sudo locale-gen ru_RU.UTF-8 || { echo "Error: Failed to generate ru_RU.UTF8 locale."; exit 1; }
sudo update-locale LANG=ru_RU.UTF-8 || { echo "Error: Failed to set default locale."; exit 1; }
export LANG=ru_RU.UTF-8
export LC_ALL=ru_RU.UTF-8
echo "Locale setup complete."
echo "--------------------------------------------------"
echo ""

echo "Setting up Python virtual environment..."
cd "${PROJECT_ROOT}" || { echo "Error: Could not change to project directory."; exit 1; }

if ! command -v "${PYTHON_EXEC}" &> /dev/null; then
    echo "Error: ${PYTHON_EXEC} is not installed. Please install Python 3."
    exit 1
fi

# Ensure python3-venv is installed for creating virtual environments
sudo apt-get update && sudo apt-get install -y python3-venv || { echo "Error: Failed to install python3-venv. Please install it manually."; exit 1; }

"${PYTHON_EXEC}" -m venv "${VENV_DIR}" || { echo "Error: Failed to create virtual environment."; exit 1; }
echo "Virtual environment created at ${PROJECT_ROOT}/${VENV_DIR}"

source "${VENV_DIR}/bin/activate" || { echo "Error: Failed to activate virtual environment."; exit 1; }
echo "Virtual environment activated."

echo "Installing dependencies from ${REQUIREMENTS_FILE}..."
pip install -r "${REQUIREMENTS_FILE}" || { echo "Error: Failed to install dependencies."; exit 1; }
echo "Dependencies installed."

deactivate
echo "Virtual environment deactivated."
echo "--------------------------------------------------"
echo ""

# --- Systemd Service Creation ---

echo "Creating systemd service file: ${SERVICE_FILE}..."

cat <<EOF | sudo tee "${SERVICE_FILE}"
[Unit]
Description=${SERVICE_NAME} Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=${PROJECT_ROOT}
ExecStart=${PROJECT_ROOT}/${VENV_DIR}/bin/${PYTHON_EXEC} ${PROJECT_ROOT}/${MAIN_APP_FILE}
Restart=always
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

if [ $? -ne 0 ]; then
    echo "Error: Failed to create systemd service file. Do you have sudo privileges?"
    exit 1
fi
echo "Systemd service file created."

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload || { echo "Error: Failed to reload systemd daemon."; exit 1; }

echo "Enabling and starting ${SERVICE_NAME} service..."
sudo systemctl enable "${SERVICE_NAME}" || { echo "Error: Failed to enable service."; exit 1; }
sudo systemctl start "${SERVICE_NAME}" || { echo "Error: Failed to start service."; exit 1; }

echo "Checking service status..."
sudo systemctl status "${SERVICE_NAME}" --no-pager

echo "--------------------------------------------------"
echo "Setup complete!"
echo "The UtyaVPN bot should now be running as a systemd service."
echo "You can check its status with: sudo systemctl status ${SERVICE_NAME}"
echo "You can view logs with: journalctl -u ${SERVICE_NAME} -f"
echo "--------------------------------------------------"
