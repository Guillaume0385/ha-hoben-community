"""Scalar-only observations at the real framer, never a second RX/parser.

Counts belong to one logical frame's examined prefix/body, not a TLS delivery.
Unexamined tails cannot be attributed to a message with an unknown boundary.
"""

import logging
from dataclasses import dataclass, replace

from .error_phases import PHASES, phase_of
from .exceptions import (
    HobenClosedError,
    HobenInternalError,
    HobenModbusError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTlsVerificationError,
    HobenTransportError,
)
from .malformed import TEXT_FIELDS, message_name
from .transport import TransportCertificateError, TransportError, TransportTimeout

_LOGGER = logging.getLogger(__name__)


def _number(value, maximum):
    return type(value) is int and 0 <= value <= maximum


@dataclass(frozen=True, slots=True)
class FrameEvidence:
    """No bytes, identity, exchange, exception or traceback may enter this value."""

    generation: int | None = None
    message_type: str = "unknown"
    received_bytes: int | str = "unknown"
    expected_total_bytes: int | str = "unknown"
    length_scope: str = "unproven"
    provenance: str = "unproven"

    def emit(self, event, *, category="none", phase="frame_boundary", status=None):
        """Revalidate every scalar before both structured and rendered output."""
        fields = {
            "event": event
            if type(event) is str and event in {"header", "error"}
            else "error",
            "generation": self.generation
            if _number(self.generation, 2147483647) and self.generation > 0
            else "unknown",
            "message_type": self.message_type
            if type(self.message_type) is str
            and self.message_type in TEXT_FIELDS["message_type"]
            else "unknown",
            "expected_total_bytes": self.expected_total_bytes
            if _number(self.expected_total_bytes, 265) and self.expected_total_bytes > 0
            else "unknown",
            "received_bytes": self.received_bytes
            if _number(self.received_bytes, 4096)
            else "unknown",
            "length_scope": self.length_scope
            if type(self.length_scope) is str
            and self.length_scope in {"frame", "post_open_hypothesis"}
            else "unproven",
            "provenance": self.provenance
            if type(self.provenance) is str
            and self.provenance in {"validated_header", "fixed_contract"}
            else "unproven",
            "phase": phase if type(phase) is str and phase in PHASES else "unknown",
            "category": category
            if type(category) is str
            and category
            in {
                "none",
                "protocol",
                "transport",
                "timeout",
                "tls_verification",
                "closed",
                "modbus_exception",
                "unexpected_error",
            }
            else "unexpected_error",
        }
        expected = fields["expected_total_bytes"]
        message = fields["message_type"]
        proven = (
            fields["provenance"] == "fixed_contract"
            and (
                (
                    message == "ping"
                    and expected == 1
                    and fields["length_scope"] == "frame"
                )
                or (
                    message == "close_client"
                    and expected == 2
                    and fields["length_scope"] == "post_open_hypothesis"
                )
            )
        ) or (
            fields["provenance"] == "validated_header"
            and fields["length_scope"] == "frame"
            and type(expected) is int
            and (
                (
                    message in {"data_response_client", "data_response_server"}
                    and 9 <= expected <= 261
                )
                or (message == "data_updated" and 13 <= expected <= 265)
            )
        )
        if not proven:
            fields.update(
                expected_total_bytes="unknown",
                length_scope="unproven",
                provenance="unproven",
            )
        if status is None:
            status = (
                "unknown"
                if fields["expected_total_bytes"] == "unknown"
                else "complete"
                if fields["received_bytes"] == fields["expected_total_bytes"]
                else "partial"
            )
        fields["status"] = (
            status
            if type(status) is str
            and status in {"complete", "partial", "invalid", "unknown"}
            else "unknown"
        )
        try:
            _LOGGER.log(
                logging.DEBUG if fields["event"] == "header" else logging.WARNING,
                "Hoben V4 frame event=%s generation=%s message_type=%s "
                "expected_total_bytes=%s received_bytes=%s length_scope=%s "
                "provenance=%s phase=%s category=%s status=%s",
                *fields.values(),
                extra={"hoben_frame": fields.copy()},
            )
        except Exception:
            pass  # A broken logging handler must not change protocol/retry policy.

    def failure(self, error, *, phase="frame_boundary", status=None):
        category = "unexpected_error"
        if isinstance(error, HobenInternalError):
            pass
        elif isinstance(error, HobenModbusError):
            category = "modbus_exception"
        elif isinstance(error, HobenProtocolError):
            category = "protocol"
        elif isinstance(error, (TransportCertificateError, HobenTlsVerificationError)):
            category = "tls_verification"
        elif isinstance(error, (TransportTimeout, HobenTimeoutError)):
            category = "timeout"
        elif isinstance(error, (TransportError, HobenTransportError)):
            category = "transport"
        elif isinstance(error, HobenClosedError):
            category = "closed"
        self.emit(
            "error", category=category, phase=phase_of(error) or phase, status=status
        )


class FrameDiagnostic:
    """Constant space: current frame only, once per header/failure, no RX copy."""

    def __init__(self):
        self.generation = None
        self.clear()

    def clear(self):
        self.evidence = FrameEvidence(generation=self.generation)
        self.header_logged = self.failed = False
        self.failure_phase = "frame_boundary"

    def start(self, discriminator):
        self.clear()
        self.evidence = replace(
            self.evidence, message_type=message_name(discriminator), received_bytes=0
        )

    def received(self):
        self.evidence = replace(
            self.evidence, received_bytes=self.evidence.received_bytes + 1
        )

    def header(self, expected="unknown", *, provenance="unproven", scope="unproven"):
        if not self.header_logged:
            self.evidence = replace(
                self.evidence,
                expected_total_bytes=expected,
                provenance=provenance,
                length_scope=scope,
            )
            self.evidence.emit("header")
            self.header_logged = True

    def finish(self):
        evidence = self.evidence
        self.clear()
        return evidence

    def failure(self, error, *, phase=None, status=None):
        if not self.failed:
            self.evidence.failure(
                error, phase=phase or self.failure_phase, status=status
            )
            self.failed = True
