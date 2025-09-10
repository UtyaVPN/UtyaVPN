import os
import pathlib
import asyncio
import aiosqlite
import re
import shutil
from datetime import datetime
import json
import sqlite3
from xtlsapi import XrayClient, utils
from contextlib import asynccontextmanager
import aiofiles
from collections import defaultdict


class Config:
    """
    Manages the configuration for the VPN services.

    This class loads configuration settings from a specified setup file
    and provides a centralized point of access to these settings. It defines
    default values for essential paths and parameters, which can be overridden
    by the contents of the setup file.

    Attributes:
        config (dict): A dictionary holding the key-value pairs of the configuration.
        ROOT_DIR (str): The root directory for the application's files.
        EASYRSA_DIR (str): The directory for Easy-RSA, used for OpenVPN PKI management.
        OPENVPN_DIR (str): The directory for OpenVPN server and client configurations.
        WIREGUARD_DIR (str): The directory for WireGuard server and client configurations.
        XRAY_DB_PATH (str): The path to the SQLite database for Xray user management.
        XRAY_API_HOST (str): The host for the Xray API.
        XRAY_API_PORT (int): The port for the Xray API.
        IP (str): The base IP address scheme to use ('172' or '10').
        CLIENT_BASE_DIR (str): The base directory where client configuration files are stored.
        BACKUP_BASE_DIR (str): The base directory for backups.
        SERVER_CONFIG_PATH (str): The path to the main server setup file.
    """

    def __init__(self, setup_file_path: str = "/root/antizapret/setup"):
        """
        Initializes the Config object by loading settings from the setup file.

        Args:
            setup_file_path (str): The absolute path to the setup file.
        """
        self.config: dict[str, str] = {}
        self.load_config(setup_file_path)

        # Core application paths
        self.ROOT_DIR: str = self.get("ROOT_DIR", "/root/antizapret")
        self.CLIENT_BASE_DIR: str = os.path.join(self.ROOT_DIR, "client")
        self.BACKUP_BASE_DIR: str = os.path.join(self.ROOT_DIR, "backup")
        self.SERVER_CONFIG_PATH: str = os.path.join(self.ROOT_DIR, "setup")

        # VPN service-specific paths
        self.EASYRSA_DIR: str = self.get("EASYRSA_DIR", "/etc/openvpn/easyrsa3")
        self.OPENVPN_DIR: str = self.get("OPENVPN_DIR", "/etc/openvpn")
        self.WIREGUARD_DIR: str = self.get("WIREGUARD_DIR", "/etc/wireguard")

        # Xray (VLESS) configuration
        self.XRAY_DB_PATH: str = self.get("XRAY_DB_PATH", "/root/antizapret/xray.db")
        self.XRAY_API_HOST: str = self.get("XRAY_API_HOST", "127.0.0.1")
        self.XRAY_API_PORT: int = int(self.get("XRAY_API_PORT", 10085))

        # Network configuration
        self.IP: str = "172" if self.get("ALTERNATIVE_IP", "n").lower() == "y" else "10"

    def load_config(self, setup_file_path: str) -> None:
        """
        Loads configuration from a file, parsing key-value pairs.

        Args:
            setup_file_path: The path to the configuration file.

        Raises:
            FileNotFoundError: If the setup file does not exist.
        """
        if not os.path.exists(setup_file_path):
            raise FileNotFoundError(f"Setup file not found: {setup_file_path}")
        with open(setup_file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    self.config[key.strip()] = value.strip()

    def get(self, key: str, default: str | None = None) -> str | None:
        """
        Retrieves a configuration value by its key.

        Args:
            key: The configuration key to retrieve.
            default: The default value to return if the key is not found.

        Returns:
            The configuration value, or the default if not found.
        """
        return self.config.get(key, default)



config = Config()
SERVER_IP: str | None = None
openvpn_lock = asyncio.Lock()
user_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def handle_error(lineno: int | str, command: str, message: str = "") -> None:
    """
    Logs an error message with context.

    Args:
        lineno: The line number where the error occurred.
        command: The command or operation that failed.
        message: A descriptive error message.
    """
    print(f"Error at line {lineno}: {command}")
    if message:
        print(f"Message: {message}")


async def run_command(
    command_args: list[str],
    input_data: str | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Executes a shell command asynchronously and returns its output.

    Args:
        command_args: A list of strings representing the command and its arguments.
        input_data: Optional string to be passed to the command's stdin.
        cwd: The working directory for the command.
        env: A dictionary of environment variables for the command.

    Returns:
        A tuple containing the stdout and stderr of the command as strings,
        or (None, None) if an error occurs.
    """
    print(f"Running: {' '.join(command_args)}")
    process = await asyncio.create_subprocess_exec(
        *command_args,
        stdin=asyncio.subprocess.PIPE if input_data else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    stdout, stderr = await process.communicate(
        input=input_data.encode() if input_data else None
    )

    if process.returncode != 0:
        await handle_error(
            "N/A",
            " ".join(command_args),
            f"Command failed with exit code {process.returncode}:\n{stderr.decode()}",
        )
        return None, None

    return stdout.decode(), stderr.decode()


@asynccontextmanager
async def file_lock(lock_file_path: str):
    """
    An asynchronous context manager to ensure exclusive access to a resource
    using a lock file.

    Args:
        lock_file_path: The path to the file to be locked.

    Yields:
        None.

    Raises:
        IOError: If the lock file already exists.
    """
    lock_file = f"{lock_file_path}.lock"
    if await asyncio.to_thread(os.path.exists, lock_file):
        raise IOError(
            f"Lock file {lock_file} already exists. Another instance may be running."
        )
    try:
        async with aiofiles.open(lock_file, "w") as f:
            await f.write(str(os.getpid()))
        yield
    finally:
        if await asyncio.to_thread(os.path.exists, lock_file):
            await asyncio.to_thread(os.remove, lock_file)


async def extract_cert_content(cert_path: str) -> str:
    """
    Extracts the content of a certificate from a file.

    Args:
        cert_path: The path to the certificate file.

    Returns:
        The certificate content as a string, or an empty string if an error occurs.
    """
    try:
        async with aiofiles.open(cert_path, "r") as f:
            content = await f.read()
        start_marker = "-----BEGIN CERTIFICATE-----"
        end_marker = "-----END CERTIFICATE-----"
        start_index = content.find(start_marker)
        end_index = content.find(end_marker)
        if start_index != -1 and end_index != -1:
            return content[start_index : end_index + len(end_marker)]
    except IOError as e:
        print(f"Could not read certificate file {cert_path}: {e}")
    return ""


async def modify_wg_config(
    config_path: str, client_name: str, new_peer_block: str | None = None
) -> bool:
    """
    Modifies a WireGuard configuration file to add or remove a peer.

    Args:
        config_path: The path to the WireGuard configuration file.
        client_name: The name of the client to modify.
        new_peer_block: The new peer block to add. If None, the client is removed.

    Returns:
        True if the client was found and modified, False otherwise.
    """
    if not await asyncio.to_thread(os.path.exists, config_path):
        return False

    async with aiofiles.open(config_path, "r") as f:
        lines = await f.readlines()

    new_lines = []
    client_found = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == f"# Client = {client_name}":
            client_found = True
            # Skip the existing peer block
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                i += 1
            if i < len(lines) and lines[i].strip() == "":
                i += 1
            continue
        new_lines.append(line)
        i += 1

    # Remove trailing empty lines
    while new_lines and new_lines[-1].strip() == "":
        new_lines.pop()

    if new_peer_block:
        new_lines.append("\n")
        new_lines.append(new_peer_block)
        new_lines.append("\n")

    async with aiofiles.open(config_path, "w") as f:
        await f.writelines(new_lines)

    return client_found


async def sync_wireguard_config(interface_name: str) -> None:
    """
    Synchronizes the running WireGuard configuration with the configuration file.

    Args:
        interface_name: The name of the WireGuard interface to sync.
    """
    stdout, _ = await run_command(
        ["systemctl", "is-active", "--quiet", f"wg-quick@{interface_name}"]
    )
    if stdout is None:
        return

    print(f"Syncing active WireGuard interface: {interface_name}")
    try:
        stripped_config, _ = await run_command(["wg-quick", "strip", interface_name])
        if stripped_config:
            await run_command(
                ["wg", "syncconf", interface_name, "/dev/stdin"],
                input_data=stripped_config,
            )
    except Exception as e:
        print(f"An error occurred during wg syncconf for {interface_name}: {e}")


async def set_server_host_file_name(
    client_name: str, server_host_override: str = ""
) -> tuple[str, str]:
    """
    Sets the server host and file name for a client configuration.

    Args:
        client_name: The name of the client.
        server_host_override: An optional override for the server host.

    Returns:
        A tuple containing the server host and the generated file name.
    """
    global SERVER_HOST, FILE_NAME
    SERVER_HOST = server_host_override or SERVER_IP
    FILE_NAME = client_name.replace("antizapret-", "").replace("vpn-", "")
    FILE_NAME = f"{FILE_NAME}-({SERVER_HOST})"
    return SERVER_HOST, FILE_NAME


async def render(template_file_path: str, variables: dict[str, str]) -> str:
    """
    Renders a template file by replacing variables with their values.

    Args:
        template_file_path: The path to the template file.
        variables: A dictionary of variable names and their values.

    Returns:
        The rendered content as a string.
    """
    async with aiofiles.open(template_file_path, "r") as f:
        content = await f.read()
    for var_name, value in variables.items():
        content = content.replace(f"${{{var_name}}}", str(value))
    # Remove any unreplaced variables
    content = re.sub(r"\$\{[a-zA-Z_][a-zA-Z_0-9]*}", "", content)
    return content



async def init_openvpn() -> None:
    """
    Initializes the OpenVPN Public Key Infrastructure (PKI) using Easy-RSA.

    This function checks for an existing PKI and, if not found or incomplete,
    creates a new one. It generates the Certificate Authority (CA), server
    certificate, and a Certificate Revocation List (CRL).
    """
    print("\nInitializing OpenVPN EasyRSA PKI...")
    pki_dir = os.path.join(config.EASYRSA_DIR, "pki")
    server_keys_dir = os.path.join(config.OPENVPN_DIR, "server/keys")
    client_keys_dir = os.path.join(config.OPENVPN_DIR, "client/keys")

    await asyncio.to_thread(os.makedirs, config.EASYRSA_DIR, exist_ok=True)

    # Check if PKI is already initialized
    if not all(
        await asyncio.to_thread(os.path.exists, p)
        for p in [
            os.path.join(pki_dir, "ca.crt"),
            os.path.join(pki_dir, "issued/antizapret-server.crt"),
        ]
    ):
        print("PKI not found or incomplete. Initializing new PKI...")
        # Clean up existing directories if they are in an inconsistent state
        for d in [pki_dir, server_keys_dir, client_keys_dir]:
            if await asyncio.to_thread(os.path.exists, d):
                await asyncio.to_thread(shutil.rmtree, d)

        # Initialize PKI, build CA, and server certificate
        await run_command(["/usr/share/easy-rsa/easyrsa", "init-pki"], cwd=config.EASYRSA_DIR)
        await run_command(
            ["/usr/share/easy-rsa/easyrsa", "--batch", "--req-cn=AntiZapret CA", "build-ca", "nopass"],
            cwd=config.EASYRSA_DIR,
            env={"EASYRSA_CA_EXPIRE": "3650", **os.environ},
        )
        await run_command(
            ["/usr/share/easy-rsa/easyrsa", "--batch", "build-server-full", "antizapret-server", "nopass"],
            cwd=config.EASYRSA_DIR,
            env={"EASYRSA_CERT_EXPIRE": "3650", **os.environ},
        )
    else:
        print("OpenVPN PKI already initialized.")

    # Ensure server and client key directories exist
    await asyncio.to_thread(os.makedirs, server_keys_dir, exist_ok=True)
    await asyncio.to_thread(os.makedirs, client_keys_dir, exist_ok=True)

    # Copy necessary keys and certificates to the OpenVPN server directory
    for f in ["ca.crt", "antizapret-server.crt", "antizapret-server.key"]:
        src_path = os.path.join(
            pki_dir,
            "issued" if f == "antizapret-server.crt" else "private" if f.endswith(".key") else "",
            f,
        )
        dest_path = os.path.join(server_keys_dir, f)
        if not await asyncio.to_thread(os.path.exists, dest_path):
            await asyncio.to_thread(shutil.copy, src_path, dest_path)

    # Generate and copy the CRL
    crl_path = os.path.join(server_keys_dir, "crl.pem")
    if not await asyncio.to_thread(os.path.exists, crl_path):
        print("Generating CRL...")
        await run_command(
            ["/usr/share/easy-rsa/easyrsa", "gen-crl"],
            cwd=config.EASYRSA_DIR,
            env={"EASYRSA_CRL_DAYS": "3650", **os.environ},
        )
        await asyncio.to_thread(shutil.copy, os.path.join(pki_dir, "crl.pem"), crl_path)
        await asyncio.to_thread(os.chmod, crl_path, 0o644)


async def add_openvpn(client_name: str, client_cert_expire_days: int = 3650) -> None:
    """
    Adds or renews an OpenVPN client certificate and generates configuration files.

    Args:
        client_name: The name of the client to add or renew.
        client_cert_expire_days: The number of days until the client certificate expires.
    """
    print(f"\nAdding/Renewing OpenVPN client: {client_name}")
    client_dir = os.path.join(config.CLIENT_BASE_DIR, client_name)
    await asyncio.to_thread(os.makedirs, client_dir, exist_ok=True)

    # Clean up old profiles
    for f in await asyncio.to_thread(os.listdir, client_dir):
        if f.endswith(".ovpn"):
            await asyncio.to_thread(os.remove, os.path.join(client_dir, f))

    await set_server_host_file_name(client_name, config.get("OPENVPN_HOST"))
    pki_dir = os.path.join(config.EASYRSA_DIR, "pki")
    client_crt_path = os.path.join(pki_dir, "issued", f"{client_name}.crt")
    client_key_path = os.path.join(pki_dir, "private", f"{client_name}.key")

    # Revoke existing certificate if it exists
    if await asyncio.to_thread(os.path.exists, client_crt_path):
        print(f"Client '{client_name}' already exists. Forcing renewal...")
        await run_command(
            ["/usr/share/easy-rsa/easyrsa", "--batch", "revoke", client_name],
            cwd=config.EASYRSA_DIR,
        )

    # Build new client certificate
    await run_command(
        ["/usr/share/easy-rsa/easyrsa", "--batch", "build-client-full", client_name, "nopass"],
        cwd=config.EASYRSA_DIR,
        env={"EASYRSA_CERT_EXPIRE": str(client_cert_expire_days), **os.environ},
    )

    # Copy keys to the client keys directory
    client_keys_dir = os.path.join(config.OPENVPN_DIR, "client/keys")
    await asyncio.to_thread(shutil.copy, client_crt_path, os.path.join(client_keys_dir, f"{client_name}.crt"))
    await asyncio.to_thread(shutil.copy, client_key_path, os.path.join(client_keys_dir, f"{client_name}.key"))

    # Load key and certificate content
    ca_cert_content = await extract_cert_content(os.path.join(config.OPENVPN_DIR, "server/keys/ca.crt"))
    client_cert_content = await extract_cert_content(os.path.join(client_keys_dir, f"{client_name}.crt"))
    async with aiofiles.open(os.path.join(client_keys_dir, f"{client_name}.key"), "r") as f:
        client_key_content = await f.read()

    if not all([ca_cert_content, client_cert_content, client_key_content]):
        await handle_error("N/A", "Key loading", "Cannot load client keys!")
        return

    # Render and save client configuration files
    current_date = datetime.now().strftime("%y-%m-%d")
    render_vars = {
        "SERVER_HOST": SERVER_HOST,
        "CA_CERT": ca_cert_content,
        "CLIENT_CERT": client_cert_content,
        "CLIENT_KEY": client_key_content,
        "SERVER_IP": SERVER_IP,
        **config.config,
    }

    templates_dir = os.path.join(config.OPENVPN_DIR, "client/templates")
    templates = {
        "antizapret-udp.conf": f"AZ-UDP-{current_date}.ovpn",
        "antizapret-tcp.conf": f"AZ-TCP-{current_date}.ovpn",
        "antizapret.conf": f"AZ-U+T-{current_date}.ovpn",
        "vpn-udp.conf": f"GL-UDP-{current_date}.ovpn",
        "vpn-tcp.conf": f"GL-TCP-{current_date}.ovpn",
        "vpn.conf": f"GL-U+T-{current_date}.ovpn",
    }

    for template, output_filename in templates.items():
        template_path = os.path.join(templates_dir, template)
        if await asyncio.to_thread(os.path.exists, template_path):
            output_path = os.path.join(client_dir, output_filename)
            rendered_content = await render(template_path, render_vars)
            async with aiofiles.open(output_path, "w") as f:
                await f.write(rendered_content)

    print(f"OpenVPN profile files (re)created for client '{client_name}' at {client_dir}")


async def delete_openvpn(client_name: str) -> None:
    """
    Revokes an OpenVPN client certificate and removes associated files.

    Args:
        client_name: The name of the client to delete.
    """
    print(f"\nDeleting OpenVPN client: {client_name}")

    # Revoke the client certificate and regenerate the CRL
    await run_command(
        ["/usr/share/easy-rsa/easyrsa", "--batch", "revoke", client_name],
        cwd=config.EASYRSA_DIR,
    )
    await run_command(
        ["/usr/share/easy-rsa/easyrsa", "gen-crl"],
        cwd=config.EASYRSA_DIR,
        env={"EASYRSA_CRL_DAYS": "3650", **os.environ},
    )

    # Update the CRL file
    pki_dir = os.path.join(config.EASYRSA_DIR, "pki")
    crl_src = os.path.join(pki_dir, "crl.pem")
    crl_dest = os.path.join(config.OPENVPN_DIR, "server/keys/crl.pem")
    await asyncio.to_thread(shutil.copy, crl_src, crl_dest)
    await asyncio.to_thread(os.chmod, crl_dest, 0o644)

    # Remove client-specific files
    client_dir = os.path.join(config.CLIENT_BASE_DIR, client_name)
    if await asyncio.to_thread(os.path.isdir, client_dir):
        for f in await asyncio.to_thread(os.listdir, client_dir):
            if f.endswith(".ovpn"):
                await asyncio.to_thread(os.remove, os.path.join(client_dir, f))

    for ext in [".crt", ".key"]:
        p = os.path.join(config.OPENVPN_DIR, f"client/keys/{client_name}{ext}")
        if await asyncio.to_thread(os.path.exists, p):
            await asyncio.to_thread(os.remove, p)

    print(f"OpenVPN client '{client_name}' successfully deleted")



async def init_wireguard() -> None:
    """
    Initializes WireGuard server keys and configuration files.

    This function generates a private and public key pair for the WireGuard server
    if they don't already exist. It then uses these keys to render server-side
    configuration files from templates.
    """
    print("\nInitializing WireGuard/AmneziaWG server keys...")
    await asyncio.to_thread(os.makedirs, config.WIREGUARD_DIR, exist_ok=True)
    key_path = os.path.join(config.WIREGUARD_DIR, "key")

    if not await asyncio.to_thread(os.path.exists, key_path):
        private_key, _ = await run_command(["wg", "genkey"])
        public_key, _ = await run_command(["wg", "pubkey"], input_data=private_key)

        async with aiofiles.open(key_path, "w") as f:
            await f.write(f"PRIVATE_KEY={private_key.strip()}\nPUBLIC_KEY={public_key.strip()}\n")

        render_vars = {
            "PRIVATE_KEY": private_key.strip(),
            "PUBLIC_KEY": public_key.strip(),
            "SERVER_IP": SERVER_IP,
            **config.config,
        }

        templates_dir = os.path.join(config.WIREGUARD_DIR, "templates")
        for conf_name in ["antizapret.conf", "vpn.conf"]:
            template_path = os.path.join(templates_dir, conf_name)
            if await asyncio.to_thread(os.path.exists, template_path):
                rendered_conf = await render(template_path, render_vars)
                async with aiofiles.open(os.path.join(config.WIREGUARD_DIR, conf_name), "w") as f:
                    await f.write(rendered_conf)
        print("WireGuard/AmneziaWG server keys and configs generated.")
    else:
        print("WireGuard/AmneziaWG server keys already exist.")


async def add_wireguard(client_name: str) -> None:
    """
    Adds a new WireGuard/AmneziaWG client.

    This function generates a new key pair for the client, finds an available IP
    address in the subnet, and adds the client as a peer to the server's
    configuration. It then generates client-specific configuration files.

    Args:
        client_name: The name of the client to add.
    """
    print(f"\nAdding WireGuard/AmneziaWG client: {client_name}")
    client_dir = os.path.join(config.CLIENT_BASE_DIR, client_name)
    await asyncio.to_thread(os.makedirs, client_dir, exist_ok=True)

    # Clean up old profiles
    for f in await asyncio.to_thread(os.listdir, client_dir):
        if f.endswith(".conf"):
            await asyncio.to_thread(os.remove, os.path.join(client_dir, f))

    await set_server_host_file_name(client_name, config.get("WIREGUARD_HOST"))

    key_path = os.path.join(config.WIREGUARD_DIR, "key")
    if not await asyncio.to_thread(os.path.exists, key_path):
        await handle_error("N/A", "WireGuard key loading", "WireGuard server keys not found. Run init_wireguard first.")
        return

    async with aiofiles.open(key_path, "r") as f:
        content = await f.read()
        server_public_key = re.search(r"PUBLIC_KEY=(.*)", content).group(1)

    ips_path = os.path.join(config.WIREGUARD_DIR, "ips")
    ips_content = ""
    if await asyncio.to_thread(os.path.exists, ips_path):
        async with aiofiles.open(ips_path, "r") as f:
            ips_content = await f.read()

    current_date = datetime.now().strftime("%y-%m-%d")

    for wg_type in ["antizapret", "vpn"]:
        print(f"Processing {wg_type.capitalize()} WireGuard configuration...")
        conf_path = os.path.join(config.WIREGUARD_DIR, f"{wg_type}.conf")

        async with file_lock(conf_path):
            if await modify_wg_config(conf_path, client_name):
                print(f"Client '{client_name}' exists in {wg_type}.conf. Recreating...")

            client_private_key, _ = await run_command(["wg", "genkey"])
            client_public_key, _ = await run_command(["wg", "pubkey"], input_data=client_private_key)
            client_preshared_key, _ = await run_command(["wg", "genpsk"])

            async with aiofiles.open(conf_path, "r") as f:
                conf_content = await f.read()
                base_ip_match = re.search(r"Address = (\d{1,3}\.\d{1,3}\.\d{1,3})", conf_content)
                if not base_ip_match:
                    await handle_error("N/A", "IP assignment", f"Could not find base IP in {conf_path}")
                    continue
                base_client_ip = base_ip_match.group(1)

            existing_ips = set(re.findall(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", conf_content))

            client_ip = ""
            for i in range(2, 255):
                potential_ip = f"{base_client_ip}.{i}"
                if potential_ip not in existing_ips:
                    client_ip = potential_ip
                    break

            if not client_ip:
                await handle_error("N/A", "IP assignment", f"No available IPs in the {wg_type} subnet!")
                continue

            new_peer_block = (
                f"# Client = {client_name}\n# PrivateKey = {client_private_key.strip()}\n[Peer]\n"
                f"PublicKey = {client_public_key.strip()}\nPresharedKey = {client_preshared_key.strip()}\n"
                f"AllowedIPs = {client_ip}/32"
            )
            await modify_wg_config(conf_path, client_name, new_peer_block)

        await sync_wireguard_config(wg_type)

        render_vars = {
            "SERVER_HOST": SERVER_HOST,
            "PUBLIC_KEY": server_public_key,
            "CLIENT_PRIVATE_KEY": client_private_key.strip(),
            "CLIENT_PUBLIC_KEY": client_public_key.strip(),
            "CLIENT_PRESHARED_KEY": client_preshared_key.strip(),
            "CLIENT_IP": client_ip,
            "IPS": ips_content,
            **config.config,
        }

        templates_dir = os.path.join(config.WIREGUARD_DIR, "templates")
        prefix = "AZ" if wg_type == "antizapret" else "GL"

        for suffix in ["wg", "am"]:
            template_name = f"{wg_type}-client-{suffix}.conf"
            output_name = f"{prefix}-{suffix.upper()}-{current_date}.conf"
            template_path = os.path.join(templates_dir, template_name)
            if await asyncio.to_thread(os.path.exists, template_path):
                rendered_conf = await render(template_path, render_vars)
                async with aiofiles.open(os.path.join(client_dir, output_name), "w") as f:
                    await f.write(rendered_conf)

    print(f"WireGuard/AmneziaWG profile files (re)created for client '{client_name}' at {client_dir}")


async def delete_wireguard(client_name: str) -> None:
    """
    Deletes a WireGuard/AmneziaWG client.

    This function removes the client's peer configuration from the server and
    deletes the client's specific configuration files.

    Args:
        client_name: The name of the client to delete.
    """
    print(f"\nDeleting WireGuard/AmneziaWG client: {client_name}")

    client_found = False
    for wg_type in ["antizapret", "vpn"]:
        conf_path = os.path.join(config.WIREGUARD_DIR, f"{wg_type}.conf")
        if await modify_wg_config(conf_path, client_name, new_peer_block=None):
            print(f"Removed client '{client_name}' from {wg_type}.conf")
            client_found = True
            await sync_wireguard_config(wg_type)

    if not client_found:
        print(f"Failed to delete client '{client_name}'! Client not found in any config.")
        return

    client_dir = os.path.join(config.CLIENT_BASE_DIR, client_name)
    if await asyncio.to_thread(os.path.isdir, client_dir):
        for f in await asyncio.to_thread(os.listdir, client_dir):
            if f.endswith(".conf") and ("AZ-" in f or "GL-" in f):
                await asyncio.to_thread(os.remove, os.path.join(client_dir, f))
    print(f"WireGuard/AmneziaWG client '{client_name}' successfully deleted")


def get_xray_client(host: str, port: int) -> XrayClient:
    """
    Establishes a connection to the Xray API.

    Args:
        host: The hostname or IP address of the Xray API server.
        port: The port number of the Xray API server.

    Returns:
        An XrayClient instance for interacting with the API.

    Raises:
        ConnectionError: If the connection to the Xray API fails.
    """
    try:
        return XrayClient(host, port)
    except Exception as e:
        raise ConnectionError(f"Error connecting to Xray API on {host}:{port}: {e}")


async def create_table() -> None:
    """
    Creates the necessary database table for storing Xray user information.

    This function ensures that the 'users' table exists in the SQLite database,
    creating it if necessary. The table stores the mapping between user UUIDs
    and their identifiers (emails).
    """
    db_dir = os.path.dirname(config.XRAY_DB_PATH)
    if not await asyncio.to_thread(os.path.exists, db_dir):
        await asyncio.to_thread(os.makedirs, db_dir)

    async with aiosqlite.connect(config.XRAY_DB_PATH) as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS users (uuid TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_email ON users (email)")
        await conn.commit()


async def add_user_to_db(uuid: str, identifier: str) -> bool:
    """
    Adds a new user to the SQLite database.

    Args:
        uuid: The UUID of the user.
        identifier: The unique identifier for the user (e.g., email).

    Returns:
        True if the user was added successfully, False if the user already exists.
    """
    try:
        async with aiosqlite.connect(config.XRAY_DB_PATH) as conn:
            await conn.execute("INSERT INTO users (uuid, email) VALUES (?, ?)", (uuid, identifier))
            await conn.commit()
            return True
    except sqlite3.IntegrityError:
        print(f"Error: User with identifier '{identifier}' already exists.")
        return False


async def get_user_by_identifier_from_db(identifier: str) -> aiosqlite.Row | None:
    """
    Retrieves a user from the database by their identifier.

    Args:
        identifier: The identifier of the user to retrieve.

    Returns:
        An aiosqlite.Row object representing the user, or None if not found.
    """
    async with aiosqlite.connect(config.XRAY_DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM users WHERE email = ?", (identifier,)) as cursor:
            return await cursor.fetchone()


async def remove_user_from_db(email: str) -> None:
    """
    Removes a user from the SQLite database by their email.

    Args:
        email: The email of the user to remove.
    """
    async with aiosqlite.connect(config.XRAY_DB_PATH) as conn:
        await conn.execute("DELETE FROM users WHERE email = ?", (email,))
        await conn.commit()


def generate_vless_link(
    user_id: str,
    server_host: str,
    public_key: str,
    server_names: str,
    vless_port: int,
    short_id: str,
    identifier: str,
) -> str:
    """
    Generates a VLESS configuration link.

    Args:
        user_id: The user's UUID.
        server_host: The server hostname or IP address.
        public_key: The server's public key for REALITY.
        server_names: The server names for SNI.
        vless_port: The port for the VLESS service.
        short_id: The short ID for REALITY.
        identifier: A friendly name for the configuration.

    Returns:
        The generated VLESS link.
    """
    params = {
        "type": "tcp",
        "security": "reality",
        "flow": "xtls-rprx-vision",
        "fp": "chrome",
        "pbk": public_key,
        "sni": server_names,
        "sid": short_id,
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"vless://{user_id}@{server_host}:{vless_port}?{query_string}#{identifier}"


def generate_client_config(
    user_id: str, server_host: str, public_key: str, server_names: str, vless_port: int, short_id: str
) -> dict:
    """
    Generates a client-side VLESS configuration dictionary from a template.

    Args:
        user_id: The user's UUID.
        server_host: The server hostname or IP address.
        public_key: The server's public key for REALITY.
        server_names: The server names for SNI.
        vless_port: The port for the VLESS service.
        short_id: The short ID for REALITY.

    Returns:
        A dictionary representing the client's Xray configuration.
    """
    with open("config/xray_client_template.json", "r") as f:
        config_template = f.read()

    route_ips_list = []
    route_ips_file = "/root/antizapret/result/route-ips.txt"
    if os.path.exists(route_ips_file):
        with open(route_ips_file, "r") as f:
            route_ips_list = [line.strip() for line in f if line.strip()]

    config_string = config_template.format(
        dns_server=f"{config.IP}.29.12.1",
        server_host=server_host,
        vless_port=vless_port,
        user_id=user_id,
        public_key=public_key,
        server_names=server_names,
        short_id=short_id,
    )

    client_config = json.loads(config_string)
    client_config["routing"]["rules"][1]["ip"] = route_ips_list

    return client_config


async def handle_add_user(identifier: str, xray_client: XrayClient) -> None:
    """
    Handles the process of adding or recreating an Xray (VLESS) user.

    This function checks if a user already exists. If so, it removes the old
    client from Xray and cleans up old configuration files before recreating it.
    If the user is new, it generates a new UUID and adds them to the database
    and Xray.

    Args:
        identifier: The unique identifier for the user.
        xray_client: An active XrayClient instance.
    """
    user = await get_user_by_identifier_from_db(identifier)
    if user:
        user_id = user["uuid"]
        print(f"User '{identifier}' exists. Recreating Xray client and configs...")
        client_dir = os.path.join(config.CLIENT_BASE_DIR, identifier)
        if await asyncio.to_thread(os.path.isdir, client_dir):
            print(f"Cleaning up old VLESS profiles for {identifier}...")
            for f in await asyncio.to_thread(os.listdir, client_dir):
                if f.endswith(f.endswith(".json") or f.endswith(".txt")):
                    await asyncio.to_thread(os.remove, os.path.join(client_dir, f))
        await asyncio.to_thread(xray_client.remove_client, "in-vless", identifier)
    else:
        user_id = utils.generate_random_user_id()
        if not await add_user_to_db(user_id, identifier):
            return
        print(f"User '{identifier}' not found. Created new user with ID {user_id}.")

    try:
        add_client_result = await asyncio.to_thread(
            xray_client.add_client, "in-vless", user_id, identifier, flow="xtls-rprx-vision"
        )
        if not add_client_result:
            print(f"Failed to add user '{identifier}' to Xray. The user may already exist.")
            return
        print(f"User '{identifier}' successfully added to Xray.")
    except Exception as e:
        print(f"An exception occurred while adding user to Xray: {e}")
        return

    # Generate AntiZapret (AZ) JSON config
    az_server_host = config.get("SERVER_HOST")
    az_public_key = config.get("VLESS_PUBLIC_KEY")
    az_server_names = config.get("VLESS_SERVER_NAMES")
    az_short_id = config.get("VLESS_SHORT_ID")

    if all([az_server_host, az_public_key, az_server_names, az_short_id]):
        az_client_config = generate_client_config(
            user_id, az_server_host, az_public_key, az_server_names, 443, az_short_id
        )
        client_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", identifier)
        dir_path = os.path.join(config.CLIENT_BASE_DIR, client_name)
        await asyncio.to_thread(os.makedirs, dir_path, exist_ok=True)
        file_path = os.path.join(dir_path, f"AZ-XR-{datetime.now().strftime('%y-%m-%d')}.json")
        async with aiofiles.open(file_path, "w") as f:
            await f.write(json.dumps(az_client_config, indent=4))
        print(f"AZ-XR JSON config saved to: {file_path}")
    else:
        print(f"Warning: Missing AZ VLESS config in {config.SERVER_CONFIG_PATH}. Skipping AZ-XR JSON generation.")

    # Generate Global (GL) VLESS link
    gl_server_host = config.get("SERVER_HOST")
    gl_public_key = config.get("VLESS_PUBLIC_KEY")
    gl_server_names = config.get("VLESS_SERVER_NAMES")
    gl_short_id = config.get("VLESS_SHORT_ID")

    if all([gl_server_host, gl_public_key, gl_server_names, gl_short_id]):
        gl_vless_link = generate_vless_link(
            user_id, gl_server_host, gl_public_key, gl_server_names, 443, gl_short_id, "УтяVPN - Глобальный"
        )
        client_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", identifier)
        dir_path = os.path.join(config.CLIENT_BASE_DIR, client_name)
        await asyncio.to_thread(os.makedirs, dir_path, exist_ok=True)
        file_path = os.path.join(dir_path, f"GL-XR-{datetime.now().strftime('%y-%m-%d')}.txt")
        async with aiofiles.open(file_path, "w") as f:
            await f.write(gl_vless_link)
        print(f"GL-XR VLESS link saved to: {file_path}")
    else:
        print(f"Warning: Missing GL VLESS config in {config.SERVER_CONFIG_PATH}. Skipping GL-XR link generation.")


async def handle_remove_user(identifier: str, xray_client: XrayClient) -> None:
    """
    Handles the removal of an Xray (VLESS) user.

    This function removes the user from both the Xray service and the local
    database, and cleans up any associated configuration files.

    Args:
        identifier: The unique identifier for the user.
        xray_client: An active XrayClient instance.
    """
    user = await get_user_by_identifier_from_db(identifier)
    if not user:
        print(f"Error: User with identifier '{identifier}' not found.")
        return

    try:
        await asyncio.to_thread(xray_client.remove_client, "in-vless", identifier)
        print(f"User '{identifier}' removed from Xray.")
    except Exception as e:
        print(f"Warning: Could not remove user from Xray (user might not exist there): {e}")

    await remove_user_from_db(identifier)
    print(f"User '{identifier}' removed from database.")

    client_dir = os.path.join(config.CLIENT_BASE_DIR, re.sub(r"[^a-zA-Z0-9_.-]", "_", identifier))
    if await asyncio.to_thread(os.path.isdir, client_dir):
        for f in await asyncio.to_thread(os.listdir, client_dir):
            if f.endswith(".json") or f.endswith(".txt"):
                await asyncio.to_thread(os.remove, os.path.join(client_dir, f))


async def create_user(user_id: str) -> None:
    """
    Creates a new VPN user across all supported protocols.

    This function orchestrates the creation of a user for OpenVPN,
    and VLESS (Xray). It ensures that the necessary services are initialized
    and uses locks to prevent race conditions.

    Args:
        user_id: The unique identifier for the new user.
    """
    client_name = f"n{user_id}"
    print(f"--- Creating user {client_name} ---")

    async with openvpn_lock:
        await init_openvpn()
        await add_openvpn(client_name)

    async with user_locks[user_id]:
        await init_wireguard()
        await add_wireguard(client_name)

        await create_table()
        try:
            xray_client = await asyncio.to_thread(
                get_xray_client, config.XRAY_API_HOST, config.XRAY_API_PORT
            )
            await handle_add_user(client_name, xray_client)
        except ConnectionError as e:
            print(f"Could not connect to Xray, skipping VLESS user creation: {e}")

    print(f"--- User {client_name} created ---")


async def delete_user(user_id: str) -> None:
    """
    Deletes a VPN user from all supported protocols.

    This function removes the user's access and configurations for OpenVPN,
    WireGuard, and VLESS (Xray). It also cleans up the user's client directory.

    Args:
        user_id: The unique identifier of the user to delete.
    """
    client_name = f"n{user_id}"
    print(f"--- Deleting user {client_name} ---")

    async with openvpn_lock:
        await delete_openvpn(client_name)

    async with user_locks[user_id]:
        await delete_wireguard(client_name)
        try:
            xray_client = await asyncio.to_thread(
                get_xray_client, config.XRAY_API_HOST, config.XRAY_API_PORT
            )
            await handle_remove_user(client_name, xray_client)
        except ConnectionError as e:
            print(f"Could not connect to Xray, skipping VLESS user deletion: {e}")

    # Clean up the client directory if it's empty
    client_dir = os.path.join(config.CLIENT_BASE_DIR, client_name)
    if await asyncio.to_thread(os.path.isdir, client_dir) and not await asyncio.to_thread(
        os.listdir, client_dir
    ):
        print(f"Removing empty client directory: {client_dir}")
        await asyncio.to_thread(shutil.rmtree, client_dir)


async def set_server_ip_async() -> str:
    """
    Asynchronously reads the server's public IP address from the setup file.

    Returns:
        The server's IP address.

    Raises:
        RuntimeError: If the SERVER_HOST is not found in the setup file.
    """
    global SERVER_IP
    path = pathlib.Path("/root/antizapret/setup")
    async with aiofiles.open(path, encoding="utf-8") as f:
        async for line in f:
            if line.startswith("SERVER_HOST="):
                SERVER_IP = line.split("=", 1)[1].strip().strip("\"'")
                return SERVER_IP
    raise RuntimeError("SERVER_HOST not found in setup file")
