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
    HobenInternalError,
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
from scripts.ha_dual_evidence import (
    FRAME_KEYS,
    TYPES,
    owner_record,
    phase,
    validate_frame,
)

_ROLE = contextvars.ContextVar("hoben_dual_role", default=None)
_installed = False
_LOGGER = logging.getLogger(__name__)


class ObservationFailed(Exception):
    def __init__(self):
        super().__init__("dual_session_observation_refused")


def category(error):
    # Unit-only framing tests intentionally do not install HA. The actual
    # worker always has it; only HA's validated scalar wrapper is consulted.
    try:
        from custom_components.hoben.safe_reports import safe_error_report
    except ModuleNotFoundError:
        safe = None
    else:
        safe = safe_error_report(error) if isinstance(error, Exception) else None
    mapped = {
        "timeout": "timeout",
        "transport_unavailable": "transport",
        "invalid_credentials": "authentication",
        "authorization_required": "authorization",
        "authentication_failed": "authentication",
        "server_closed": "closed",
        "experimental_close_client": "closed",
        "malformed_response": "protocol",
        "internal_failure": "unexpected",
        "client_closed": "closed",
    }.get((safe or {}).get("error"))
    if mapped is not None:
        return mapped
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
    if isinstance(error, HobenInternalError):
        return "unexpected"
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
        self.owners = []
        self.ordinal = None
        self.last_success = None

    def candidate(self):
        f = self.e["incident"]
        if not f or f["at_ms"] is None:
            return False
        pending = f["read_ms"] is not None and 360000 <= f["read_ms"] <= 365000
        idle = (
            f["kind"] in {"eof", "close_client"}
            and f["read_ms"] is None
            and 355000 <= f["at_ms"] <= 365000
        )
        return bool(
            f
            and f["role"] == "a"
            and f["generation"] == 1
            and f["kind"] in {"timeout", "eof", "close_client"}
            and f["subcode"] not in {2, 4, 5}
            and (pending or idle)
            and len(self.e["reads"]) >= 6
            and all(s["decoded"] for s in self.e["reads"][:6])
            and f["at_ms"] is not None
            and (f["kind"] != "timeout" or f["at_ms"] >= f["deadline_ms"])
        )

    def record(
        self,
        role,
        error,
        phase_name,
        *,
        kind=None,
        subcode=None,
        session=None,
        frame=None,
    ):
        """Record before close; only real EOF/full CloseClient have those kinds."""
        if role in self.closing or self.e["failure"] is not None:
            return
        previous = self.e["incident"]
        current = session or self.sessions.get(role)
        if previous is not None and (
            role != previous["role"]
            or current is not None
            and current.owner["generation"] != previous["generation"]
            or error != previous["category"]
        ):
            self.fail(role, error, phase_name, subcode)
            return
        if self.e["incident"] is None:
            session = session or self.sessions.get(role)
            at = self.at()
            read_ms = getattr(session, "read_ms", None)
            self.e["incident"] = dict(
                role=role,
                at_ms=at,
                category=error,
                phase=phase_name,
                subcode=subcode,
                kind=kind or error,
                frame=frame,
                late_frame=None,
                generation=session.owner["generation"] if session else 1,
                read_ms=read_ms,
                deadline_ms=read_ms + 30000
                if error == "timeout" and read_ms is not None
                else None,
            )
            if self.candidate():
                self.transition(role, "reconnecting")
        if not self.candidate():
            self.fail(role, error, phase_name, subcode)

    def refresh_resources(self, role):
        rows = [s.owner for s in self.owners if s.role == role]
        r = self.e["resources"][role]
        for key in ("opens", "close_calls"):
            r[key] = sum(o[key] for o in rows)
        r["accepted"] = any(o["accepted"] for o in rows)
        r["close_completed"] = bool(rows) and all(o["close_completed"] for o in rows)
        r["cleanup"] = bool(rows) and all(o["cleanup"] for o in rows)

    def cleanup_error(self, session, error):
        rows = self.e["cleanup_errors"]
        item = dict(
            role=session.role,
            generation=session.owner["generation"],
            at_ms=self.at(),
            category=category(error),
        )
        if not any(
            r["role"] == item["role"] and r["generation"] == item["generation"]
            for r in rows
        ):
            if len(rows) >= 3:
                self.e["overflow"] = True
            else:
                rows.append(item)
        self.fail(session.role, item["category"], "cleanup")

    def at(self):
        # Invalid observation time stops collection through guard(), but cannot
        # interrupt the real owner's close/reaping callbacks.
        try:
            return (
                None
                if self.t0 is None
                else max(0, int((self.stamp() - self.t0) * 1000))
            )
        except Exception:
            return None

    def stats(self, role):
        return self.e["phases"][phase(self.at() or 0)][role]

    def fail(self, role, error="unexpected", phase_name="unknown", subcode=None):
        if self.e["overflow"]:
            self.e["error"] = "budget"
        if self.e["failure"] is None:
            if self.e["overflow"]:
                error, subcode = "budget", None
            try:
                at = self.at()
            except Exception:
                at = None
            terminal = dict(
                role=role, at_ms=at, category=error, phase=phase_name, subcode=subcode
            )
            self.e["terminal"] = terminal
            incident = self.e["incident"]
            self.e["failure"] = (
                {k: incident[k] for k in terminal} if incident else terminal
            )
            self.e["error"] = (
                "budget" if self.e["overflow"] else self.e["failure"]["category"]
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
        session = self.sessions[role]
        if role == "a" and self.t0 is None:
            self.t0 = at
            self.e["t0_ms"] = max(0, int((at - self.start) * 1000))
        elif role == "b":
            self.e["b"]["accepted_ms"] = self.at()
        session.owner.update(accepted=True, accepted_ms=self.at())
        self.refresh_resources(role)
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
                session = self.sessions[role]
                timer = session._read_timeout
                expired = type(timer) is asyncio.Timeout and timer.expired()
                if (
                    role == "a"
                    and frame["message_type"] == "data_response_client"
                    and expired
                ):
                    # Observe the real owner's already-expired deadline. The
                    # timeout callback may precede its waiter's exception turn.
                    self.record(
                        role,
                        "timeout",
                        "request_correlation",
                        kind="timeout",
                        session=session,
                    )
                incident = self.e["incident"]
                if (
                    incident
                    and incident["kind"] == "timeout"
                    and role == "a"
                    and frame["generation"] == 1
                    and frame["message_type"] == "data_response_client"
                    and (session._rx_error is not None or expired)
                ):
                    if incident["late_frame"] is not None:
                        self.e["overflow"] = True
                        self.fail(role, "budget", "request_correlation")
                    else:
                        incident["late_frame"] = frame
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
                self.record(
                    role,
                    "protocol" if error == "none" else error,
                    frame["phase"],
                    subcode=subcode,
                    kind="close_client"
                    if subcode is not None
                    else "protocol"
                    if error == "none"
                    else error,
                    frame=frame,
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
            and client.ha_reconnect_enabled
            and client._read_timeout == 30
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
                and options.get("ha_reconnect") is True
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
            role not in tracker.closing
            and options.get("mode") is V4SessionMode.PERSISTENT
        )
        previous = tracker.sessions.get(role)
        generation = 1 if previous is None else previous.owner["generation"] + 1
        if previous is not None:
            need(
                role == "a"
                and generation == 2
                and tracker.candidate()
                and previous.cleanup_succeeded
                and previous.owner["cleanup"]
                and tracker.at() >= previous.owner["cleaned_ms"] + 60000
            )
        self.tracker, self.role = tracker, role
        self.owner = owner_record(role, generation)
        self.read_ms = None
        tracker.e["owners"].append(self.owner)
        tracker.owners.append(self)
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
            self.tracker.record(
                self.role, category(error), phase_of(error) or "opening", session=self
            )
            self.tracker.fail(self.role, category(error), phase_of(error) or "opening")
            raise
        finally:
            _ROLE.reset(token)

    async def request_v4_data(self, *, timeout=30):
        self.read_ms = self.tracker.at()
        try:
            return await super().request_v4_data(timeout=timeout)
        finally:
            self.read_ms = None

    def _signal_loss(self):
        error = self._rx_error
        if error is not None and self.role not in self.tracker.closing:
            kind = "timeout" if type(error) is HobenTimeoutError else None
            if type(error) is ExperimentalCloseClientError:
                kind = "close_client"
            try:
                self.tracker.record(
                    self.role,
                    category(error),
                    phase_of(error) or "request_correlation",
                    kind=kind,
                    session=self,
                    subcode=error.subcode
                    if type(error) is ExperimentalCloseClientError
                    else None,
                )
            except Exception:
                # The metadata tap cannot prevent the actual loss/close owner.
                self.tracker.fail(self.role, "unexpected", "unknown")
        super()._signal_loss()

    async def abort(self):
        try:
            await super().abort()
        finally:
            self.owner["cleanup"] = (
                self.cleanup_succeeded and self.owner["close_completed"]
            )
            if self.owner["cleanup"]:
                self.owner["cleaned_ms"] = self.tracker.at()
            self.tracker.refresh_resources(self.role)

    async def _receive_unproven_handoff(self, transport):
        token = _ROLE.set(self.role)
        try:
            error = await super()._receive_unproven_handoff(transport)
            if error is not None and self.role not in self.tracker.closing:
                self.tracker.record(
                    self.role,
                    category(error),
                    phase_of(error) or "unknown",
                    subcode=self.snapshot.close_client_subcode
                    if isinstance(error, ExperimentalCloseClientError)
                    else None,
                    session=self,
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
        need(self.transport.host == "myhoben.fr" and self.transport.port == 465)
        r = self.session.owner
        need(r["opens"] == 0)
        need(sum(s.owner["opens"] - s.owner["close_completed"] for s in t.owners) < 2)
        r["opens"] = 1
        r["open_ms"] = t.at()
        t.refresh_resources(role)
        # The wrapper preserves the same endpoint refusal before every TLS call.
        await self.transport.connect()

    async def read(self, max_bytes=4096, *, bounded=True):
        t, role = self.tracker, self.role
        t.guard(role)
        framer = self.session._framer
        partial = framer is not None and framer.partial
        buffered = len(framer._buffer) if framer is not None else 0
        if not self.session.owner["accepted"]:
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
                    t.record(
                        role,
                        "transport",
                        "tls_read",
                        kind="protocol" if partial else "eof",
                        session=self.session,
                    )
            else:
                t.record(role, "unexpected", "tls_read", session=self.session)
            return data
        except Exception as error:
            if isinstance(error, TransportEOF):
                t.increment(role, "eof")
            t.record(
                role,
                category(error),
                "tls_read",
                kind="eof"
                if isinstance(error, TransportEOF) and not partial
                else "unexpected",
                session=self.session,
            )
            raise

    async def write(self, data):
        t, role = self.tracker, self.role
        t.guard(role)
        need(not self.session.owner["close_completed"])
        if data == b"\x0b":
            await self.transport.write(data)  # Never suppress a Pong.
            t.increment(role, "pongs")
            if not self.session.owner["accepted"]:
                t.increment(role, "opening_pongs")
        elif data == encode_data_request_client(
            build_read_input_registers(0xFFFF, 1024, 20)
        ):
            count = sum(p[role]["requests"] for p in t.e["phases"])
            need(count < (14 if role == "a" else 1))
            t.increment(role, "requests")
            t.request_times[role].append(t.at())
            await self.transport.write(data)
        else:
            # OpenClient is emitted by the frozen shared handshake only.
            need(
                type(data) is bytes
                and data[:1] == b"\x03"
                and not self.session.owner["accepted"]
            )
            await self.transport.write(data)

    async def close(self):
        t, role = self.tracker, self.role
        r = self.session.owner
        need(r["close_calls"] == 0)
        r["close_calls"] = 1
        t.refresh_resources(role)
        try:
            await self.transport.close()
            r["close_completed"] = True
            r["closed_ms"] = t.at()
            t.refresh_resources(role)
        except (Exception, asyncio.CancelledError) as error:
            t.cleanup_error(self.session, error)
            raise
