"""Dedicated D7 passive TLS observer; no CLI, retries or HA activation.

One actual plaintext delivery may be discarded by the existing private B
capability. Subsequent reads are parked, never scanned/reframed. With today's
evidence the observation ends INCONCLUSIVE after cleanup, not SUCCESS.
"""

import asyncio
import math
import ssl
import time

from custom_components.hoben.myhoben import encode_open_client
from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportCertificateError,
    TransportError,
)
from custom_components.hoben.v4_session import (
    SessionState,
    V4Session,
    V4SessionMode,
    _InfoDeliveryDropExperiment,
)
from scripts.info_delivery_memory import READ_ONLY_V4
from scripts.info_delivery_scenario import error_category
from scripts.info_delivery_tls_adapter import (
    CleanupWitnessPort,
    PlaintextDeliveryPort,
    V4OwnerPort,
)
from scripts.info_manual_contract import LIMITS, OBSERVATION, need, validate_observation


class PassiveTlsPort(
    AsyncTlsTransport, PlaintextDeliveryPort, V4OwnerPort, CleanupWitnessPort
):
    """Actual read owner + scalar witness, implementing D6's delivery ports.

    No fixture layout declarations are accepted. Certificates, hostname and
    the original SDK close Future are inspected, not supplied by a report.
    """

    def __init__(self, *, clock=time.monotonic):
        super().__init__()
        self.clock = clock
        self.session = None
        self.origin = self.end = None
        self.candidate = asyncio.Event()
        self.facts = dict(OBSERVATION)
        self._factory_calls = self._close_calls = self._writes = 0
        self._active_read = self._active_write = 0
        self._close_future = None
        self._original_writer = None

    def bind(self, session, origin):
        need(self.session is None and type(session) is V4Session)
        need(session.mode is V4SessionMode.PERSISTENT)
        need(session.state is SessionState.DISCONNECTED)
        need(session._transport_factory == self.factory)
        self.session, self.origin = session, origin
        self.end = origin + LIMITS["observation_ms"] / 1000

    def factory(self):
        need(self._factory_calls == 0)
        self._factory_calls += 1
        return self

    def elapsed(self):
        value = self.clock() - self.origin
        need(math.isfinite(value) and 0 <= value * 1000 <= LIMITS["total_ms"])
        return int(value * 1000)

    async def connect(self):
        need(self._factory_calls == 1 and self.facts["connections"] == 0)
        need(self.host == "myhoben.fr" and self.port == 465)
        self.facts["connections"] = 1
        await super().connect()
        self._original_writer = writer = self._writer
        tls = writer.get_extra_info("ssl_object")
        if not (
            isinstance(tls, ssl.SSLObject | ssl.SSLSocket)
            and tls.context.verify_mode == ssl.CERT_REQUIRED
            and tls.context.check_hostname is True
            and tls.server_hostname == "myhoben.fr"
            and tls.version() in {"TLSv1.2", "TLSv1.3"}
            and tls.getpeercert()
        ):
            raise TransportCertificateError("verification_unproven")
        protocol = getattr(writer, "_protocol", None)
        if isinstance(protocol, asyncio.StreamReaderProtocol):
            self._close_future = asyncio.StreamReaderProtocol._get_close_waiter(
                protocol, writer
            )
        self.facts["tls_verified"] = True

    def delivered(self, data):
        """Only called directly by read(), with the actual returned object."""
        s, f = self.session, self.facts
        need(asyncio.current_task() is s._rx_task and s._transport is self)
        need(type(data) is bytes and 1 <= len(data) <= 4096)
        need(f["deliveries"] < 8192 and f["received_bytes"] + len(data) <= 1048576)
        f["deliveries"] += 1
        f["received_bytes"] += len(data)
        # This proves only a candidate at the start of a post-open delivery.
        # No suffix scan, subcode, frame length or declared fixture layout.
        if (
            data[:1] == b"\x0c"
            and self.clock() < self.end
            and s.state is SessionState.CONNECTED
            and not s._framer.partial
            and s._framer._tail is None
            and not s._data_updated.active
            and s._rx_error is None
        ):
            need(not f["candidate_observed"])
            f["candidate_observed"] = True
            f["candidate_delivery_bytes"] = len(data)
            f["candidate_at_ms"] = self.elapsed()
            self.candidate.set()

    async def read(self, max_bytes=4096, *, bounded=True):
        need(self._active_read == 0)
        self._active_read += 1
        try:
            if self.candidate.is_set():
                # Cancellation by the same session's cleanup is the only exit.
                # No second transport read can consume a candidate's suffix.
                await asyncio.Future()
            if not bounded:
                if (
                    self.facts["deliveries"] >= 8192
                    or self.facts["received_bytes"] >= 1048576
                ):
                    if self.facts["first_error"] == "none":
                        self.facts["first_error"] = "budget"
                    raise TransportError("delivery_budget")
                max_bytes = min(max_bytes, 1048576 - self.facts["received_bytes"])
            data = await super().read(max_bytes, bounded=bounded)
            if not bounded:
                if self.clock() >= self.end:
                    # A late delivery is not an observation in the window and
                    # cannot be fed to the private drop/continuation path.
                    await asyncio.Future()
                self.delivered(data)
            return data
        finally:
            self._active_read -= 1

    def allow_v4_read(self):
        # New owner decision allows observation without an unsafe continuation.
        return False

    async def write(self, data):
        need(type(data) is bytes and self._active_write == 0)
        s = self.session
        opening = self._writes == 0 and data == encode_open_client(
            s._user_guid,
            s._opening_options.build,
            s._device_guid,
            s._opening_options.device_info,
        )
        need(opening or data in (b"\x0b", READ_ONLY_V4))
        need(not self.candidate.is_set() or data != READ_ONLY_V4)
        need(self._writes < 8192)
        self._writes += 1
        self._active_write += 1
        if data == b"\x0b":
            self.facts["pings_validated"] += 1
        elif data == READ_ONLY_V4:
            self.facts["read_requests"] += 1
        try:
            await super().write(data)
            if data == b"\x0b":
                self.facts["pongs_written"] += 1
        finally:
            self._active_write -= 1

    async def close(self):
        self._close_calls += 1
        self.facts["transport_close_requested"] = True
        if self.facts["first_error"] == "none" and self._reader is not None:
            if self._reader.exception() is not None:
                self.facts["first_error"] = "transport"
            elif self._reader.at_eof():
                self.facts["first_error"] = "closed"
        first = self._close_calls == 1 and self._writer is self._original_writer
        first = first and self._writer is not None
        await super().close()
        future = self._close_future
        # A repeat close, detached writer, abort or is_closing alone cannot
        # attest cleanup. Require the original SDK callback Future as well.
        if (
            first
            and isinstance(future, asyncio.Future)
            and future.done()
            and not future.cancelled()
            and future.exception() is None
        ):
            self.facts["transport_close_completed"] = True

    def finish(self, worker_report=None):
        s, f = self.session, self.facts
        if f["first_error"] == "none" and s._rx_error is not None:
            f["first_error"] = error_category(s._rx_error)
        f["verified_reads"] = s.verified_read_sequence
        f["discarded_deliveries"] = s._info_delivery_drop._count
        f["rx_stopped"] = s._rx_task is not None and s._rx_task.done()
        f["operations_stopped"] = (
            not s._operations
            and not s._tx_operations
            and self._active_read == self._active_write == 0
            and s._opening_task is None
        )
        f["cleanup_attested"] = bool(
            f["cleanup_error"] == "none"
            and s.cleanup_succeeded
            and s.state is SessionState.CLOSED
            and f["transport_close_completed"]
            and f["rx_stopped"]
            and f["operations_stopped"]
            and self._factory_calls == 1
        )
        f["elapsed_ms"] = self.elapsed()
        return validate_observation(f)


def make_session(user, device, port):
    need(type(port) is PassiveTlsPort)
    return V4Session(
        user_guid=user,
        device_guid=device,
        transport_factory=port.factory,
        mode=V4SessionMode.PERSISTENT,
        recover_data_updated=True,
        classify_frame_boundary=True,
        _info_delivery_drop=_InfoDeliveryDropExperiment(limit=1),
    )


async def observe(session, port, *, origin, clock=time.monotonic, stop=None):
    """One session, no resynchronization/request/reconnect after opaque Info.

    stop is a private OS signal event, never a caller-provided live option.
    Every helper is cancelled/reaped. Repeated cancellation cannot reset the
    immutable deadline or cancel a cleanup that is already in progress.
    """
    need(type(session) is V4Session and type(port) is PassiveTlsPort)
    port.bind(session, origin)
    f = port.facts
    f["started"] = True
    end = origin + LIMITS["observation_ms"] / 1000
    cancelled = False

    async def work():
        waiters = []

        def fail(category):
            if f["first_error"] == "none":
                f["first_error"] = category

        try:
            remaining = end - clock()
            need(remaining > 0)
            async with asyncio.timeout(min(30, remaining)):
                await session.connect()
            f["opening_accepted"] = bool(session.snapshot.opening is not None)
            waiters = [
                asyncio.create_task(port.candidate.wait()),
                asyncio.create_task(asyncio.sleep(max(0, end - clock()))),
            ]
            if stop is not None:
                waiters.append(asyncio.create_task(stop.wait()))
            await asyncio.wait(
                [*waiters, session._rx_task], return_when=asyncio.FIRST_COMPLETED
            )
            if clock() >= end:
                f["observation_complete"] = True
            if session._rx_task.done():
                if session._rx_error is not None:
                    fail(error_category(session._rx_error))
                else:
                    fail("closed")
            elif not port.candidate.is_set() and clock() < end:
                fail("cancelled")
        except asyncio.CancelledError:
            fail("cancelled")
        except Exception as error:
            fail(error_category(error))
        finally:
            for task in waiters:
                task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            f["cleanup_started_ms"] = port.elapsed()
            try:
                remaining = origin + LIMITS["total_ms"] / 1000 - clock()
                async with asyncio.timeout(max(0, min(50, remaining - 5))):
                    await session.abort()
            except (Exception, asyncio.CancelledError):
                f["cleanup_error"] = "cleanup"

    task = asyncio.create_task(work(), name="hoben-info-passive-worker")
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not cancelled:
                cancelled = True
                task.cancel()
    await task
    return port.finish()
