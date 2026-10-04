"""HA-independent client failures with fixed text and allowlisted diagnostics."""

from .myhoben import CloseClientReason
from .profiles import StoveProfile


class HobenError(Exception):
    """Base client failure; never accept arbitrary server or identifier text."""

    code = "client_failed"

    def __init__(self) -> None:
        super().__init__(self.code)

    def safe_report(self) -> dict[str, int | str]:
        """Export a stable code suitable for diagnostics and future HA mapping."""
        return {"state": "error", "error": self.code}


class HobenInvalidInputError(HobenError, ValueError):
    """Invalid local identity/settings, rejected before any transport creation."""

    code = "invalid_client_inputs"


class HobenAuthorizationRequiredError(HobenError):
    """DeviceAuthReq was received; no pairing response was sent."""

    code = "authorization_required"


class HobenClosedError(HobenError):
    """CloseClient carries a documented reason, never its original payload."""

    code = "server_closed"

    def __init__(self, reason: CloseClientReason) -> None:
        self.reason = reason
        super().__init__()

    def safe_report(self) -> dict[str, int | str]:
        return super().safe_report() | {"reason": self.reason.value}


class HobenInvalidCredentialsError(HobenClosedError):
    """The server explicitly rejected the identifier (CloseClient 05 02)."""

    code = "invalid_credentials"


class HobenUnsupportedProfileError(HobenError):
    """A dynamically selected profile has no implemented raw refresh."""

    code = "unsupported_profile"

    def __init__(self, profile: StoveProfile) -> None:
        self.profile = profile
        super().__init__()

    def safe_report(self) -> dict[str, int | str]:
        return super().safe_report() | {"profile": self.profile.value}


class HobenProtocolError(HobenError):
    """Malformed, unsupported or uncorrelated protocol data; never retried."""

    code = "malformed_response"


class HobenAmbiguousSessionError(HobenProtocolError):
    """Unclassified OpenedClient suffix forbids identity adoption and reading."""

    code = "unclassified_opened_client_bytes"


class HobenModbusError(HobenError):
    """A correlated Modbus exception, without guessing its numeric meaning."""

    code = "modbus_exception"

    def __init__(self, exception_code: int) -> None:
        self.exception_code = exception_code
        super().__init__()

    def safe_report(self) -> dict[str, int | str]:
        return super().safe_report() | {"exception_code": self.exception_code}


class HobenTransportError(HobenError):
    """Temporary TLS/network unavailability; eligible for bounded retry."""

    code = "transport_unavailable"


class HobenTimeoutError(HobenTransportError, TimeoutError):
    """A transport or overall exchange deadline expired."""

    code = "timeout"


class HobenRefreshExhaustedError(HobenTransportError):
    """All allowed attempts failed; only count and sanitized failure are retained."""

    code = "refresh_exhausted"

    def __init__(self, attempts: int, last_error: HobenTransportError) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__()

    def safe_report(self) -> dict[str, int | str]:
        return super().safe_report() | {
            "attempts": self.attempts,
            "failure": self.last_error.code,
        }


class HobenClientClosedError(HobenError):
    """The caller closed the client; construct a new one to refresh again."""

    code = "client_closed"
