"""Non-secret entry identity and sanitized error context for the HA layer."""

import hashlib
import logging
import traceback

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
    """Log frame locations only, without messages, source lines, locals or chains.

    logger.exception/format_exception can disclose arbitrary exception payloads
    and chained errors. Unexpected failures still need actionable stack context.
    Walk raw frames: extract_tb() also reads source files through linecache,
    blocking HA's event loop even when the source lines are never logged.
    """
    context = "\n".join(
        f"  {frame.f_code.co_filename}:{lineno} in {frame.f_code.co_name}"
        for frame, lineno in traceback.walk_tb(error.__traceback__)
    )
    logger.error("Unexpected Hoben client failure; stack locations:\n%s", context)
