"""Validate public support fields at the HA error/diagnostics boundary.

This module is consumed only by HA adapters. Protocol/client models still own
their HA-independent safe_report() API. Both error mapping and diagnostics use
this one allowlist: no text parsing, exception-chain traversal or raw export.
"""

from collections.abc import Mapping

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .client import HobenClient, RawStoveSnapshot
from .exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationCodeError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenClosedError,
    HobenError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenRefreshExhaustedError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .myhoben import CloseClientReason
from .profiles import StoveProfile

PROFILES = frozenset(profile.value for profile in StoveProfile)
_ERROR_CODES = frozenset(
    error_type.code
    for error_type in (
        HobenError,
        HobenInvalidInputError,
        HobenAuthorizationRequiredError,
        HobenAuthorizationCodeError,
        HobenClosedError,
        HobenInvalidCredentialsError,
        HobenUnsupportedProfileError,
        HobenProtocolError,
        HobenAmbiguousSessionError,
        HobenModbusError,
        HobenTransportError,
        HobenTimeoutError,
        HobenRefreshExhaustedError,
        HobenClientClosedError,
    )
)
_HA_ERROR_CODES = frozenset(
    {"authentication_failed", "update_failed", "config_entry_error", "unexpected_error"}
)
_ERROR_TEXT_FIELDS = {
    "error": _ERROR_CODES,
    "reason": frozenset(reason.value for reason in CloseClientReason),
    "profile": PROFILES,
    "failure": _ERROR_CODES,
}
_ERROR_NUMBER_FIELDS = {"exception_code": 255, "attempts": 2}
_WRAPPED_ERROR_TEXT_FIELDS = _ERROR_TEXT_FIELDS | {
    "error": _ERROR_CODES | _HA_ERROR_CODES
}


def _select_fields(
    report: object,
    text_fields: Mapping[str, frozenset[str]],
    number_fields: Mapping[str, int] | None = None,
    boolean_fields: tuple[str, ...] = (),
) -> dict[str, str | int | bool]:
    """Copy approved keys and exact primitive values; never coerce input."""
    if type(report) is not dict:
        return {}
    result: dict[str, str | int | bool] = {}
    for field, allowed in text_fields.items():
        value = report.get(field)
        if type(value) is str and value in allowed:
            result[field] = value
    for field, maximum in (number_fields or {}).items():
        value = report.get(field)
        if type(value) is int and 0 <= value <= maximum:
            result[field] = value
    for field in boolean_fields:
        value = report.get(field)
        if type(value) is bool:
            result[field] = value
    return result


def select_report(
    model: HobenClient | RawStoveSnapshot | HobenError,
    text_fields: Mapping[str, frozenset[str]],
    number_fields: Mapping[str, int] | None = None,
    boolean_fields: tuple[str, ...] = (),
) -> dict[str, str | int | bool]:
    """Fail closed on broken contracts; copy no objects or raised exceptions."""
    try:
        report = model.safe_report()
    except Exception:
        return {}
    return _select_fields(report, text_fields, number_fields, boolean_fields)


def safe_error_report(error: Exception | None) -> dict[str, str | int | bool] | None:
    """Read typed metadata only; unannotated HA errors retain fixed fallbacks.

    A HA wrapper carries a copied primitive report, never the source exception.
    Revalidate it at export as well, so mutation/extensions cannot widen the
    public surface. Do not inspect args, text, traceback, cause or context.
    """
    if error is None:
        return None
    if isinstance(error, HobenError):
        report = select_report(error, _ERROR_TEXT_FIELDS, _ERROR_NUMBER_FIELDS)
        if "error" in report:
            return report
    elif isinstance(error, (ConfigEntryAuthFailed, UpdateFailed, ConfigEntryError)):
        try:
            metadata = getattr(error, "_hoben_safe_report", None)
        except Exception:
            metadata = None
        report = _select_fields(
            metadata,
            _WRAPPED_ERROR_TEXT_FIELDS,
            _ERROR_NUMBER_FIELDS,
        )
        if "error" in report:
            return report
        if isinstance(error, ConfigEntryAuthFailed):
            return {"error": "authentication_failed"}
        if isinstance(error, UpdateFailed):
            return {"error": "update_failed"}
        return {"error": "config_entry_error"}
    return {"error": "unexpected_error"}


def wrap_error[ErrorT: Exception](
    error_type: type[ErrorT], message: str, source: Exception
) -> ErrorT:
    """Keep HA's existing class/logging lifecycle and attach only safe scalars.

    The message prefix is a fixed caller-owned string. The suffix uses the same
    validated keys/values as diagnostics; HA still decides when to log it. No
    additional logger, raw exception retention or failure history is introduced.
    """
    report = safe_error_report(source)
    assert report is not None
    suffix = ", ".join(f"{key}={value}" for key, value in report.items())
    error = error_type(f"{message} [{suffix}]")
    error._hoben_safe_report = report
    return error
