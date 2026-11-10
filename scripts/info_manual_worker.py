"""D8 manual-only bounded TLS delivery observer; no invented Info framing.

The existing private drop owns the first admissible 0x0C-leading delivery.
After that drop the SAME session RX task only counts future plaintext TLS
deliveries: not a single byte returns to V4Session's framer. A serialized,
fixed diagnostic read can still be emitted every 30 seconds. No fixed-FFFF
reply can prove freshness/correlation after an unanswered read, so no functional
recovery is claimed from opaque deliveries.
"""

import asyncio
import copy
import math
import ssl
import time

from custom_components.hoben.myhoben import encode_open_client
from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportCertificateError,
    TransportEOF,
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
        self.facts = copy.deepcopy(OBSERVATION)
        self._factory_calls = self._close_calls = self._writes = 0
        self._active_read = self._active_write = 0
        self._close_future = None
        self._original_writer = None
        self._probe_authorized = False
        self._segment = None

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

    def _segment_end(self, kind):
        """Close a scalar observation interval, NEVER an Info frame length."""
        segment = self._segment
        if segment is None:
            return
        f = self.facts
        entry = {
            "start_at_ms": segment[0],
            "observed_bytes_between_candidates": segment[1],
            "tls_deliveries": segment[2],
            "end_kind": kind,
        }
        if len(f["candidate_segments"]) < 16:
            f["candidate_segments"].append(entry)
        else:
            f["candidate_segments_omitted"] += 1
        self._segment = None

    def delivered(self, data):
        """Observe only the return of a genuine read by the sole session RX task."""
        s, f = self.session, self.facts
        need(asyncio.current_task() is s._rx_task and s._transport is self)
        need(type(data) is bytes and 1 <= len(data) <= 4096)
        need(f["deliveries"] < 8192 and f["received_bytes"] + len(data) <= 1048576)
        f["deliveries"] += 1
        f["received_bytes"] += len(data)
        at = self.elapsed()
        if f["candidate_observed"]:
            f["post_candidate_reads"] += 1
            f["tls_deliveries_since_candidate"] += 1
            f["tls_bytes_since_candidate"] += len(data)
            if len(f["delivery_timeline"]) < 96:
                f["delivery_timeline"].append([at, len(data)])
            else:
                f["delivery_timeline_omitted"] += 1
            # These are leading bytes of TLS deliveries, NOT message headers.
            # No scanning of the payload for look-alike discriminants.
            if data[:1] == b"\x0c":
                f["candidate_leads_unproven"] += 1
                self._segment_end("delivery_lead_unproven")
                self._segment = [at, 0, 0]
            elif data[:1] == b"\x0a":
                f["ping_leads_unproven"] += 1
            elif data[:1] == b"\x0e":
                f["response_leads_unproven"] += 1
            elif data[:1] == b"\x1b":
                f["data_updated_leads_unproven"] += 1
            self._segment[1] += len(data)
            self._segment[2] += 1
            return
        # Before the first candidate only: this is a clean-framer, post-open
        # delivery lead with a known offset 0, not a proven Info frame.
        if (
            data[:1] == b"\x0c"
            and self.clock() < self.end
            and s.state is SessionState.CONNECTED
            and not s._framer.partial
            and s._framer._tail is None
            and not s._data_updated.active
            and s._rx_error is None
        ):
            f["candidate_observed"] = True
            f["candidate_delivery_offset"] = 0
            f["candidate_delivery_bytes"] = len(data)
            f["candidate_at_ms"] = at
            f["tls_deliveries_since_candidate"] = 1
            f["tls_bytes_since_candidate"] = len(data)
            f["delivery_timeline"].append([at, len(data)])
            self._segment = [at, len(data), 1]
            self.candidate.set()

    async def read(self, max_bytes=4096, *, bounded=True):
        need(self._active_read == 0)
        # This read invocation starts AFTER the first delivery returned to
        # V4Session and its private drop consumed it. Opaque data must never be
        # returned to its framer. No second reader, byte scan or guessed skip.
        opaque = self.candidate.is_set() and not bounded
        self._active_read += 1
        try:
            while True:
                if not bounded:
                    if self.clock() >= self.end:
                        await asyncio.Future()  # Cleanup cancels this sole RX.
                    if (
                        self.facts["deliveries"] >= 8192
                        or self.facts["received_bytes"] >= 1048576
                    ):
                        if self.facts["first_error"] == "none":
                            self.facts["first_error"] = "budget"
                        raise TransportError("delivery_budget")
                    max_bytes = min(max_bytes, 1048576 - self.facts["received_bytes"])
                try:
                    data = await super().read(max_bytes, bounded=bounded)
                except TransportEOF:
                    # A real TLS peer EOF is not a local close nor silent idle.
                    self.facts["peer_eof"] = True
                    raise
                if not bounded:
                    if self.clock() >= self.end:
                        await asyncio.Future()
                    self.delivered(data)
                    if opaque:
                        continue
                return data
        finally:
            self._active_read -= 1

    def allow_v4_read(self):
        # No V4Session request waiter may be attached to opaque deliveries.
        return False

    async def send_diagnostic_v4(self):
        """Only a fixed read packet; serialize with all session TX operations."""
        s = self.session
        need(self.candidate.is_set() and s._transport is self)
        async with s._tx_lock:
            need(
                s.state is SessionState.CONNECTED
                and s._rx_error is None
                and self._close_calls == 0
                and self._active_write == 0
            )
            self._probe_authorized = True
            try:
                await self.write(READ_ONLY_V4)
            finally:
                self._probe_authorized = False

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
        need(data != READ_ONLY_V4 or not self.candidate.is_set() or self._probe_authorized)
        need(self._writes < 8192)
        self._writes += 1
        self._active_write += 1
        if data == b"\x0b":
            self.facts["pings_validated"] += 1
        try:
            await super().write(data)
            if data == b"\x0b":
                self.facts["pongs_written"] += 1
            elif data == READ_ONLY_V4:
                self.facts["read_requests"] += 1
                if self._probe_authorized:
                    self.facts["unconfirmed_read_requests"] += 1
        finally:
            self._active_write -= 1

    async def close(self):
        self._close_calls += 1
        self.facts["transport_close_requested"] = True
        if self.facts["first_error"] == "none" and not self.facts["peer_eof"] and self._reader is not None:
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
        self._segment_end("tls_eof" if f["peer_eof"] else "observation_end")
        if f["first_error"] == "none" and s._rx_error is not None and not f["peer_eof"]:
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
    """One V4 opening and one RX owner; never parse an opaque continuation.

    All V4 diagnostic TX follow the original 30-second monotonic cadence and
    cannot turn a late fixed-FFFF response into correlated V4 proof. An external
    process guardian owns the unchanged absolute 3600-second OS deadline.
    """
    need(type(session) is V4Session and type(port) is PassiveTlsPort)
    port.bind(session, origin)
    f = port.facts
    f["started"] = True
    end = origin + LIMITS["observation_ms"] / 1000
    cancelled = False

    async def probe_loop():
        next_at = clock() + 30.0
        while clock() < end:
            await asyncio.sleep(max(0, next_at - clock()))
            if clock() >= end or session._rx_task.done():
                return
            await port.send_diagnostic_v4()
            # Never burst missed intervals or exceed one write at a time.
            next_at = max(next_at + 30.0, clock() + 30.0)

    async def work():
        waiters = set()
        probe = None

        def fail(category):
            if f["first_error"] == "none":
                f["first_error"] = category

        try:
            remaining = end - clock()
            need(remaining > 0)
            async with asyncio.timeout(min(30, remaining)):
                await session.connect()
            f["opening_accepted"] = bool(session.snapshot.opening is not None)
            candidate_wait = asyncio.create_task(port.candidate.wait())
            end_wait = asyncio.create_task(asyncio.sleep(max(0, end - clock())))
            stop_wait = asyncio.create_task(stop.wait()) if stop is not None else None
            waiters.update((candidate_wait, end_wait))
            if stop_wait is not None:
                waiters.add(stop_wait)
            while True:
                watched = {session._rx_task, end_wait}
                if not port.candidate.is_set():
                    watched.add(candidate_wait)
                if stop_wait is not None:
                    watched.add(stop_wait)
                if probe is not None:
                    watched.add(probe)
                done, _ = await asyncio.wait(
                    watched, return_when=asyncio.FIRST_COMPLETED
                )
                if session._rx_task in done:
                    if port.facts["peer_eof"]:
                        break
                    fail(
                        error_category(session._rx_error)
                        if session._rx_error is not None
                        else "closed"
                    )
                    break
                if end_wait in done or clock() >= end:
                    f["observation_complete"] = True
                    break
                if stop_wait is not None and stop_wait in done:
                    fail("cancelled")
                    break
                if candidate_wait in done and probe is None:
                    # The only parse attempt is the pre-existing first delivery
                    # drop. All subsequent reads are private, length-only.
                    probe = asyncio.create_task(probe_loop(), name="hoben-info-v4-probe")
                    waiters.add(probe)
                if probe is not None and probe in done:
                    try:
                        probe.result()
                    except Exception as error:
                        fail(error_category(error))
                    break
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

    task = asyncio.create_task(work(), name="hoben-info-continuous-worker")
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not cancelled:
                cancelled = True
                task.cancel()
    await task
    return port.finish()
