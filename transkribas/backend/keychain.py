"""macOS Keychain integration for secure secret storage.

Stores API keys in the system keychain instead of plain-text SQLite.
Falls back to DB storage on non-macOS systems.
"""

import logging
import platform
import subprocess

logger = logging.getLogger(__name__)

SERVICE_NAME = "com.diko.app"


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def set_secret(key: str, value: str) -> bool:
    """Store a secret in macOS Keychain. Returns True on success."""
    if not _is_macos() or not value:
        return False
    try:
        # Delete existing entry first (ignore errors)
        subprocess.run(
            ["security", "delete-generic-password",
             "-s", SERVICE_NAME, "-a", key],
            capture_output=True,
        )
        # Add new entry
        result = subprocess.run(
            ["security", "add-generic-password",
             "-s", SERVICE_NAME, "-a", key,
             "-w", value,
             "-U"],  # update if exists
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info(f"Secret '{key}' stored in Keychain")
            return True
        logger.warning(
            f"Keychain store failed: {result.stderr.decode()}"
        )
        return False
    except Exception as e:
        logger.warning(f"Keychain unavailable: {e}")
        return False


def get_secret(key: str) -> str | None:
    """Retrieve a secret from macOS Keychain. Returns None if not found."""
    if not _is_macos():
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", SERVICE_NAME, "-a", key, "-w"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def delete_secret(key: str) -> bool:
    """Remove a secret from macOS Keychain."""
    if not _is_macos():
        return False
    try:
        result = subprocess.run(
            ["security", "delete-generic-password",
             "-s", SERVICE_NAME, "-a", key],
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def migrate_from_db(db_value: str, key: str = "openrouter_api_key") -> bool:
    """Migrate a plain-text key from DB to Keychain.

    Returns True if migration succeeded and DB value should be cleared.
    """
    if not db_value or db_value.startswith("keychain:"):
        return False

    if set_secret(key, db_value):
        logger.info(
            f"Migrated '{key}' from DB to Keychain"
        )
        return True
    return False
