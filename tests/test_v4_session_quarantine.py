"""L4: real shared session, synthetic TLS/clock only; no recovery consumer."""

import ast
import asyncio
import inspect
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from custom_components.hoben.exceptions import (
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTimeoutError,
)
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_eof_quarantine import Reason, State
from custom_components.hoben.v4_experiment import Session300, SessionReconnect
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import (
    DelimitedV4Message,
    SessionState,
    SessionStateError,
    V4Session,
    _QuarantineCapability,
    _QuarantinedRead,
    _QuarantineOrigin,
)
from tests.test_session_300_runtime import Stream, response
from tests.test_session_no_pong import until


class QuarantineStream(Stream):
    def __init__(self):
        super().__init__()
        self.owners = set()
        self.write_started = asyncio.Event()
        self.release_write = asyncio.Event()
        self.block_write = False

    async def read(self, max_bytes=4096, *, bounded=True):
        if not bounded:
            self.owners.add(asyncio.current_task())
        return await super().read(max_bytes, bounded=bounded)

    async def write(self, payload):
        if self.block_write and payload[0] == 13:
            self.active_tx += 1
            try:
                self.writes.append(payload)
                self.write_started.set()
                await self.release_write.wait()
            finally:
                self.active_tx -= 1
        else:
            await super().write(payload)


def owners(now):
    clock = lambda: now[0]  # noqa: E731
    return SessionReconnect(clock=clock), NoPongAfter120(clock=clock)


def capability(budget, pong, **changes):
    return _QuarantineCapability(
        budget,
        pong,
        **(
            {
                "observation_deadline_ms": 600000,
                "process_deadline_ms": 610000,
                "suite_deadline_ms": 1030000,
            }
            | changes
        ),
    )


async def connected(*, enabled=True, suppress=True, deadline=None):
    now = [10]
    budget, pong = owners(now)
    stream = QuarantineStream()
    cap = (
        capability(
            budget, pong, **({"observation_deadline_ms": deadline} if deadline else {})
        )
        if enabled
        else None
    )
    session = V4Session(
        user_guid="b" * 32,
        transport_factory=lambda: stream,
        session_300=budget,
        no_pong_after_120=pong,
        _quarantine=cap,
    )
    await session.connect()
    await stream.started.wait()
    if suppress:
        now[0] = 130
        stream.queue.put_nowait(b"\x0a")
        await until(lambda: pong.suppressed == 1)
    now[0] = 131
    return session, stream, budget, pong, now


async def enter(session, stream, data=b"\x05"):
    stream.queue.put_nowait(data)
    await until(lambda: session.state is SessionState.QUARANTINED)
    assert session._quarantine_latched and not session._experiment.usable
    assert not session._loss_event.is_set() and not session.loss_is_retryable
    assert stream.close_count == 0 and stream.active_reads == 1
    assert not session._tx_lock.locked()


async def stopped(session):
    with pytest.raises(HobenProtocolError):
        await session.wait_rx_stopped()
    assert not session.loss_is_retryable


async def cleanup(session, stream):
    await session.abort()
    await session.close()
    await session.abort()
    assert stream.close_count == 1
    assert stream.active_reads == stream.active_tx == 0
    assert not session._operations and not session._tx_operations
    assert not session._tx_lock.locked() and session._pending_read is None
    assert session._read_timeout is None and session._rx_task.done()
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


@pytest.mark.parametrize("rejection", [b"\x05", b"\x05\x7f\x0a" + response()])
@pytest.mark.parametrize("eof", [b"", TransportEOF("synthetic-private")])
def test_real_rx_passively_discards_suffixes_and_counts_eof_once(rejection, eof):
    async def scenario():
        s, stream, budget, pong, now = await connected()
        await enter(s, stream, rejection)
        assert budget.rx_bytes == 48 + 1 + len(rejection)
        assert not s._framer.partial and not s._opening_buffer
        reads, pings, responses = budget.requests, budget.pings, budget.responses
        now[0] = 132
        stream.queue.put_nowait(b"\x0a" + response() + b"\x05")
        await until(lambda: budget.rx_chunks == 4)
        assert (budget.requests, budget.pings, budget.responses) == (
            reads,
            pings,
            responses,
        )
        assert budget.rx_bytes == 48 + 1 + len(rejection) + 52
        now[0] = 140
        stream.queue.put_nowait(eof)
        await stopped(s)
        result = s._quarantine_observation
        assert result.state is State.EOF_CANDIDATE
        assert result.reason is Reason.EOF_CANDIDATE
        assert result.origin is _QuarantineOrigin.TRANSPORT_READ
        assert result.generation == 1 and result.at_ms == 140000
        assert all(
            v is None or type(v) in (int, str, State, Reason, _QuarantineOrigin)
            for v in asdict(result).values()
        )
        with pytest.raises(FrozenInstanceError):
            result.at_ms = 0
        assert pong.peer_eofs == pong.peer_eofs_after_suppression == 1
        assert stream.owners == {s._rx_task}
        assert budget.opens == 1 and s._loss_event.is_set()
        assert all(p[0] == 3 for p in stream.writes)
        assert "synthetic-private" not in repr(result) + repr(s)
        with pytest.raises(SessionStateError):
            await s.connect()  # No new opening on this latched session.
        await cleanup(s, stream)
        assert pong.peer_eofs == 1  # Cleanup did not manufacture another EOF.

    asyncio.run(scenario())


def test_pending_read_signal_disposes_timeout_and_observer_cannot_cancel_rx():
    async def scenario():
        s, stream, budget, pong, now = await connected()
        read = asyncio.create_task(s.request_v4_data())
        await until(lambda: budget.requests == 1 and not s._tx_in_flight)
        owner = s._rx_task
        await enter(s, stream)
        with pytest.raises(_QuarantinedRead):
            await read
        assert s._pending_read is s._read_timeout is None
        assert budget.requests == 1 and budget.responses == 0
        assert not s._operations and not s._tx_operations
        observer = asyncio.create_task(s.wait_rx_stopped())
        await asyncio.sleep(0)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert not owner.done() and stream.active_reads == 1
        loss = asyncio.create_task(s.wait_lost())
        await asyncio.sleep(0)
        assert not loss.done()
        loss.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loss
        with pytest.raises(_QuarantinedRead):
            await s.request_v4_data()
        with pytest.raises(_QuarantinedRead):
            await s._handle_delimited_ping(DelimitedV4Message.PING)
        assert [p[0] for p in stream.writes] == [3, 13]
        now[0] = 140
        stream.queue.put_nowait(b"")
        await stopped(s)
        assert pong.peer_eofs == 1
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize("queued_read", [True, False])
def test_queued_tx_is_not_in_flight_and_never_writes_after_latch(queued_read):
    async def scenario():
        s, stream, budget, _, _ = await connected()
        await s._tx_lock.acquire()
        task = asyncio.create_task(
            s.request_v4_data()
            if queued_read
            else s._handle_delimited_ping(DelimitedV4Message.PING)
        )
        await until(lambda: bool(s._tx_operations))
        assert not s._tx_in_flight
        stream.queue.put_nowait(b"\x05")
        await until(lambda: s.state is SessionState.QUARANTINED)
        assert not s._loss_event.is_set()
        s._tx_lock.release()
        with pytest.raises(_QuarantinedRead):
            await task
        assert budget.requests == 0 and len(stream.writes) == 1
        await cleanup(s, stream)

    asyncio.run(scenario())


def test_engaged_tx_is_not_claimed_as_cut_off_retroactively():
    async def scenario():
        s, stream, budget, pong, _ = await connected()
        stream.block_write = True
        read = asyncio.create_task(s.request_v4_data())
        await stream.write_started.wait()
        assert s._tx_in_flight
        stream.queue.put_nowait(b"\x05")
        await until(lambda: s._quarantine_observation is not None)
        assert s._quarantine_observation.state is State.REFUSED
        assert s._quarantine_observation.reason is Reason.TX_IN_FLIGHT
        assert s.state is not SessionState.QUARANTINED
        stream.release_write.set()
        with pytest.raises(HobenProtocolError):
            await read
        # The abandoned read's existing close path can cancel RX while it is
        # releasing TX. That is a local stop, never an admissible transport EOF.
        result = (await asyncio.gather(s._rx_task, return_exceptions=True))[0]
        assert result is None or isinstance(
            result, (HobenProtocolError, asyncio.CancelledError)
        )
        assert not s.loss_is_retryable
        assert budget.requests == 1 and pong.peer_eofs == 0
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize("coalesced", [True, False])
def test_only_a_response_delivered_before_cutoff_remains_successful(coalesced):
    async def scenario():
        s, stream, budget, _, now = await connected()
        read = asyncio.create_task(s.request_v4_data())
        await until(lambda: budget.requests == 1 and not s._tx_in_flight)
        if coalesced:
            await enter(s, stream, response() + b"\x05\x0a")
            with pytest.raises(_QuarantinedRead):
                await read
            assert budget.responses == 0 and budget.pings == 1
        else:
            stream.queue.put_nowait(response())
            assert (await read).registers == (17,) * 20
            assert budget.responses == 1
            now[0] = 132
            await enter(s, stream)
            assert budget.responses == 1
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "before120",
        "at240",
        "after240",
        "suppression0",
        "generation2",
        "type_other",
        "default_off",
    ],
)
def test_ineligible_rejections_preserve_normal_protocol_failure(case):
    async def scenario():
        s, stream, budget, pong, now = await connected(
            enabled=case != "default_off", suppress=case != "suppression0"
        )
        if case == "before120":
            now[0] = 129
        if case in {"at240", "after240"}:
            now[0] = 250 if case == "at240" else 251
        if case == "generation2":
            s._experiment_generation = 2  # Stale owner declaration, fail closed.
        stream.queue.put_nowait(b"\x1b" if case == "type_other" else b"\x05")
        await stopped(s)
        assert s.state is not SessionState.QUARANTINED
        assert pong.peer_eofs == 0 and budget.opens == 1
        if case in {"type_other", "default_off"}:
            assert not s._quarantine_latched and s._quarantine_observation is None
        else:
            assert s._quarantine_observation.state is State.REFUSED
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "end",
    ["tls", "deadline", "data_deadline", "rx_budget", "close", "abort", "rx_cancel"],
)
def test_non_eof_endings_never_become_admissible(end, deadlines):
    async def scenario():
        s, stream, budget, pong, now = await connected()
        await enter(s, stream)
        now[0] = 132
        if end == "tls":
            stream.queue.put_nowait(TransportTlsError("synthetic-private"))
        elif end == "deadline":
            deadlines.contexts[-1][1].reschedule(asyncio.get_running_loop().time())
        elif end == "data_deadline":
            now[0] = 250
            stream.queue.put_nowait(b"\x0a")
        elif end == "rx_budget":
            before = budget.rx_bytes
            for _ in range(256):
                stream.queue.put_nowait(b"\x7f" * 4096)
        elif end == "close":
            await s.close()
        elif end == "abort":
            await s.abort()
        else:
            s._rx_task.cancel()
        await stopped(s)
        result = s._quarantine_observation
        assert result.state is State.REFUSED
        assert result.origin is _QuarantineOrigin.NONE
        assert pong.peer_eofs == 0 and budget.opens == 1
        if end == "rx_budget":
            assert budget.rx_bytes == before + 256 * 4096
            assert budget.rx_bytes > 1048576
        assert not s._framer.partial and not s._opening_buffer
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key", ["observation_deadline_ms", "process_deadline_ms", "suite_deadline_ms"]
)
@pytest.mark.parametrize("at_deadline", [False, True])
def test_each_external_deadline_bounds_real_eof_admissibility(key, at_deadline):
    async def scenario():
        now = [10]
        budget, pong = owners(now)
        stream = QuarantineStream()
        s = V4Session(
            user_guid="b" * 32,
            transport_factory=lambda: stream,
            session_300=budget,
            no_pong_after_120=pong,
            _quarantine=capability(budget, pong, **{key: 140000}),
        )
        await s.connect()
        now[0] = 130
        stream.queue.put_nowait(b"\x0a")
        await until(lambda: pong.suppressed == 1)
        now[0] = 131
        await enter(s, stream)
        assert s._quarantine_policy.snapshot.deadline_ms == 140000
        now[0] = 140 if at_deadline else 139
        stream.queue.put_nowait(b"")
        await stopped(s)
        assert s._quarantine_observation.state is (
            State.REFUSED if at_deadline else State.EOF_CANDIDATE
        )
        assert pong.peer_eofs == int(not at_deadline)
        await cleanup(s, stream)

    asyncio.run(scenario())


def test_eof_at_same_quantized_time_as_cutoff_is_ambiguous():
    async def scenario():
        s, stream, _, pong, _ = await connected()
        stream.queue.put_nowait(b"\x05")
        stream.queue.put_nowait(b"")
        await stopped(s)
        assert s._quarantine_observation.state is State.REFUSED
        assert s._quarantine_observation.reason is Reason.AMBIGUOUS
        assert pong.peer_eofs == 0
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize("stop_first", [False, True])
@pytest.mark.parametrize("stop", ["close", "abort"])
def test_concurrent_stop_and_eof_never_leave_candidate(stop_first, stop):
    async def scenario():
        s, stream, _, _, now = await connected()
        await enter(s, stream)
        now[0] = 140
        if not stop_first:
            stream.queue.put_nowait(b"")
        task = asyncio.create_task(getattr(s, stop)())
        if stop_first:
            stream.queue.put_nowait(b"")
        await task
        assert s._quarantine_observation.state is State.REFUSED
        assert s._quarantine_observation.origin is _QuarantineOrigin.NONE
        assert not s.loss_is_retryable
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize("stop", ["close", "abort"])
@pytest.mark.parametrize("eof_first", [False, True])
def test_same_timestamp_stop_eof_orders_revoke_candidate(stop, eof_first):
    async def scenario():
        s, stream, _, pong, now = await connected()
        await enter(s, stream)
        now[0] = 140
        if eof_first:
            stream.queue.put_nowait(b"")
            await stopped(s)
        await getattr(s, stop)()
        if not eof_first:
            stream.queue.put_nowait(b"")
        assert s._quarantine_observation.state is State.REFUSED
        assert s._quarantine_observation.origin is _QuarantineOrigin.NONE
        assert pong.peer_eofs == int(eof_first)
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [True, False])
def test_already_winning_read_cancel_or_timeout_cannot_leave_admissible_eof(cancel):
    async def scenario():
        s, stream, _, pong, _ = await connected()
        read = asyncio.create_task(s.request_v4_data())
        await until(lambda: s._read_timeout is not None and not s._tx_in_flight)
        if cancel:
            read.cancel()
        else:
            s._read_timeout.reschedule(asyncio.get_running_loop().time())
        await asyncio.sleep(0)
        stream.queue.put_nowait(b"\x05")
        stream.queue.put_nowait(b"")
        with pytest.raises(asyncio.CancelledError if cancel else HobenTimeoutError):
            await read
        assert s.state is not SessionState.QUARANTINED
        assert pong.peer_eofs == 0
        await cleanup(s, stream)

    asyncio.run(scenario())


def test_read_cancellation_after_waiter_signal_still_revokes_quarantine():
    async def scenario():
        s, stream, budget, pong, _ = await connected()
        read = asyncio.create_task(s.request_v4_data())
        await until(lambda: budget.requests == 1 and not s._tx_in_flight)
        # Cancel between set_exception and the shielded request resuming. This
        # is a caller stop, unlike cancellation of a passive RX observer.
        s._pending_read.add_done_callback(lambda _: read.cancel())
        stream.queue.put_nowait(b"\x05")
        with pytest.raises(asyncio.CancelledError):
            await read
        assert s._quarantine_observation.state is State.REFUSED
        assert pong.peer_eofs == 0 and not s.loss_is_retryable
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "clock_value", [True, -1, float("nan"), float("inf"), 10**1000, "private", None]
)
def test_invalid_owner_clock_cannot_create_candidate(clock_value):
    async def scenario():
        s, stream, _, pong, now = await connected()
        now[0] = clock_value
        stream.queue.put_nowait(b"\x05")
        await stopped(s)
        result = s._quarantine_observation
        assert result.state is State.REFUSED and result.at_ms is None
        assert "private" not in repr(result)
        assert pong.peer_eofs == 0
        await cleanup(s, stream)

    asyncio.run(scenario())


def test_clock_failure_cannot_prevent_close_or_manufacture_eof():
    async def scenario():
        s, stream, budget, pong, _ = await connected()
        await enter(s, stream)

        def failed_clock():
            raise RuntimeError("synthetic-private")

        budget.clock = failed_clock
        stream.queue.put_nowait(b"")
        await stopped(s)
        assert s._quarantine_observation.state is State.REFUSED
        assert s._quarantine_observation.at_ms is None
        assert pong.peer_eofs == 0
        assert "synthetic-private" not in repr(s._quarantine_observation)
        await cleanup(s, stream)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "budget_type", [Session300, type("Derived", (SessionReconnect,), {})]
)
def test_capability_requires_exact_second_scenario_and_matching_owners(budget_type):
    now = [10]
    budget, pong = owners(now)
    with pytest.raises(HobenInvalidInputError):
        capability(budget_type(clock=budget.clock), pong)
    cap = capability(budget, pong)
    with pytest.raises(HobenInvalidInputError):
        V4Session(
            session_300=SessionReconnect(clock=budget.clock),
            no_pong_after_120=pong,
            _quarantine=cap,
        )
    V4Session(session_300=budget, no_pong_after_120=pong, _quarantine=cap)
    with pytest.raises(HobenInvalidInputError):
        V4Session(session_300=budget, no_pong_after_120=pong, _quarantine=cap)
    with pytest.raises(HobenInvalidInputError):
        V4Session(session_300=budget, no_pong_after_120=pong, _quarantine=True)


@pytest.mark.parametrize("bad", [True, -1, 1.0, float("nan"), None, 2**53])
def test_capability_deadlines_are_strict_bounded_integers(bad):
    budget, pong = owners([10])
    with pytest.raises(HobenInvalidInputError):
        capability(budget, pong, observation_deadline_ms=bad)


def test_capability_is_not_constructible_after_an_opening_or_policy_acceptance():
    budget, pong = owners([10])
    budget.opening()
    with pytest.raises(HobenInvalidInputError):
        capability(budget, pong)
    budget, pong = owners([10])
    pong.accepted(1)
    with pytest.raises(HobenInvalidInputError):
        capability(budget, pong)


def test_only_session_imports_bridge_and_no_consumer_supplies_capability(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    assert inspect.signature(V4Session).parameters["_quarantine"].default is None
    for folder in ("custom_components", "scripts", ".github"):
        for path in (root / folder).rglob("*"):
            if (
                path == root / "custom_components/hoben/v4_session.py"
                or path.suffix not in {".py", ".js", ".cjs", ".yml", ".yaml"}
            ):
                continue
            source = path.read_text()
            assert (
                "_QuarantineCapability" not in source and "_quarantine" not in source
            ), path
            if path.suffix == ".py":
                tree = ast.parse(source)
                assert not any(
                    isinstance(n, ast.keyword) and n.arg == "_quarantine"
                    for n in ast.walk(tree)
                ), path
    monkeypatch.setenv("HOBEN_QUARANTINE", "true")
    monkeypatch.setenv("SESSION_QUARANTINE", "true")
    session = V4Session()
    assert session._quarantine_capability is None
    assert session._quarantine_policy is None and not session._quarantine_latched
