"""Private L5 recovery: real session/lifecycle, wholly synthetic TLS and time."""

import ast
import asyncio
import inspect
from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.hoben.exceptions import (
    HobenClientClosedError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTransportError,
)
from custom_components.hoben.transport import TransportTlsError
from custom_components.hoben.v4_eof_quarantine import State
from custom_components.hoben.v4_lifecycle import (
    LifecycleStoppedError,
    V4Lifecycle,
    _LifecycleQuarantineCapability,
)
from custom_components.hoben.v4_session import (
    DelimitedV4DataResponse,
    SessionState,
    SessionStateError,
    V4Session,
    _QuarantinedRead,
    _QuarantineOrigin,
)
from tests.test_session_300_runtime import response
from tests.test_session_no_pong import until
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_session_quarantine import QuarantineStream, owners


class ControlledStream(QuarantineStream):
    def __init__(self, factory, index):
        super().__init__()
        self.factory, self.index = factory, index
        self.opening_started = asyncio.Event()
        self.closing_started = asyncio.Event()
        self.connect_gate = self.close_gate = None

    async def connect(self):
        self.opening_started.set()
        if self.connect_gate is not None:
            await self.connect_gate.wait()
        if self.index in self.factory.fail_open:
            raise TransportTlsError("synthetic-private")

    async def read(self, max_bytes=4096, *, bounded=True):
        if bounded and self.index and self.factory.accept_at is not None:
            self.factory.now[0] = self.factory.accept_at
        result = await super().read(max_bytes, bounded=bounded)
        if bounded and self.index and self.factory.stop_at_accept:
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.create_task(self.factory.life.close())
            )
        return result

    async def close(self):
        self.closing_started.set()
        await super().close()
        if self.close_gate is not None:
            await self.close_gate.wait()
        if self.factory.close_failure:
            raise TransportTlsError("synthetic-private")


class Factory:
    def __init__(self, now):
        self.now = now
        self.sessions, self.streams, self.inputs = [], [], []
        self.fail_open = set()
        self.accept_at = None
        self.stop_at_accept = False
        self.close_failure = False
        self.new_open_gate = None
        self.replacement_suffix = b""
        self.life = None

    def __call__(self, **kwargs):
        index = len(self.sessions)
        stream = ControlledStream(self, index)
        if index:
            stream.connect_gate = self.new_open_gate
            stream.prefix += self.replacement_suffix
        session = V4Session(**kwargs, transport_factory=lambda: stream)
        self.inputs.append(kwargs)
        self.streams.append(stream)
        self.sessions.append(session)
        return session


async def connected(*, deadlines=None, delays=(1, 2), enabled=True):
    now = [10]
    budget, pong = owners(now)
    cap = (
        _LifecycleQuarantineCapability(
            budget,
            pong,
            **(
                {
                    "observation_deadline_ms": 600000,
                    "process_deadline_ms": 610000,
                    "suite_deadline_ms": 1030000,
                }
                | (deadlines or {})
            ),
        )
        if enabled
        else None
    )
    factory, sleep = Factory(now), Backoff()
    life = V4Lifecycle(
        user_guid="b" * 32,
        session_factory=factory,
        sleep=sleep,
        retry_delays=delays,
        _quarantine=cap,
    )
    factory.life = life
    await life.connect()
    return life, factory, sleep, budget, pong, now, cap


async def quarantined(life, factory, pong, now):
    now[0] = 130
    factory.streams[0].queue.put_nowait(b"\x0a")
    await until(lambda: pong.suppressed == 1)
    now[0] = 131
    factory.streams[0].queue.put_nowait(b"\x05\x7f\x0a")
    await until(lambda: life.state is SessionState.QUARANTINED)
    assert life.snapshot.state is SessionState.QUARANTINED
    assert not factory.sessions[0]._loss_event.is_set()
    assert not factory.sessions[0]._experiment.usable
    assert not sleep_or_extra(factory)


def sleep_or_extra(factory):
    return len(factory.sessions) != 1 or factory.streams[0].close_count != 0


async def reached_backoff(factory, sleep, now):
    now[0] = 140
    factory.streams[0].queue.put_nowait(b"")
    assert await asyncio.wait_for(sleep.entered.get(), 2) == 1
    assert factory.streams[0].close_count == 1


async def clean(life, factory):
    await life.close()
    await life.close()
    for s, stream in zip(factory.sessions, factory.streams, strict=True):
        assert s.state is SessionState.CLOSED
        assert stream.close_count == 1
        assert stream.active_reads == stream.active_tx == 0
        assert s._transport is s._opening_task is s._pending_read is None
        assert s._read_timeout is None and not s._tx_lock.locked()
        assert not s._operations and not s._tx_operations
        assert s._rx_task is None or s._rx_task.done()
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


def test_suspend_waiters_once_then_fresh_generation_restores_pong_read_without_replay():
    async def scenario():
        life, f, sleep, budget, pong, now, cap = await connected()
        old = f.sessions[0]
        identity = life.device_guid_for_persistence
        read = asyncio.create_task(life.request_v4_data())
        await until(lambda: budget.requests == 1 and not old._tx_in_flight)
        exchange = old._pending_read
        await quarantined(life, f, pong, now)
        with pytest.raises(_QuarantinedRead):
            await read
        assert old._pending_read is old._read_timeout is None
        with pytest.raises(SessionStateError):
            await life.request_v4_data()
        waiting = [asyncio.create_task(life.wait_connected()) for _ in range(3)]
        await asyncio.sleep(0)
        assert not any(t.done() for t in waiting)
        waiting[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting[0]
        assert not life._task.cancelling() and not old._rx_task.cancelling()
        await reached_backoff(f, sleep, now)
        assert cap._permit is old._quarantine_permit
        assert old._quarantine_observation.state is State.EOF_CANDIDATE
        with pytest.raises(HobenProtocolError):
            old._consume_quarantine(life, 1)
        assert not any(t.done() for t in waiting[1:])
        assert life.state is SessionState.RECONNECTING
        now[0] = 142
        sleep.release.put_nowait(None)
        await asyncio.gather(*waiting[1:])
        new, stream = f.sessions[1], f.streams[1]
        with pytest.raises(HobenProtocolError):
            new._consume_quarantine(life, 2)  # Another session cannot claim it.
        assert new is not old and new._quarantine_capability is None
        assert new._pending_read is None and new._experiment is budget
        assert f.inputs[1]["device_guid"] == identity
        assert budget.opens == 2 and budget.requests == 1
        assert len(stream.writes) == 1  # No replay of old sent read.
        stream.queue.put_nowait(b"\x0a")
        await until(lambda: budget.pongs == 1)
        assert pong.suppressed == 1
        result = asyncio.create_task(life.request_v4_data())
        await until(lambda: budget.requests == 2 and not new._tx_in_flight)
        with pytest.raises(_QuarantinedRead):
            await old._handle_delimited_data_response(
                DelimitedV4DataResponse(response(), exchange=exchange)
            )
        assert not result.done()
        stream.queue.put_nowait(response())
        assert (await result).registers == (17,) * 20
        assert budget.responses == 1
        assert f.streams[0].owners == {old._rx_task}
        assert stream.owners == {new._rx_task}
        assert pong.peer_eofs == 1
        # No public result or stable-success claim is generated by this bridge.
        assert "recovered_120s" not in repr(life.snapshot)
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "ending",
    ["discriminator", "silence", "tls", "close", "abort", "owner_close", "rx_cancel"],
)
def test_only_admissible_eof_can_open_private_recovery(ending, deadlines):
    async def scenario():
        life, f, sleep, _, pong, now, _ = await connected()
        await quarantined(life, f, pong, now)
        now[0] = 140
        if ending in {"discriminator", "silence"}:
            deadlines.contexts[-1][1].reschedule(asyncio.get_running_loop().time())
        elif ending == "tls":
            f.streams[0].queue.put_nowait(TransportTlsError("synthetic-private"))
        elif ending == "close":
            await f.sessions[0].close()
        elif ending == "abort":
            await f.sessions[0].abort()
        elif ending == "owner_close":
            await life.close()
        else:
            f.sessions[0]._rx_task.cancel()
        with pytest.raises((HobenProtocolError, HobenClientClosedError)):
            await life.wait_stopped()
        assert len(f.sessions) == 1 and not sleep.delays
        assert pong.peer_eofs == 0
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize("eof_first", [False, True])
def test_simultaneous_owner_stop_wins_before_consumption(eof_first):
    async def scenario():
        life, f, sleep, _, pong, now, cap = await connected()
        await quarantined(life, f, pong, now)
        now[0] = 140
        if eof_first:
            f.streams[0].queue.put_nowait(b"")
        stop = asyncio.create_task(life.close())
        if not eof_first:
            f.streams[0].queue.put_nowait(b"")
        await stop
        assert cap._permit is None and not sleep.delays
        assert len(f.sessions) == 1
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "invalidate", ["close", "generation", "origin", "date", "state", "stale"]
)
def test_live_origin_rechecked_before_consumption_instead_of_copying_snapshot(
    invalidate,
):
    async def scenario():
        life, f, sleep, _, pong, now, cap = await connected()
        await quarantined(life, f, pong, now)
        old = f.sessions[0]
        now[0] = 140
        f.streams[0].queue.put_nowait(b"")
        await until(lambda: old._quarantine_observation.state is State.EOF_CANDIDATE)
        copied = old._quarantine_observation
        assert f.streams[0].close_count == 0 and old._transport is not None
        assert old._rx_task.done()  # Consumption precedes intentional cleanup.
        if invalidate == "close":
            await old.close()
        elif invalidate == "generation":
            old._experiment_generation = 2
        elif invalidate == "origin":
            old._quarantine_observation = replace(copied, origin=_QuarantineOrigin.NONE)
        elif invalidate == "date":
            old._quarantine_observation = replace(copied, at_ms=copied.at_ms + 1)
        elif invalidate == "state":
            old._quarantine_observation = replace(copied, state=State.REFUSED)
        else:
            now[0] = 250
        with pytest.raises(HobenProtocolError):
            await life.wait_stopped()
        assert copied.state is State.EOF_CANDIDATE
        assert cap._permit is None and not sleep.delays
        assert len(f.sessions) == 1
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "phase", ["quarantine", "cleanup", "backoff", "opening", "acceptance", "stable"]
)
def test_stop_each_phase_leaves_no_late_opening_or_orphan(phase):
    async def scenario():
        life, f, sleep, _, pong, now, cap = await connected()
        await quarantined(life, f, pong, now)
        closing_gate = None
        if phase == "cleanup":
            closing_gate = f.streams[0].close_gate = asyncio.Event()
        if phase != "quarantine":
            now[0] = 140
            f.streams[0].queue.put_nowait(b"")
            if phase == "cleanup":
                await f.streams[0].closing_started.wait()
            else:
                await asyncio.wait_for(sleep.entered.get(), 2)
        if phase in {"opening", "acceptance", "stable"}:
            f.new_open_gate = asyncio.Event() if phase == "opening" else None
            f.stop_at_accept = phase == "acceptance"
            now[0] = 142
            sleep.release.put_nowait(None)
            if phase == "opening":
                await until(lambda: len(f.streams) == 2)
                await f.streams[1].opening_started.wait()
            elif phase == "acceptance":
                await until(lambda: life._stopping)
            else:
                await life.wait_connected()
        await life.close()
        if closing_gate:
            closing_gate.set()
        if f.new_open_gate:
            f.new_open_gate.set()
        sleep.release.put_nowait(None)
        assert cap._origin._quarantine_owner_stopped
        assert len(f.sessions) <= 2
        with pytest.raises(LifecycleStoppedError):
            await life.wait_connected()
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "accept_at,allowed", [(249.999, True), (250, False), (250.001, False)]
)
def test_actual_reacceptance_must_precede_240_from_initial_t0(accept_at, allowed):
    async def scenario():
        life, f, sleep, _, pong, now, cap = await connected()
        await quarantined(life, f, pong, now)
        await reached_backoff(f, sleep, now)
        f.accept_at = accept_at
        now[0] = 141
        sleep.release.put_nowait(None)
        if allowed:
            await life.wait_connected()
            assert life.state is SessionState.CONNECTED and cap._recovered
        else:
            with pytest.raises(HobenProtocolError):
                await life.wait_stopped()
            assert life.state is SessionState.DISCONNECTED
            assert pong._current == 1  # Late prefix was never strictly adopted.
        assert len(f.sessions) == 2
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key", ["observation_deadline_ms", "process_deadline_ms", "suite_deadline_ms"]
)
@pytest.mark.parametrize("after_open", [False, True])
def test_insufficient_120s_remaining_never_extends_any_budget(key, after_open):
    async def scenario():
        life, f, sleep, _, pong, now, _ = await connected(
            deadlines={key: 260000 if not after_open else 270000}
        )
        await quarantined(life, f, pong, now)
        now[0] = 140
        f.streams[0].queue.put_nowait(b"")
        if after_open:
            await asyncio.wait_for(sleep.entered.get(), 2)
            f.accept_at = 151
            sleep.release.put_nowait(None)
        with pytest.raises(HobenProtocolError):
            await life.wait_stopped()
        assert len(f.sessions) == (2 if after_open else 1)
        if not after_open:
            assert not sleep.delays
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "invalidate", ["old_close", "deadline", "retrograde", "clock_failure"]
)
def test_consumed_origin_can_still_be_revoked_during_backoff(invalidate):
    async def scenario():
        life, f, sleep, _, pong, now, cap = await connected()
        await quarantined(life, f, pong, now)
        await reached_backoff(f, sleep, now)
        old = f.sessions[0]
        with pytest.raises(HobenProtocolError):
            old._consume_quarantine(object(), 1)
        if invalidate == "old_close":
            await old.close()
        elif invalidate == "deadline":
            now[0] = 250
        elif invalidate == "retrograde":
            now[0] = 139
        else:
            now[0] = None
        sleep.release.put_nowait(None)
        with pytest.raises(HobenProtocolError):
            await life.wait_stopped()
        assert len(f.sessions) == 1 and cap._permit is not None
        now[0] = 145
        assert not old._quarantine_permit_valid(life, cap._permit)
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize("loss", [b"", TransportTlsError("synthetic-private"), b"\x05"])
def test_second_accepted_generation_loss_is_terminal_without_cumulative_stability(loss):
    async def scenario():
        life, f, sleep, budget, pong, now, _ = await connected()
        await quarantined(life, f, pong, now)
        await reached_backoff(f, sleep, now)
        now[0] = 142
        sleep.release.put_nowait(None)
        await life.wait_connected()
        now[0] = 160
        f.streams[1].queue.put_nowait(loss)
        with pytest.raises((HobenProtocolError, HobenTransportError)):
            await life.wait_stopped()
        assert budget.opens == 2 and sleep.delays == [1]
        await clean(life, f)

    asyncio.run(scenario())


def test_failed_reopening_consumes_third_attempt_without_replenishing_shared_budget():
    async def scenario():
        life, f, sleep, budget, pong, now, _ = await connected()
        await quarantined(life, f, pong, now)
        await reached_backoff(f, sleep, now)
        f.fail_open = {1}
        now[0] = 142
        sleep.release.put_nowait(None)
        assert await asyncio.wait_for(sleep.entered.get(), 2) == 2
        now[0] = 145
        sleep.release.put_nowait(None)
        await life.wait_connected()
        assert budget.opens == life.snapshot.attempts == life.snapshot.max_attempts == 3
        f.streams[2].queue.put_nowait(b"")
        with pytest.raises(HobenTransportError):
            await life.wait_stopped()
        assert sleep.delays == [1, 2]
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["idle", "cleanup", "backoff", "opening", "stable"])
def test_private_absolute_timers_bound_every_phase_without_success(phase, deadlines):
    async def scenario():
        life, f, sleep, _, pong, now, _ = await connected()
        if phase != "idle":
            await quarantined(life, f, pong, now)
            if phase == "cleanup":
                f.streams[0].close_gate = asyncio.Event()
                now[0] = 140
                f.streams[0].queue.put_nowait(b"")
                await f.streams[0].closing_started.wait()
            else:
                await reached_backoff(f, sleep, now)
            if phase in {"opening", "stable"}:
                f.new_open_gate = asyncio.Event() if phase == "opening" else None
                now[0] = 142
                sleep.release.put_nowait(None)
                if phase == "opening":
                    await until(lambda: len(f.streams) == 2)
                    await f.streams[1].opening_started.wait()
                else:
                    await life.wait_connected()
        now[0] = 370 if phase == "stable" else 250
        deadlines.contexts[-1][1].reschedule(asyncio.get_running_loop().time())
        with pytest.raises(HobenProtocolError):
            await asyncio.wait_for(life.wait_stopped(), 2)
        assert len(f.sessions) == (2 if phase in {"opening", "stable"} else 1)
        assert "recovered_120s" not in repr(life.snapshot)
        await clean(life, f)

    asyncio.run(scenario())


def test_oversized_backoff_is_refused_before_sleep_without_new_attempt():
    async def scenario():
        life, f, sleep, _, pong, now, _ = await connected(delays=(120, 2))
        await quarantined(life, f, pong, now)
        now[0] = 140
        f.streams[0].queue.put_nowait(b"")
        with pytest.raises(HobenProtocolError):
            await life.wait_stopped()
        assert not sleep.delays and len(f.sessions) == 1
        await clean(life, f)

    asyncio.run(scenario())


def test_cleanup_failure_cannot_authorize_a_new_private_opening():
    async def scenario():
        life, f, sleep, _, pong, now, cap = await connected()
        await quarantined(life, f, pong, now)
        f.close_failure = True
        now[0] = 140
        f.streams[0].queue.put_nowait(b"")
        with pytest.raises(HobenProtocolError):
            await life.wait_stopped()
        assert len(f.sessions) == 1 and not sleep.delays
        assert cap._origin._quarantine_owner_stopped
        await clean(life, f)

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["quarantine", "backoff", "opening"])
def test_direct_owner_cancellation_never_leaves_recovery_running(phase):
    async def scenario():
        life, f, sleep, _, pong, now, _ = await connected()
        await quarantined(life, f, pong, now)
        if phase != "quarantine":
            await reached_backoff(f, sleep, now)
        if phase == "opening":
            f.new_open_gate = asyncio.Event()
            now[0] = 142
            sleep.release.put_nowait(None)
            await until(lambda: len(f.streams) == 2)
            await f.streams[1].opening_started.wait()
        life._task.cancel()
        with pytest.raises(LifecycleStoppedError):
            await life.wait_stopped()
        assert len(f.sessions) <= 2
        await clean(life, f)

    asyncio.run(scenario())


def test_lifecycle_capability_is_exact_one_use_and_rejects_more_than_three_attempts():
    budget, pong = owners([10])
    cap = _LifecycleQuarantineCapability(
        budget,
        pong,
        observation_deadline_ms=600000,
        process_deadline_ms=610000,
        suite_deadline_ms=1030000,
    )
    with pytest.raises(HobenInvalidInputError):
        V4Lifecycle(user_guid="b" * 32, _quarantine=cap)
    V4Lifecycle(user_guid="b" * 32, retry_delays=(1, 2), _quarantine=cap)
    with pytest.raises(HobenInvalidInputError):
        V4Lifecycle(user_guid="b" * 32, retry_delays=(1,), _quarantine=cap)
    with pytest.raises(HobenInvalidInputError):
        V4Lifecycle(user_guid="b" * 32, _quarantine=True)


@pytest.mark.parametrize("suppressed", [False, True])
def test_true_eof_without_quarantine_proof_cannot_use_generic_retry(suppressed):
    async def scenario():
        life, f, sleep, _, pong, now, _ = await connected()
        if suppressed:
            now[0] = 130
            f.streams[0].queue.put_nowait(b"\x0a")
            await until(lambda: pong.suppressed == 1)
        now[0] = 140
        f.streams[0].queue.put_nowait(b"")
        with pytest.raises(HobenTransportError):
            await life.wait_stopped()
        assert pong.peer_eofs == 1 and len(f.sessions) == 1 and not sleep.delays
        await clean(life, f)

    asyncio.run(scenario())


def test_default_abort_retains_public_close_override_semantics():
    called = []

    class OrdinarySession(V4Session):
        async def close(self):
            called.append(True)
            await super().close()

    async def scenario():
        session = OrdinarySession()
        await session.abort()
        assert called == [True] and session.state is SessionState.CLOSED

    asyncio.run(scenario())


def test_immediate_loss_after_new_strict_acceptance_cannot_authorize_a_third_open():
    async def scenario():
        life, f, sleep, budget, pong, now, cap = await connected()
        await quarantined(life, f, pong, now)
        await reached_backoff(f, sleep, now)
        f.replacement_suffix = b"\x05"
        now[0] = 142
        sleep.release.put_nowait(None)
        with pytest.raises(HobenProtocolError):
            await life.wait_stopped()
        assert cap._recovered and budget.opens == 2
        assert len(f.sessions) == 2 and sleep.delays == [1]
        assert cap._origin._quarantine_owner_stopped
        await clean(life, f)

    asyncio.run(scenario())


def test_same_new_generation_can_run_120s_with_normal_pong_and_reads_without_report():
    async def scenario():
        life, f, sleep, budget, pong, now, _ = await connected()
        await quarantined(life, f, pong, now)
        await reached_backoff(f, sleep, now)
        now[0] = 142
        sleep.release.put_nowait(None)
        await life.wait_connected()
        new = f.sessions[1]
        for tick in (142, 202, 262):
            now[0] = tick
            f.streams[1].queue.put_nowait(b"\x0a")
            await until(lambda: budget.pongs == (tick - 142) // 60 + 1)
            read = asyncio.create_task(life.request_v4_data())
            await until(
                lambda: (
                    budget.requests == (tick - 142) // 60 + 1 and not new._tx_in_flight
                )
            )
            f.streams[1].queue.put_nowait(response())
            assert (await read).registers == (17,) * 20
            assert (
                life.state is SessionState.CONNECTED
                and budget.connected_generation == 2
            )
        assert budget.opens == 2 and budget.responses == 3 and pong.suppressed == 1
        assert "recovered_120s" not in repr(life.snapshot)
        await clean(life, f)

    asyncio.run(scenario())


def test_default_off_guard_allows_only_reviewed_session_lifecycle_references(
    monkeypatch,
):
    assert inspect.signature(V4Lifecycle).parameters["_quarantine"].default is None
    root = Path(__file__).resolve().parents[1]
    allowed = {
        root / "custom_components/hoben/v4_session.py",
        root / "custom_components/hoben/v4_lifecycle.py",
    }
    for folder in ("custom_components", "scripts", ".github"):
        for p in (root / folder).rglob("*"):
            if p in allowed or p.suffix not in {".py", ".js", ".cjs", ".yml", ".yaml"}:
                continue
            source = p.read_text()
            assert (
                "_LifecycleQuarantineCapability" not in source
                and "_quarantine" not in source
            ), p
            if p.suffix == ".py":
                assert not any(
                    isinstance(n, ast.keyword) and n.arg == "_quarantine"
                    for n in ast.walk(ast.parse(source))
                ), p
    monkeypatch.setenv("HOBEN_QUARANTINE", "true")
    life = V4Lifecycle(user_guid="b" * 32)
    assert life._quarantine is None
