"""Deterministic regressions for #54's scheduling and atomic H2 batch review.

Only virtual arrival/completion times and synthetic protocol bytes are used.
"""

import pytest

from custom_components.hoben.modbus import encode_mbap
from scripts.boundary_capture import V4_REQUEST
from tests.test_boundary_observations import (
    OPENED_PREFIX,
    RESPONSE,
    VirtualStream,
    observe,
)


def delay_completed_read(world, *, arrival, resumed):
    """Complete RX on time, but resume the collector after its absolute budget.

    Returning False models asyncio.wait's timer winning while its reader is
    already done. The journal records arrival, not the later scheduling time.
    """
    wait = world.wait
    delayed = False

    async def stalled(task, timeout):
        nonlocal delayed
        done = await wait(task, timeout)
        if done and world.now == arrival and not delayed:
            delayed = True
            world.now = resumed
            return False
        return done

    world.wait = stalled


@pytest.mark.parametrize("mode", ["H1", "H2"])
def test_timely_opening_survives_late_collector_scheduling(tmp_path, mode):
    world = VirtualStream([(0.01, OPENED_PREFIX)])
    delay_completed_read(world, arrival=0.01, resumed=15.01)
    result, capture, journal = observe(tmp_path, world, mode=mode)
    assert result.prefix_complete
    assert result.stop == "observation_budget" and not result.report["partial"]
    accepted = next(e for e in journal if e["kind"] == "opening_accepted")
    assert accepted["received_at"] == capture.reads[0].ended == 0.01
    assert result.requests == result.valid_responses == (2 if mode == "H2" else 0)


@pytest.mark.parametrize("ping", [b"", b"\x0a"])
def test_timely_final_response_is_drained_after_the_global_deadline(tmp_path, ping):
    world = VirtualStream(
        [(0.01, OPENED_PREFIX), (5.25, RESPONSE), (25.5, ping + RESPONSE)],
        replies=False,
    )
    delay_completed_read(world, arrival=25.5, resumed=30.02)
    result, capture, journal = observe(tmp_path, world, seconds=30)
    assert result.requests == result.valid_responses == 2
    assert result.stop == "observation_budget" and not result.report["partial"]
    correlations = [e for e in journal if e.get("result") == "correlated_response"]
    assert [e["received_at"] for e in correlations] == [5.25, 25.5]
    assert bytes(capture.data) == OPENED_PREFIX + RESPONSE + ping + RESPONSE
    assert all(at < 30.01 for at, _ in world.writes)
    assert result.pongs_under_h2 == 0


def test_timely_eof_is_not_relabelled_as_a_complete_window(tmp_path):
    world = VirtualStream([(0.01, OPENED_PREFIX), (30, b"")])
    delay_completed_read(world, arrival=30, resumed=30.02)
    result, capture, _ = observe(tmp_path, world, mode="H1", seconds=30)
    assert result.stop == "peer_eof" and result.report["partial"]
    assert capture.reads[-1].ended == 30


def test_opening_completed_after_its_budget_is_saved_but_not_accepted(tmp_path):
    world = VirtualStream([(15.5, OPENED_PREFIX)], replies=False)
    wait = world.wait

    async def late_completion(task, timeout):
        return await wait(task, timeout + 1)

    world.wait = late_completion
    result, capture, _ = observe(tmp_path, world, mode="H1")
    assert result.stop == "opening_timeout" and not result.prefix_complete
    assert bytes(capture.data) == OPENED_PREFIX
    assert result.requests == 0 and len(world.writes) == 1


INVALID_RESPONSES = (
    RESPONSE,
    b"\x0e" + encode_mbap(17, 1, b"\x04\x28" + bytes(40)),
    b"\x0e" + encode_mbap(0xFFFF, 2, b"\x04\x28" + bytes(40)),
    b"\x0e" + encode_mbap(0xFFFF, 1, b"\x03\x28" + bytes(40)),
    b"\x0e" + encode_mbap(0xFFFF, 1, b"\x04\x02\x00\x00"),
    b"\x0e" + encode_mbap(0xFFFF, 1, b"\x04\x03\x00\x00"),
)


@pytest.mark.parametrize("response", INVALID_RESPONSES)
@pytest.mark.parametrize("ping_first", [True, False])
@pytest.mark.parametrize("pending", [False, True])
def test_invalid_response_batch_emits_no_pong_in_either_order(
    tmp_path, response, ping_first, pending
):
    # A valid response is unsolicited without a waiter; with a waiter, append
    # a duplicate so the complete batch still fails correlation atomically.
    if pending and response == RESPONSE:
        response += RESPONSE
    batch = b"\x0a" + response if ping_first else response + b"\x0a"
    at = 6 if pending else 2
    world = VirtualStream([(0.01, OPENED_PREFIX), (at, batch), (7, b"")], replies=False)
    result, capture, journal = observe(tmp_path, world)
    assert result.emission_stop == "invalid_correlation"
    assert result.stop == ("invalid_correlation" if pending else "peer_eof")
    assert result.pongs_under_h2 == result.valid_responses == 0
    assert [p[0] for _, p in world.writes] == ([3, 13] if pending else [3])
    assert [p for _, p in world.writes].count(V4_REQUEST) == int(pending)
    assert bytes(capture.data) == OPENED_PREFIX + batch
    assert any(e.get("result") == "invalid_correlation" for e in journal)
    assert not any(e.get("result") == "correlated_response" for e in journal)


def test_valid_response_batch_is_committed_before_replying_to_its_ping(tmp_path):
    world = VirtualStream(
        [(0.01, OPENED_PREFIX), (6, b"\x0a" + RESPONSE), (7, b"")],
        replies=False,
    )
    result, _, journal = observe(tmp_path, world)
    assert result.valid_responses == result.requests == result.pongs_under_h2 == 1
    correlated = next(
        i for i, e in enumerate(journal) if e.get("result") == "correlated_response"
    )
    pong = next(
        i
        for i, e in enumerate(journal)
        if e["kind"] == "tx_attempt" and e["category"] == "pong_h2"
    )
    assert correlated < pong
