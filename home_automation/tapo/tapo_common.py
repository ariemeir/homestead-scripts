# tapo_common.py
import subprocess

def get_password_from_keychain(account: str, service: str = "tapo") -> str:
    """
    Retrieve a password from macOS Keychain using the 'security' CLI.
    This will trigger a Keychain access prompt (Touch ID or GUI prompt).
    """
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        # include stderr for diagnostics
        raise RuntimeError(
            f"Failed to get password from Keychain for account={account}, service={service}.\n"
            f"stderr: {e.stderr.strip()}"
        ) from e

    return proc.stdout.strip()

