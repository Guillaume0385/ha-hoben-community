"""Offline policy foundation; no live collector or causal timeout claim."""

import asyncio

import pytest

from custom_components.hoben.exceptions import HobenInvalidInputError
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_experiment import Session300
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import SessionState, V4Session
from tests.test_session_300_runtime import Stream, response


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), 2)


def test_policy_requires_the_explicit_experimental_session():
    with pytest.raises(HobenInvalidInputError):
        V4Session(no_pong_after_120=NoPongAfter120())
    with pytest.raises(HobenInvalidInputError):
        V4Session(session_300=Session300(), no_pong_after_120=object())


def test_monotonic_threshold_current_generation_and_no_causal_claim():
    now = [50]
    policy = NoPongAfter120(clock=lambda: now[0])
    assert not policy.suppress(1)
    policy.accepted(1)
    now[0] = 169.999
    assert not policy.suppress(1)
    now[0] = 170
    assert policy.suppress(1)
    policy.peer_closed(1)
    policy.peer_closed(1)
    assert policy.peer_eofs == policy.peer_eofs_after_suppression == 1
    policy.accepted(2)
    now[0] = 9999
    assert not policy.suppress(1) and not policy.suppress(2)
    policy.peer_closed(1)  # An old owner cannot annotate the new generation.
    assert policy.peer_eofs == 1
    assert repr(policy) == "NoPongAfter120()"


@pytest.mark.parametrize(
    "loss", ["eof_exception", "empty_read", "tls_error", "local_close"]
)
def test_shared_rx_reads_tx_lock_recovery_and_peer_eof_are_distinct(loss):
    async def scenario():
        now = [0.0]
        clock = lambda: now[0]  # noqa: E731
        policy, budget = NoPongAfter120(clock=clock), Session300(clock=clock)
        streams, sessions = [], []

        def factory(**kwargs):
            stream = Stream([response()])
            session = V4Session(
                **kwargs,
                session_300=budget,
                no_pong_after_120=policy,
                transport_factory=lambda: stream,
            )
            streams.append(stream)
            sessions.append(session)
            return session

        async def backoff(delay):
            assert delay == 1
            now[0] += delay
            await asyncio.sleep(0)

        life = V4Lifecycle(
            user_guid="b" * 32,
            session_factory=factory,
            retry_delays=(1,),
            sleep=backoff,
        )
        try:
            await life.connect()
            streams[0].queue.put_nowait(b"\x0a")
            await until(lambda: budget.pongs == 1)
            now[0] = 119.999
            await sessions[0]._tx_lock.acquire()
            try:
                streams[0].queue.put_nowait(b"\x0a")
                await until(lambda: budget.pings == 2)
                assert policy.suppressed == 0
                now[0] = 120
            finally:
                sessions[0]._tx_lock.release()
            await until(lambda: policy.suppressed == 1)
            assert budget.pings == 2 and budget.pongs == 1
            assert life.state is SessionState.CONNECTED and budget.opens == 1
            # A fixed correlated read continues through the very same RX owner.
            await life.request_v4_data()
            assert budget.responses == 1
            assert [p[0] for p in streams[0].writes] == [3, 11, 13]
            assert policy.peer_eofs == 0
            if loss == "local_close":
                await life.close()
                assert budget.opens == 1 and policy.peer_eofs == 0
                return
            event = {
                "eof_exception": TransportEOF("synthetic-private"),
                "empty_read": b"",
                "tls_error": TransportTlsError("synthetic-private"),
            }[loss]
            streams[0].queue.put_nowait(event)
            await until(lambda: budget.opens == 2)
            await life.wait_connected()
            streams[1].queue.put_nowait(b"\x0a")
            await until(lambda: budget.pongs == 2)
            assert policy.suppressed == 1
            assert [p[0] for p in streams[1].writes] == [3, 11]
            assert policy.peer_eofs == int(loss != "tls_error")
            assert policy.peer_eofs_after_suppression == policy.peer_eofs
            assert budget.opens == 2 and life.snapshot.attempts == 2
        finally:
            await life.close()
            assert all(s.close_count == 1 for s in streams)
            assert all(s.active_reads == s.active_tx == 0 for s in streams)
            assert all(s._rx_task.done() and not s._operations for s in sessions)
            assert not [
                t for t in asyncio.all_tasks() if t is not asyncio.current_task()
            ]

    asyncio.run(scenario())
