"""Bounded HA telemetry only; never grants correlation, cleanup or admission."""

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)
CAP = 65535
_COUNTERS = (
    "unsupported_deliveries",
    "unsupported_delivery_bytes",
    "info_candidate_deliveries",
    "v4_write_attempts",
    "v4_requests",
    "v4_responses_correlated",
    "v4_responses_uncredited",
    "responses_after_drop",
    "responses_after_info_candidate",
    "pings",
    "pongs",
    "rx_timeouts",
)
_FLAGS = (
    "tls_connected",
    "v4_accepted",
    "acquisition_uncertain",
    "eof_received",
    "terminal_error",
    "transport_close_requested",
    "transport_closed",
    "transport_close_failed",
    "cleanup_requested",
    "cleanup_succeeded",
    "cleanup_failed",
    "cleanup_interrupted",
)


class SessionDiagnostics:
    """One local TLS attempt, constant space, no byte/exception/identity input.

    Counters saturate, never wrap or affect the owner. DEBUG is sampled per
    event; HA downloads a fresh closed projection, not these internal objects.
    """

    __slots__ = ("_counts", "_flags", "_generation", "_last_size", "_capped")

    def __init__(self, generation):
        self._generation = (
            generation
            if type(generation) is int and 0 < generation <= 2147483647
            else None
        )
        self._counts = dict.fromkeys(_COUNTERS, 0)
        self._flags = dict.fromkeys(_FLAGS, False)
        self._last_size = 0
        self._capped = self._generation is None

    def safe_report(self):
        return {
            "schema": 1,
            "scope": "tls_attempt",
            "tls_generation": self._generation
            if type(self._generation) is int and 0 < self._generation <= 2147483647
            else None,
            "length_scope": "tls_delivery",
            "boundary_proven": False,
            "info_framing": "INCONCLUSIVE",
            **{
                k: self._counts[k]
                if type(self._counts[k]) is int and 0 <= self._counts[k] <= CAP
                else 0
                for k in _COUNTERS
            },
            **{k: self._flags[k] is True for k in _FLAGS},
            "last_delivery_bytes": self._last_size
            if type(self._last_size) is int and 0 <= self._last_size <= 4096
            else 0,
            "counters_capped": self._capped is True,
        }

    def drop(self, size, *, info_candidate=False):
        if (
            type(size) is not int
            or not 1 <= size <= 4096
            or type(info_candidate) is not bool
        ):
            return
        self._last_size = size
        total = self._counts["unsupported_delivery_bytes"] + size
        self._capped |= total > CAP
        self._counts["unsupported_delivery_bytes"] = min(CAP, total)
        self.note("unsupported_deliveries")
        if info_candidate:
            self.note("info_candidate_deliveries")

    def correlated_response(self):
        self.note("v4_responses_correlated")
        if self._counts["unsupported_deliveries"]:
            self.note("responses_after_drop")
        if self._counts["info_candidate_deliveries"]:
            self.note("responses_after_info_candidate")

    def note(self, event):
        if type(event) is not str:
            return
        if event in _COUNTERS:
            before = self._counts[event]
            self._counts[event] = count = min(CAP, before + 1)
            if before == CAP:
                self._capped = True
                return
            sampled = count <= 4 or count & (count - 1) == 0
        elif event in _FLAGS:
            if self._flags[event]:
                return
            self._flags[event] = True
            sampled = True
        else:
            return
        if sampled:
            try:
                _LOGGER.debug(
                    "Hoben HA telemetry event=%s counters=%s", event, self.safe_report()
                )
            except (Exception, asyncio.CancelledError):
                # A diagnostic handler cannot cancel or replace the RX/cleanup.
                # Never retain its error or include free text in a second log.
                pass


def project_report(value):
    """An explicit HA export contract; future/private fields never pass silently."""
    fixed = {
        "schema": 1,
        "scope": "tls_attempt",
        "length_scope": "tls_delivery",
        "boundary_proven": False,
        "info_framing": "INCONCLUSIVE",
    }
    keys = (
        set(fixed)
        | set(_COUNTERS)
        | set(_FLAGS)
        | {"tls_generation", "last_delivery_bytes", "counters_capped"}
    )
    if type(value) is not dict or set(value) != keys:
        return None
    if any(type(value[k]) is not type(v) or value[k] != v for k, v in fixed.items()):
        return None
    if any(type(value[k]) is not int or not 0 <= value[k] <= CAP for k in _COUNTERS):
        return None
    if any(type(value[k]) is not bool for k in (*_FLAGS, "counters_capped")):
        return None
    generation = value["tls_generation"]
    if generation is not None and (
        type(generation) is not int or not 0 < generation <= 2147483647
    ):
        return None
    size = value["last_delivery_bytes"]
    if type(size) is not int or not 0 <= size <= 4096:
        return None
    return value.copy()
