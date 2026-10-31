"""Non-secret entry identity and sanitized error context for the HA layer."""

import hashlib
import logging

from .error_phases import phase_of
from .myhoben import normalize_user_guid


def user_guid_fingerprint(user_guid: str) -> str:
    """Hash the normalized 128-bit identity with a fixed domain prefix.

    Use the full SHA-256 digest, without truncation/collision shortcuts. Neither
    the config-entry unique ID nor the device identifier exposes either GUID.
    Normalization stays owned by the existing protocol helper.
    """
    normalized = normalize_user_guid(user_guid)
    return hashlib.sha256(f"hoben:user_guid:{normalized}".encode("ascii")).hexdigest()


def log_unexpected_error(logger: logging.Logger, error: Exception) -> None:
    """Fixed category/phase only: no private paths, traceback traversal or I/O."""
    logger.error(
        "Unexpected Hoben client failure [error=unexpected_error, phase=%s]",
        phase_of(error) or "unknown",
    )
