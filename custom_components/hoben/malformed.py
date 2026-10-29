"""Closed, scalar diagnostics at a protocol rejection; never retain RX data.

Lengths describe the stated local scope, never a TLS read as a wire boundary.
In particular an OpenedClient prefix establishes no complete-message length.
"""

from dataclasses import dataclass

TEXT_FIELDS = {
    "phase": frozenset(
        {
            "unknown",
            "opening",
            "frame_boundary",
            "message_classification",
            "request_correlation",
            "response_validation",
        }
    ),
    "message_type": frozenset(
        {
            "unknown",
            "opened_client",
            "close_client",
            "ping",
            "data_response_client",
            "data_response_server",
            "data_updated",
            "device_auth_req",
        }
    ),
    "length_scope": frozenset({"not_proven", "opening_buffer", "frame", "mbap_header"}),
    "missing_fields": frozenset(
        {
            "unknown",
            "none",
            "message_type",
            "mbap_header",
            "message_body",
            "close_subcode",
        }
    ),
    "rejection": frozenset(
        {
            "unknown",
            "invalid_opening",
            "unknown_type",
            "invalid_mbap",
            "incomplete_frame",
            "uncorrelated_response",
            "invalid_response",
            "contract_error",
        }
    ),
    "received_length": frozenset({"not_proven"}),
    "expected_length": frozenset({"not_proven"}),
}
NUMBER_FIELDS = {"received_length": 4096, "expected_length": 4096}
_TYPES = {
    4: "opened_client",
    5: "close_client",
    7: "data_response_server",
    10: "ping",
    14: "data_response_client",
    27: "data_updated",
    47: "device_auth_req",
}


def message_name(discriminator: int | None) -> str:
    """Publish only a documented name, never an unknown discriminator value."""
    return _TYPES.get(discriminator, "unknown")


def observed_length(data: bytes | bytearray) -> int | str:
    """A value outside the publication bound is unknown, never a clamped count."""
    return len(data) if len(data) <= 4096 else "not_proven"


def response_diagnostic(frame: object, phase: str) -> "MalformedDiagnostic":
    """Derive lengths only from a validated MBAP contract at this rejection."""
    from .modbus import modbus_tcp_frame_size

    received = "not_proven"
    expected = "not_proven"
    name = "unknown"
    missing = "unknown"
    if type(frame) is bytes:
        received = observed_length(frame)
        name = message_name(frame[0] if frame else None)
        if frame[:1] == b"\x0e":
            missing = "mbap_header" if len(frame) < 7 else "none"
            if len(frame) >= 7:
                try:
                    expected = 1 + modbus_tcp_frame_size(frame[1:7])
                    if len(frame) < expected:
                        missing = "message_body"
                except ValueError:
                    pass
    return MalformedDiagnostic(
        phase=phase,
        message_type=name,
        received_length=received,
        expected_length=expected,
        length_scope="frame",
        missing_fields=missing,
        rejection="uncorrelated_response"
        if phase == "request_correlation"
        else "invalid_response",
    )


@dataclass(frozen=True, slots=True)
class MalformedDiagnostic:
    """Constant-space, validated evidence; unknown facts stay explicitly unknown."""

    phase: str = "unknown"
    message_type: str = "unknown"
    received_length: int | str = "not_proven"
    expected_length: int | str = "not_proven"
    length_scope: str = "not_proven"
    missing_fields: str = "unknown"
    rejection: str = "unknown"

    def __post_init__(self) -> None:
        for key, allowed in TEXT_FIELDS.items():
            value = getattr(self, key)
            if type(value) is str and value in allowed:
                continue
            if key in NUMBER_FIELDS and type(value) is int and 0 <= value <= 4096:
                continue
            raise ValueError("invalid_malformed_diagnostic")

    def safe_report(self) -> dict[str, int | str]:
        """Copy only the closed schema; no objects, payloads or exception text."""
        self.__post_init__()  # Revalidate at every public/logging boundary too.
        return {key: getattr(self, key) for key in TEXT_FIELDS}
