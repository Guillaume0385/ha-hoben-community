"""Process-local metadata tap for #126/032; no raw capture or second parser."""

import asyncio
import contextvars
import logging
from contextlib import contextmanager
from functools import partial

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.error_phases import phase_of
from custom_components.hoben.exceptions import (
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenInvalidCredentialsError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
)
from custom_components.hoben.modbus import build_read_input_registers
from custom_components.hoben.myhoben import encode_data_request_client
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTimeout,
)
from custom_components.hoben.v4_experiment import ExperimentalCloseClientError
from custom_components.hoben.v4_session import V4Session, V4SessionMode
from scripts.campaign_runtime_contract import need
from scripts.ha_dual_evidence import FRAME_KEYS, TYPES, phase, validate_frame

_ROLE = contextvars.ContextVar("hoben_dual_role", default=None)
_installed = False
_LOGGER = logging.getLogger(__name__)


class ObservationFailed(Exception):
    def __init__(self):
        super().__init__("dual_session_observation_refused")


def category(error):
    if isinstance(error, HobenInvalidCredentialsError):
        return "authentication"
    if isinstance(error, HobenAuthorizationRequiredError):
        return "authorization"
    if isinstance(error, (TimeoutError, TransportTimeout, HobenTimeoutError)):
        return "timeout"
    if isinstance(error, HobenClosedError):
        return "closed"
    if isinstance(error, (TransportError, HobenTransportError)):
        return "transport"
    if isinstance(error, HobenProtocolError):
        return "protocol"
    if isinstance(error, asyncio.CancelledError):
        return "closed"
    return "unexpected"


class Tracker(logging.Handler):
    """Fixed-size phase counters and the latest already-redacted B3 record."""

    def __init__(self, evidence, stamp, start, deadline):
        super().__init__(logging.DEBUG)
        self.e = evidence
        self.stamp, self.start, self.deadline = stamp, start, deadline
        self.t0 = None
        self.sessions = {}
        self.closing = set()
        self.request_times = {"a": [], "b": []}

    def at(self):
        return None if self.t0 is None else max(0, int((self.stamp() - self.t0) * 1000))

    def stats(self, role):
        return self.e["phases"][phase(self.at() or 0)][role]

    def fail(self, role, error="unexpected", phase_name="unknown", subcode=None):
        if self.e["failure"] is None:
            if self.e["overflow"]:
                error, subcode = "budget", None
            self.e["error"] = error
            try:
                at = self.at()
            except Exception:
                at = None
            self.e["failure"] = dict(
                role=role, at_ms=at, category=error, phase=phase_name, subcode=subcode
            )
            _LOGGER.warning(
                "HA dual test failure role=%s category=%s phase=%s subcode=%s",
                role,
                error,
                phase_name,
                subcode,
            )

    def increment(self, role, key, amount=1):
        s = self.stats(role)
        cap = 1048576 if key == "rx_bytes" else 4096
        if (
            s[key] + amount > cap
            or key == "rx_bytes"
            and sum(p[role][key] for p in self.e["phases"]) + amount > cap
        ):
            self.e["overflow"], self.e["error"] = True, "budget"
            return
        s[key] += amount

    def guard(self, role):
        if self.stamp() >= self.deadline:
            self.fail(role, "timeout", "unknown")
        if self.e["failure"] is not None or self.e["overflow"]:
            raise ObservationFailed()

    def transition(self, role, state):
        value = dict(role=role, at_ms=self.at() or 0, state=state)
        if len(self.e["transitions"]) >= 8:
            self.e["overflow"], self.e["error"] = True, "budget"
        else:
            self.e["transitions"].append(value)

    def accepted(self, role):
        at = self.stamp()
        self.e["resources"][role]["accepted"] = True
        if role == "a":
            need(self.t0 is None)
            self.t0 = at
            self.e["t0_ms"] = max(0, int((at - self.start) * 1000))
        else:
            self.e["b"]["accepted_ms"] = self.at()
        self.transition(role, "connected")

    def emit(self, record):
        role = _ROLE.get()
        fields = getattr(record, "hoben_frame", None)
        if role not in {"a", "b"} or type(fields) is not dict:
            return
        try:
            need(set(fields) == set(FRAME_KEYS) - {"at_ms"})
            frame = {**fields, "at_ms": self.at()}
            validate_frame(frame)
            s = self.stats(role)
            s["last_frame"] = frame
            if frame["event"] == "header":
                i = (
                    TYPES.index(frame["message_type"])
                    if frame["message_type"] in TYPES
                    else 0
                )
                if s["types"][i] == 4096:
                    self.e["overflow"], self.e["error"] = True, "budget"
                else:
                    s["types"][i] += 1
            else:
                # A valid CloseClient or a TLS/local failure is not itself an
                # invalid frame. Unknown bytes require an actually seen prefix.
                if (
                    frame["status"] == "partial"
                    and type(frame["received_bytes"]) is int
                    and frame["received_bytes"] > 0
                ):
                    self.increment(role, "truncated")
                elif (
                    frame["message_type"] == "unknown"
                    and type(frame["received_bytes"]) is int
                    and frame["received_bytes"] > 0
                ):
                    self.increment(role, "unexpected")
                elif frame["status"] == "invalid":
                    self.increment(role, "invalid")
                error = {
                    "tls_verification": "transport",
                    "unexpected_error": "unexpected",
                    "modbus_exception": "protocol",
                }.get(frame["category"], frame["category"])
                subcode = None
                if (
                    frame["message_type"] == "close_client"
                    and frame["status"] == "complete"
                    and error == "closed"
                    and frame["received_bytes"] == 2
                ):
                    # The existing RX owner set this scalar before emitting B3.
                    # A prefix/header alone cannot attest a CloseClient subcode.
                    subcode = self.sessions[role].snapshot.close_client_subcode
                    need(type(subcode) is int and 0 <= subcode <= 255)
                self.fail(
                    role,
                    "protocol" if error == "none" else error,
                    frame["phase"],
                    subcode,
                )
        except Exception:
            self.fail(role, "unexpected", "unknown")

    @contextmanager
    def install(self, client):
        global _installed
        need(
            not _installed
            and client._lifecycle is None
            and client._max_attempts == 1
            and not client.ha_reconnect_enabled
        )
        original = v4_lifecycle.V4Lifecycle
        logger = logging.getLogger("custom_components.hoben.frame_diagnostic")
        level = logger.level

        def factory(**options):
            need(
                client._lifecycle is None
                and client._active_operation is asyncio.current_task()
            )
            supplied = options["session_factory"]
            need(
                type(supplied) is partial
                and supplied.func is V4Session
                and not supplied.args
                and set(supplied.keywords) == {"transport_factory"}
                and options.get("ha_reconnect") is False
            )
            options["session_factory"] = partial(
                TrackedSession, tracker=self, role="a", **supplied.keywords
            )
            return original(**options)

        _installed = True
        v4_lifecycle.V4Lifecycle = factory
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self)
        try:
            yield self
        finally:
            logger.removeHandler(self)
            logger.setLevel(level)
            v4_lifecycle.V4Lifecycle = original
            _installed = False


class TrackedSession(V4Session):
    """Shared session implementation; add metadata without changing routing."""

    def __init__(self, *, tracker, role, transport_factory, **options):
        need(
            role not in tracker.sessions
            and options.get("mode") is V4SessionMode.PERSISTENT
        )
        self.tracker, self.role = tracker, role
        tracker.sessions[role] = self
        super().__init__(
            transport_factory=lambda: TrackedTransport(
                transport_factory(), self, tracker, role
            ),
            **options,
        )

    async def connect(self):
        token = _ROLE.set(self.role)
        try:
            await super().connect()
            self.tracker.accepted(self.role)
        except (Exception, asyncio.CancelledError) as error:
            self.tracker.fail(self.role, category(error), phase_of(error) or "opening")
            raise
        finally:
            _ROLE.reset(token)

    async def _receive_unproven_handoff(self, transport):
        token = _ROLE.set(self.role)
        try:
            error = await super()._receive_unproven_handoff(transport)
            if error is not None and self.role not in self.tracker.closing:
                self.tracker.fail(
                    self.role,
                    category(error),
                    phase_of(error) or "unknown",
                    self.snapshot.close_client_subcode
                    if isinstance(error, ExperimentalCloseClientError)
                    else None,
                )
            return error
        finally:
            _ROLE.reset(token)


class TrackedTransport:
    """Transparent TLS delegate; only counts delivery sizes, never keeps bytes."""

    def __init__(self, transport, session, tracker, role):
        self.transport, self.session, self.tracker, self.role = (
            transport,
            session,
            tracker,
            role,
        )

    async def connect(self):
        t, role = self.tracker, self.role
        t.guard(role)
        r = t.e["resources"][role]
        need(r["opens"] == 0)
        r["opens"] = 1
        await self.transport.connect()

    async def read(self, max_bytes=4096, *, bounded=True):
        t, role = self.tracker, self.role
        t.guard(role)
        framer = self.session._framer
        partial = framer is not None and framer.partial
        buffered = len(framer._buffer) if framer is not None else 0
        if not t.e["resources"][role]["accepted"]:
            buffered = max(buffered, len(self.session._opening_buffer))
        if buffered > 4096:
            t.e["overflow"], t.e["error"] = True, "budget"
            t.guard(role)
        s = t.stats(role)
        s["buffered_max"] = max(s["buffered_max"], buffered)
        try:
            data = await self.transport.read(max_bytes, bounded=bounded)
            if type(data) is bytes:
                t.increment(role, "rx_chunks")
                t.increment(role, "rx_bytes", len(data))
                if data and partial:
                    t.increment(role, "fragments")
                if not data:
                    t.increment(role, "eof")
                    t.fail(role, "transport", "tls_read")
            else:
                t.fail(role, "unexpected", "tls_read")
            return data
        except Exception as error:
            if isinstance(error, TransportEOF):
                t.increment(role, "eof")
            t.fail(role, category(error), "tls_read")
            raise

    async def write(self, data):
        t, role = self.tracker, self.role
        t.guard(role)
        need(not t.e["resources"][role]["close_completed"])
        if data == b"\x0b":
            await self.transport.write(data)  # Never suppress a Pong.
            t.increment(role, "pongs")
            if not t.e["resources"][role]["accepted"]:
                t.increment(role, "opening_pongs")
        elif data == encode_data_request_client(
            build_read_input_registers(0xFFFF, 1024, 20)
        ):
            count = sum(p[role]["requests"] for p in t.e["phases"])
            need(count < (12 if role == "a" else 1))
            t.increment(role, "requests")
            t.request_times[role].append(t.at())
            await self.transport.write(data)
        else:
            # OpenClient is emitted by the frozen shared handshake only.
            need(
                type(data) is bytes
                and data[:1] == b"\x03"
                and not t.e["resources"][role]["accepted"]
            )
            await self.transport.write(data)

    async def close(self):
        t, role = self.tracker, self.role
        r = t.e["resources"][role]
        need(r["close_calls"] == 0)
        r["close_calls"] = 1
        try:
            await self.transport.close()
            r["close_completed"] = True
        except (Exception, asyncio.CancelledError) as error:
            t.fail(role, category(error), "cleanup")
            raise
