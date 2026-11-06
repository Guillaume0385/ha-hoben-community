"""Bounded close telemetry only: never grants cleanup or retry permission."""

import asyncio
import contextvars
import logging
import math
import ssl
from contextlib import contextmanager

_LOGGER = logging.getLogger(__name__)
_GENERATION = contextvars.ContextVar("hoben_close_generation", default="unknown")
_OPERATIONS = {"writer_close", "wait_closed", "abort", "reap"}
_RESULTS = {
    "returned",
    "raised_connection",
    "raised_tls",
    "raised_other",
    "timeout",
    "cancelled",
    "not_confirmed",
}
_SOURCES = {"operation", "callback", "owner"}


def result(error):
    """Types only; never retain an exception, its text, cause or arguments."""
    if error is None:
        return "returned"
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ssl.SSLError):
        return "raised_tls"
    if isinstance(error, ConnectionError):
        return "raised_connection"
    return "raised_other"


@contextmanager
def close_generation(framer):
    """Use the existing lifecycle/B3 generation, with no synthetic identifier."""
    try:
        value = framer.frame_log.generation
    except (Exception, asyncio.CancelledError):
        value = None
    if type(value) is not int or not 1 <= value <= 2147483647:
        value = "unknown"
    token = _GENERATION.set(value)
    try:
        yield
    finally:
        _GENERATION.reset(token)


class CloseTrace:
    """One constant-space record; inspecting a witness never consumes its error.

    The temporary SDK callback tap forwards the original call unmodified and is
    removed in finish(). A callback captured before installation may bypass it;
    not_observed means exactly that, never that connection_lost did not occur.
    Unknown/older stream implementations expose no invented Future state.
    """

    def __init__(self, writer, timeout):
        self.clock = asyncio.get_running_loop().time
        self.start = self.clock()
        self.cap_ms = math.ceil(min(timeout, 60) * 1000)
        self.generation = _GENERATION.get()
        self.events = []
        self.serial = 0
        self.first = self.secondary = None
        self.callback = "not_observed"
        self.callback_result = None
        self.invalid = self.truncated = False
        self.finished = False
        self.future = self.protocol = self.original = self.tap = None
        try:
            protocol = getattr(writer, "_protocol", None)
            if isinstance(protocol, asyncio.StreamReaderProtocol):
                self.future = asyncio.StreamReaderProtocol._get_close_waiter(
                    protocol, writer
                )
                self.protocol, self.original = protocol, protocol.connection_lost
                self.had_override = "connection_lost" in vars(protocol)

                def connection_lost(error):
                    self.callback = "observed"
                    self.callback_result = result(error)
                    try:
                        return self.original(error)
                    finally:
                        self.record("wait_closed", "not_confirmed", source="callback")

                self.tap = connection_lost
                protocol.connection_lost = connection_lost
        except (Exception, asyncio.CancelledError):
            self.invalid = True

    def future_state(self):
        future = self.future
        if not isinstance(future, asyncio.Future):
            return "unknown"
        if future.cancelled():
            return "cancelled"
        if not future.done():
            return "pending"
        # exception() would mark a not-yet-consumed exception as retrieved.
        return "completed_error" if future._exception is not None else "completed_ok"

    def elapsed(self):
        return max(0, int((self.clock() - self.start) * 1000))

    def record(self, operation, outcome, *, source="operation", failed=False):
        try:
            if self.finished:
                return
            if (
                type(operation) is not str
                or operation not in _OPERATIONS
                or type(outcome) is not str
                or outcome not in _RESULTS
                or type(source) is not str
                or source not in _SOURCES
            ):
                self.invalid = True
                return
            self.serial = min(65535, self.serial + 1)
            event = dict(
                operation=operation,
                result=outcome,
                source=source,
                order=self.serial,
                at_ms=min(self.cap_ms, self.elapsed()),
                future=self.future_state(),
                connection_lost=self.callback,
            )
            if len(self.events) < 12:
                self.events.append(event)
            else:
                self.truncated = True
            if failed:
                if self.first is None:
                    self.first = event.copy()
                elif self.secondary is None:
                    self.secondary = event.copy()
        except (Exception, asyncio.CancelledError):
            self.invalid = True

    @contextmanager
    def operation(self, name):
        self.record(name, "not_confirmed")
        try:
            yield
        except BaseException as error:
            self.record(name, result(error), failed=True)
            raise
        else:
            self.record(name, "returned")

    def owner_failure(self, error):
        # A deadline/caller cancellation can interrupt the shield while its
        # child is still pending. Record it before the later reap cancellation.
        if self.first is None:
            self.record("wait_closed", result(error), source="owner", failed=True)

    def finish(self):
        try:
            if self.finished:
                return
            self.finished = True
            if self.protocol is not None and self.protocol.connection_lost is self.tap:
                if self.had_override:
                    self.protocol.connection_lost = self.original
                else:
                    del self.protocol.connection_lost
            elapsed = self.elapsed()
            snapshot = dict(
                schema=1,
                generation=self.generation,
                events=list(self.events),
                first_failure=self.first,
                secondary_failure=self.secondary,
                future=self.future_state(),
                connection_lost=self.callback,
                callback_result=self.callback_result,
                elapsed_ms=min(self.cap_ms, elapsed),
                duration_capped=elapsed > self.cap_ms,
                truncated=self.truncated,
                invalid=self.invalid,
            )
            _LOGGER.log(
                logging.WARNING if self.first else logging.DEBUG,
                "Hoben TLS close diagnostic=%s",
                snapshot,
                extra={"hoben_tls_close": snapshot},
            )
        except (Exception, asyncio.CancelledError):
            pass  # A diagnostic handler cannot change the real close outcome.
