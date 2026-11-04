"""Passive process-local HA-F1 tap. No parsing, policy, I/O or retry ownership."""

import asyncio
import contextvars
import copy
import logging
import math
from contextlib import contextmanager
from functools import partial, wraps

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.error_phases import PHASES, phase_of
from custom_components.hoben.exceptions import (
    HobenClosedError,
    HobenInternalError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTlsVerificationError,
    HobenTransportError,
)
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTimeout,
    TransportTlsError,
)
from custom_components.hoben.v4_experiment import ExperimentalCloseClientError
from scripts.ha_incident_evidence import CATEGORIES, SOURCES, STAGES

_OWNER = contextvars.ContextVar("ha_f1_owner", default=None)


def metadata(method):
    """A broken tap invalidates its report, never the real owner's operation."""

    @wraps(method)
    def observe(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except (Exception, asyncio.CancelledError):
            self.invalid = True

    return observe


ALIASES = {
    "timeout": "timeout",
    "transport_unavailable": "transport",
    "invalid_credentials": "authentication",
    "authorization_required": "authorization",
    "server_closed": "closed",
    "experimental_close_client": "close_client",
    "malformed_response": "protocol",
    "internal_failure": "internal",
    "tls_verification_failed": "tls",
    "cleanup_failed": "cleanup_failed",
    "client_closed": "closed",
    "session_lifecycle_stopped": "cancelled",
    "session_lifecycle_exhausted": "exhausted",
    "modbus_exception": "protocol",
    "data_updated_recovery": "protocol",
}


def category(error):
    mapped = ALIASES.get(getattr(error, "code", None))
    if mapped is not None:
        return mapped
    for types, name in (
        ((asyncio.CancelledError,), "cancelled"),
        ((TransportEOF,), "eof"),
        ((TimeoutError, TransportTimeout, HobenTimeoutError), "timeout"),
        ((ExperimentalCloseClientError,), "close_client"),
        ((TransportTlsError, HobenTlsVerificationError), "tls"),
        ((TransportError, HobenTransportError), "transport"),
        ((HobenInternalError,), "internal"),
        ((HobenProtocolError,), "protocol"),
        ((HobenClosedError,), "closed"),
    ):
        if isinstance(error, types):
            return name
    return ALIASES.get(getattr(error, "code", None), "internal")


class Recorder(logging.Handler):
    """Three owners maximum; fixed scalar projection, no error/data retention."""

    def __init__(self, clock, *, start=None):
        super().__init__(logging.WARNING)
        self.clock, self.start = clock, clock() if start is None else start
        self.rows, self.sessions = [], []
        self.first = self.terminal = self.cleanup = None
        self.invalid = False

    def at(self):
        try:
            value = self.clock() - self.start
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value <= 900
            ):
                raise ValueError
            return int(value * 1000)
        except Exception:
            self.invalid = True
            return 0

    def row(self, session):
        return next(
            (r for s, r in zip(self.sessions, self.rows, strict=True) if s is session),
            None,
        )

    def register(self, session, role):
        if len(self.rows) >= 3:
            self.invalid = True
            return
        row = dict(
            role=role,
            generation=1 + sum(r["role"] == role for r in self.rows),
            accepted=False,
            accepted_generation=None,
            close_client_subcode=None,
            close=[None] * 4,
            stage="active",
            pending=0,
            last_read=None,
        )
        self.sessions.append(session)
        self.rows.append(row)

    @metadata
    def event(
        self,
        session,
        name,
        phase,
        source,
        subcode=None,
        *,
        cleanup=False,
        terminal=False,
    ):
        if type(name) is not str or name not in CATEGORIES:
            name, self.invalid = "internal", True
        if type(phase) is not str or phase not in PHASES:
            phase, self.invalid = "unknown", True
        if type(source) is not str or source not in SOURCES:
            source, self.invalid = "observer", True
        if subcode is not None and (
            name != "close_client"
            or type(subcode) is not int
            or not 0 <= subcode <= 255
        ):
            subcode, self.invalid = None, True
        row = self.row(session)
        event = [
            row["role"] if row else "a",
            row["generation"] if row else None,
            self.at(),
            name,
            phase,
            source,
            subcode,
        ]
        if self.first is None:
            self.first = event.copy()
        if cleanup and self.cleanup is None:
            self.cleanup = event.copy()
        if terminal and self.terminal is None:
            self.terminal = event.copy()

    @metadata
    def error(self, session, error, phase, source, *, cleanup=False):
        row = self.row(session)
        if (
            isinstance(error, asyncio.CancelledError)
            and not cleanup
            and row is not None
            and row["close"][0] is not None
        ):
            return  # Intentional RX/TX stop is not a peer incident.
        name = category(error)
        if name == "eof" and source != "transport_read":
            name = "transport"
        self.event(
            session,
            name,
            phase_of(error) or phase,
            source,
            error.subcode if type(error) is ExperimentalCloseClientError else None,
            cleanup=cleanup,
        )

    @metadata
    def stage(self, session, stage):
        row = self.row(session)
        if row is None:
            return
        if row["close"][0] is None:
            row["close"][0] = self.at()
        if STAGES.index(stage) > STAGES.index(row["stage"]):
            row["stage"] = stage

    @metadata
    def resources(self, session):
        row = self.row(session)
        if row is None:
            return

        def pending(task):
            return task is not None and not task.done()

        bits = [
            pending(session._rx_task),
            bool(session._tx_operations),
            session._pending_read is not None,
            session._transport is not None,
            pending(session._data_updated.task),
            pending(session._opening_task),
            bool(session._operations),
        ]
        row["pending"] = sum(int(value) << index for index, value in enumerate(bits))
        row["close_client_subcode"] = (
            session.snapshot.close_client_subcode
            if session.close_client_received
            else None
        )
        if (
            session.cleanup_succeeded
            and row["close"][2] is not None
            and row["pending"] == 0
        ):
            # Read the real owner's proof; detachment or a second close is insufficient.
            row["close"][3] = (
                row["close"][3] if row["close"][3] is not None else self.at()
            )
            row["stage"] = "reaped"

    @metadata
    def read(self, session):
        row = self.row(session)
        sequence = session.verified_read_sequence
        if (
            row is not None
            and row["accepted"]
            and type(sequence) is int
            and sequence > 0
        ):
            row["last_read"] = [sequence, self.at(), 0]

    @metadata
    def emit(self, record):
        session = _OWNER.get()
        if self.row(session) is None:
            return
        f = getattr(record, "hoben_frame", None)
        if type(f) is not dict or f.get("event") != "error":
            return
        names = {
            "protocol": "protocol",
            "transport": "transport",
            "timeout": "timeout",
            "tls_verification": "tls",
            "closed": "closed",
            "modbus_exception": "protocol",
            "unexpected_error": "internal",
        }
        name = names.get(f.get("category"), "internal")
        subcode = None
        if (
            f.get("message_type") == "close_client"
            and f.get("status") == "complete"
            and f.get("received_bytes") == 2
            and f.get("expected_total_bytes") == 2
            and name == "closed"
        ):
            name, subcode = "close_client", session.snapshot.close_client_subcode
        self.event(session, name, f.get("phase", "unknown"), "session", subcode)

    def snapshot(self):
        for session, row in zip(self.sessions, self.rows, strict=True):
            if row["stage"] == "construction_failed":
                continue  # No constructed owner: resources are unknown, never clean.
            self.resources(session)
            if (
                not session.cleanup_succeeded
                and row["close"][0] is not None
                and self.cleanup is None
            ):
                self.event(
                    session, "cleanup_failed", "cleanup", "session", cleanup=True
                )
        end = self.at()
        for row in self.rows:
            if row["last_read"] is not None:
                row["last_read"][2] = end - row["last_read"][1]
        return copy.deepcopy(
            dict(
                end_ms=end,
                first=self.first,
                terminal=self.terminal,
                cleanup=self.cleanup,
                owners=self.rows,
                invalid=self.invalid,
            )
        )

    @contextmanager
    def closes(self, client):
        original = client.async_close

        async def close(*args, **kwargs):
            try:
                return await original(*args, **kwargs)
            except (Exception, asyncio.CancelledError) as error:
                session = self.sessions[-1] if self.sessions else None
                # Record the actual observer close failure even when its caller
                # catches it; do not infer it from an eventual worker close.
                clean = all(
                    s.cleanup_succeeded
                    for s, r in zip(self.sessions, self.rows, strict=True)
                    if r["stage"] != "construction_failed"
                )
                self.error(
                    session,
                    error,
                    "cleanup",
                    "observer",
                    cleanup=not (isinstance(error, asyncio.CancelledError) and clean),
                )
                self.event(
                    session, category(error), "cleanup", "observer", terminal=True
                )
                raise

        client.async_close = close
        try:
            yield
        finally:
            if client.async_close is close:
                client.async_close = original

    @contextmanager
    def refreshes(self, coordinator):
        from custom_components.hoben.coordinator import HobenCoordinatorData

        original = coordinator.async_refresh

        async def refresh(*args, **kwargs):
            before = coordinator.data
            try:
                return await original(*args, **kwargs)
            finally:
                o = coordinator.client.session_observation
                session = next(
                    (
                        s
                        for s, r in zip(self.sessions, self.rows, strict=True)
                        if r["role"] == "a"
                        and r["accepted_generation"] == o.read_generation
                    ),
                    None,
                )
                if (
                    coordinator.last_update_success
                    and type(coordinator.data) is HobenCoordinatorData
                    and coordinator.data is not before
                    and session is not None
                ):
                    self.read(session)
                elif not coordinator.last_update_success and self.first is None:
                    from custom_components.hoben.safe_reports import safe_error_report

                    report = safe_error_report(coordinator.last_exception) or {}
                    self.event(
                        session,
                        ALIASES.get(report.get("error"), "internal"),
                        report.get("phase", "unknown"),
                        "observer",
                    )

        coordinator.async_refresh = refresh
        try:
            yield
        finally:
            coordinator.async_refresh = original

    @contextmanager
    def logs(self):
        logger = logging.getLogger("custom_components.hoben.frame_diagnostic")
        logger.addHandler(self)
        try:
            yield
        finally:
            logger.removeHandler(self)

    @contextmanager
    def install(self, coordinator):
        original = v4_lifecycle.V4Lifecycle

        def factory(**options):
            supplied = options["session_factory"]
            session_type = type("F1Session", (SessionMetadata, supplied.func), {})
            options["session_factory"] = partial(
                session_type, diagnostics=self, diagnostic_role="a", **supplied.keywords
            )
            previous = options.get("_status_callback")
            owner = [None]

            def status(event):
                if previous is not None:
                    previous(event)
                life = owner[0]
                if (
                    event.kind == "ended"
                    and life is not None
                    and not life._stopping
                    and life._failure is not None
                ):
                    session = self.sessions[-1] if self.sessions else None
                    error = life._failure
                    self.event(
                        session,
                        ALIASES.get(error.code, category(error)),
                        phase_of(error)
                        or (
                            "post_open"
                            if type(error) is ExperimentalCloseClientError
                            else "unknown"
                        ),
                        "session",
                        error.subcode
                        if type(error) is ExperimentalCloseClientError
                        else None,
                        terminal=True,
                    )

            options["_status_callback"] = status
            result = original(**options)
            owner[0] = result
            return result

        v4_lifecycle.V4Lifecycle = factory
        try:
            with (
                self.logs(),
                self.refreshes(coordinator),
                self.closes(coordinator.client),
            ):
                yield
        finally:
            v4_lifecycle.V4Lifecycle = original


class SessionMetadata:
    """Mixin around the original owner; calls each original operation once."""

    def __init__(self, *, diagnostics, diagnostic_role, transport_factory, **options):
        self.diagnostics = diagnostics
        diagnostics.register(self, diagnostic_role)
        try:
            super().__init__(
                transport_factory=lambda: TransportMetadata(transport_factory(), self),
                **options,
            )
        except (Exception, asyncio.CancelledError) as error:
            row = diagnostics.row(self)
            if row is not None:
                row.update(stage="construction_failed", pending=None)
            diagnostics.error(self, error, "opening", "session")
            raise

    async def connect(self):
        token = _OWNER.set(self)
        try:
            result = await super().connect()
            row = self.diagnostics.row(self)
            if row is not None:
                row["accepted"] = True
                row["accepted_generation"] = sum(
                    r["accepted"]
                    for r in self.diagnostics.rows
                    if r["role"] == row["role"]
                )
            return result
        except (Exception, asyncio.CancelledError) as error:
            self.diagnostics.error(self, error, "opening", "session")
            raise
        finally:
            _OWNER.reset(token)

    def _signal_loss(self):
        if self._rx_error is not None:
            task = asyncio.current_task()
            row = self.diagnostics.row(self)
            if (
                task.cancelling()
                and task is not self._rx_task
                and row is not None
                and row["close"][0] is None
            ):
                self.diagnostics.event(
                    self, "cancelled", "request_correlation", "session"
                )
            else:
                self.diagnostics.error(
                    self,
                    self._rx_error,
                    "post_open"
                    if type(self._rx_error) is ExperimentalCloseClientError
                    else "request_correlation",
                    "session",
                )
        super()._signal_loss()

    async def request_v4_data(self, **options):
        result = await super().request_v4_data(**options)
        row = self.diagnostics.row(self)
        if row is not None and row["role"] == "b":
            self.diagnostics.read(self)
        return result

    async def _stop_operations(self):
        self.diagnostics.stage(self, "stop_operations")
        return await super()._stop_operations()

    async def _close(self):
        self.diagnostics.stage(self, "session_close")
        return await super()._close()

    async def _release_transport(self):
        self.diagnostics.stage(self, "transport_release")
        return await super()._release_transport()

    async def abort(self):
        try:
            return await super().abort()
        except asyncio.CancelledError:
            # A cancelled observer can receive cancellation after resources
            # finished closing. Only the real close error or missing final
            # cleanup proof establishes a cleanup failure in the report.
            raise
        except Exception as error:
            self.diagnostics.error(self, error, "cleanup", "session", cleanup=True)
            raise
        finally:
            self.diagnostics.resources(self)


class TransportMetadata:
    """Byte-transparent delegate. No buffer, payload, exception or identity saved."""

    def __init__(self, transport, session):
        self.transport, self.session = transport, session

    def __getattr__(self, name):
        return getattr(self.transport, name)

    async def connect(self):
        try:
            return await self.transport.connect()
        except (Exception, asyncio.CancelledError) as error:
            self.session.diagnostics.error(
                self.session, error, "opening", "transport_connect"
            )
            raise

    async def read(self, *args, **kwargs):
        try:
            return await self.transport.read(*args, **kwargs)
        except Exception as error:
            self.session.diagnostics.error(
                self.session, error, "tls_read", "transport_read"
            )
            raise

    async def write(self, data):
        try:
            return await self.transport.write(data)
        except (Exception, asyncio.CancelledError) as error:
            self.session.diagnostics.error(
                self.session, error, "request_correlation", "transport_write"
            )
            raise

    async def close(self):
        d, session = self.session.diagnostics, self.session
        d.stage(session, "tls_close")
        row = d.row(session)
        if row is not None:
            row["close"][1] = d.at()
        try:
            result = await self.transport.close()
            if row is not None:
                row["close"][2] = d.at()
            d.stage(session, "tls_closed")
            return result
        except (Exception, asyncio.CancelledError) as error:
            d.error(session, error, "cleanup", "transport_close", cleanup=True)
            raise
