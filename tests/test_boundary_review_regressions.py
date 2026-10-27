"""Offline regressions for all four #49 review findings on 51efd1b.

Scripted arrival times distinguish preexisting frames from solicited responses.
No server, household value or real identity is used.
"""

import asyncio
import json

import pytest

from scripts.boundary_analysis import RxRead, analyze_capture
from scripts.boundary_capture import V4_REQUEST, collect_session, run_campaign
from scripts.replay_opened_client_boundary import replay
from tests.test_boundary_observations import (
    FIELDS,
    NOTIFICATION,
    OPENED_PREFIX,
    RESPONSE,
    VirtualStream,
    observe,
)

REJECTED_PREFIXES = (
    OPENED_PREFIX[:8] + b"\xff" + OPENED_PREFIX[9:],
    OPENED_PREFIX[:14] + b"\xff" + OPENED_PREFIX[15:],
    OPENED_PREFIX[:14] + b"0" * 32 + OPENED_PREFIX[46:],
    OPENED_PREFIX[:7]
    + b"\x00\x02"
    + OPENED_PREFIX[9:10]
    + b"\x00"
    + OPENED_PREFIX[11:],
)


@pytest.mark.parametrize("request_number", [1, 2])
@pytest.mark.parametrize("split", range(1, len(RESPONSE)))
def test_preexisting_response_cannot_satisfy_either_request(
    tmp_path, request_number, split
):
    script = [(0.01, OPENED_PREFIX)]
    if request_number == 2:
        script.append((6, RESPONSE))  # The first actual request has a valid response.
    early, late = (4, 6) if request_number == 1 else (24, 27)
    script.extend([(early, RESPONSE[:split]), (late, RESPONSE[split:]), (40, b"")])
    world = VirtualStream(script, replies=False)
    waits = []
    original_wait = world.wait

    async def bounded_wait(task, timeout):
        waits.append(timeout)
        # Fail deterministically rather than hang if a due timer spins.
        assert len(waits) < 20
        assert timeout > 0 or task.done()
        return await original_wait(task, timeout)

    world.wait = bounded_wait
    result, capture, journal = observe(tmp_path, world)
    assert result.requests == result.valid_responses == request_number - 1
    assert result.emission_stop == "invalid_correlation"
    assert result.stop == "peer_eof"
    assert [p for _, p in world.writes].count(V4_REQUEST) == request_number - 1
    assert bytes(capture.data) == OPENED_PREFIX + RESPONSE * request_number
    assert len([e for e in journal if e.get("result") == "correlated_response"]) == (
        request_number - 1
    )
    assert all(e.get("result") != "correlated_exception" for e in journal)


@pytest.mark.parametrize("pause", [0.0, 0.1, 1.0])
@pytest.mark.parametrize("pings", [1, 3])
@pytest.mark.parametrize("prefix_size", [1, 7, 47, 48])
def test_h1_coalesced_opening_read_is_passive(tmp_path, pause, pings, prefix_size):
    script = [(0, b"\x0a" * pings + OPENED_PREFIX[:prefix_size])]
    if prefix_size < 48:
        script.append((1.1, OPENED_PREFIX[prefix_size:]))
    script.extend([(2.5, NOTIFICATION), (3, b"")])
    world = VirtualStream(script)
    result, capture, journal = observe(tmp_path, world, mode="H1", pause=pause)
    assert result.prefix_complete
    assert len(world.writes) == 1 and world.writes[0][1][0] == 3
    assert result.requests == result.pongs_before_open == result.pongs_under_h2 == 0
    assert bytes(capture.data) == b"\x0a" * pings + OPENED_PREFIX + NOTIFICATION
    first_opening_read = next(e for e in journal if e["kind"] == "rx")
    assert all(
        e["ended"] <= first_opening_read["ended"]
        for e in journal
        if e["kind"] == "tx_complete"
    )


@pytest.mark.parametrize("pause", [0.0, 0.1, 1.0])
@pytest.mark.parametrize("pings", [1, 3])
def test_h1_ping_only_reads_before_opening_still_get_pongs(tmp_path, pause, pings):
    world = VirtualStream([(0, b"\x0a" * pings), (1.1, OPENED_PREFIX), (2, b"")])
    result, _, journal = observe(tmp_path, world, mode="H1", pause=pause)
    assert result.pongs_before_open == pings
    assert [p[0] for _, p in world.writes] == [3] + [11] * pings
    opening_read = next(
        e for e in journal if e["kind"] == "rx" and e["offset"] == pings
    )
    assert all(
        e["ended"] < opening_read["ended"]
        for e in journal
        if e["kind"] == "tx_complete"
    )


def test_global_expiry_abandons_second_waiter_as_partial(tmp_path):
    world = VirtualStream(
        [(0.01, OPENED_PREFIX), (5.25, RESPONSE), (31.5, RESPONSE)], replies=False
    )
    result, capture, journal = observe(tmp_path, world, seconds=30)
    assert result.stop == "response_timeout" and result.report["partial"]
    assert result.requests == 2 and result.valid_responses == 1
    assert world.now == 30.01
    assert bytes(capture.data) == OPENED_PREFIX + RESPONSE
    assert world.script == [(31.5, RESPONSE)]
    last_rx = [event for event in journal if event["kind"] == "rx"][-1]
    assert last_rx["status"] == "cancelled_read"
    assert journal[-1]["kind"] == "close_complete"


@pytest.mark.parametrize("mode", ["H1", "H2"])
def test_deadline_without_pending_request_remains_a_complete_window(tmp_path, mode):
    script = [(0.01, OPENED_PREFIX)]
    if mode == "H2":
        script.extend([(5.25, RESPONSE), (25.5, RESPONSE)])
    world = VirtualStream(script, replies=False)
    result, _, _ = observe(tmp_path, world, mode=mode, seconds=30)
    assert result.stop == "observation_budget" and not result.report["partial"]
    assert result.requests == result.valid_responses == (2 if mode == "H2" else 0)


def campaign(tmp_path, script, *, mode="H2", seconds=30):
    worlds = []
    spacings = []

    async def session(capture, **kwargs):
        world = VirtualStream(script, replies=False)
        worlds.append(world)
        return await collect_session(
            capture,
            **kwargs,
            transport_factory=world.factory,
            clock=world.clock,
            sleep=world.sleep,
            waiter=world.wait,
        )

    async def delay(seconds):
        spacings.append(seconds)

    report = asyncio.run(
        run_campaign(
            tmp_path,
            mode=mode,
            user_guid=FIELDS["user_guid"],
            device_guid=FIELDS["device_guid"],
            seconds=seconds,
            session_runner=session,
            sleep=delay,
        )
    )
    assert all(
        w.closed and w.active_reads == 0 and w.maximum_readers <= 1 for w in worlds
    )
    return report, spacings


def test_repeated_pending_global_expiry_stops_campaign(tmp_path):
    report, spacings = campaign(tmp_path, [(0.01, OPENED_PREFIX), (5.25, RESPONSE)])
    assert report["executed_sessions"] == 2 and report["stopped_early"]
    assert report["complete_windows"] == 0 and spacings == [15.0]
    assert all(
        s["stop"] == "response_timeout" and s["partial"] for s in report["sessions"]
    )
    assert all(
        s["v4_requests"] == 2 and s["correlated_responses"] == 1
        for s in report["sessions"]
    )


@pytest.mark.parametrize("prefix", REJECTED_PREFIXES)
@pytest.mark.parametrize("suffix", [b"\x0a", RESPONSE, NOTIFICATION])
@pytest.mark.parametrize("split", [0, 7, 47])
@pytest.mark.parametrize("mode", ["H1", "H2"])
def test_rejected_context_has_no_hypothesis_evidence_in_capture_or_replay(
    tmp_path, prefix, suffix, split, mode
):
    script = [] if split == 0 else [(0.01, prefix[:split])]
    script.append((0.8, prefix[split:] + suffix))
    result, capture, _ = observe(tmp_path, VirtualStream(script), mode=mode)
    assert not result.prefix_complete and result.requests == 0
    assert (
        result.report["h1"]["status"] == result.report["h2"]["status"] == "inconclusive"
    )
    assert result.report["comparison"] == "insufficient_data"
    replayed = replay(capture.directory)
    assert replayed["h1"] == result.report["h1"]
    assert replayed["h2"] == result.report["h2"]
    assert replayed["comparison"] == "insufficient_data"
    assert bytes(capture.data) == prefix + suffix
    assert (capture.directory / "rx.bin").read_bytes() == prefix + suffix


@pytest.mark.parametrize("prefix", REJECTED_PREFIXES)
def test_offline_analysis_cannot_promote_a_rejected_opening(prefix):
    data = prefix + RESPONSE
    reads = [
        RxRead(0, 0, 4096, 48, 0, 0.1, None),
        RxRead(1, 48, 4096, len(RESPONSE), 0.1, 2, 0.1),
    ]
    report = analyze_capture(data, reads, 0)
    assert report["h1"]["status"] == report["h2"]["status"] == "inconclusive"
    assert report["comparison"] == "insufficient_data"


@pytest.mark.parametrize("prefix", REJECTED_PREFIXES)
def test_rejected_sessions_do_not_contaminate_campaign_hypotheses(tmp_path, prefix):
    report, spacings = campaign(tmp_path, [(0.01, prefix + RESPONSE)])
    assert report["h1_status_counts"] == report["h2_status_counts"] == {}
    assert report["comparison_counts"] == {}
    assert report["executed_sessions"] == 2 and report["stopped_early"]
    assert report["complete_windows"] == 0 and spacings == [15.0]
    assert report["eligible_sessions"] == 0 and report["excluded_sessions"] == 2


def test_saved_valid_prefix_requires_original_acceptance_for_replay(tmp_path):
    result, capture, journal = observe(
        tmp_path, VirtualStream([(0.01, OPENED_PREFIX), (2, NOTIFICATION), (3, b"")])
    )
    assert result.report["opening_context"]["eligible"]
    original = bytes(capture.data)
    path = capture.directory / "journal.jsonl"
    path.write_text(
        "".join(
            json.dumps(e) + "\n" for e in journal if e["kind"] != "opening_accepted"
        )
    )
    report = replay(capture.directory)
    assert report["opening_context"] == {
        "eligible": False,
        "status": "unaccepted_opening_prefix",
    }
    assert report["h1"]["status"] == report["h2"]["status"] == "inconclusive"
    assert report["comparison"] == "insufficient_data"
    assert (capture.directory / "rx.bin").read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("prefix", REJECTED_PREFIXES)
def test_replay_revalidates_bytes_even_if_acceptance_event_claims_success(
    tmp_path, prefix
):
    _, capture, journal = observe(tmp_path, VirtualStream([(0.01, prefix + RESPONSE)]))
    rx = next(e for e in journal if e["kind"] == "rx")
    journal.append(
        {
            "kind": "opening_accepted",
            "offset": 0,
            "read_index": rx["index"],
            "received_at": rx["ended"],
        }
    )
    (capture.directory / "journal.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in journal)
    )
    report = replay(capture.directory)
    assert not report["opening_context"]["eligible"]
    assert report["h1"]["status"] == report["h2"]["status"] == "inconclusive"
    assert report["comparison"] == "insufficient_data"


@pytest.mark.parametrize(
    "replacement",
    [
        {"offset": True},
        {"offset": 1},
        {"read_index": True},
        {"read_index": 1},
        {"received_at": float("nan")},
        {"received_at": 1},
    ],
)
def test_replay_refuses_inconsistent_acceptance_journal(tmp_path, replacement):
    _, capture, journal = observe(
        tmp_path, VirtualStream([(0.01, OPENED_PREFIX), (2, b"")])
    )
    accepted = next(e for e in journal if e["kind"] == "opening_accepted")
    accepted.update(replacement)
    (capture.directory / "journal.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in journal)
    )
    with pytest.raises(ValueError, match="private opening acceptance"):
        replay(capture.directory)


@pytest.mark.parametrize("prefix_size", [1, 7, 47])
def test_incomplete_prefix_is_excluded_from_analysis_and_campaign(
    tmp_path, prefix_size
):
    report, spacings = campaign(
        tmp_path, [(0.01, OPENED_PREFIX[:prefix_size]), (2, b"")]
    )
    assert report["executed_sessions"] == report["excluded_sessions"] == 2
    assert report["eligible_sessions"] == report["complete_windows"] == 0
    assert report["stopped_early"] and spacings == [15.0]
    assert report["opening_context_counts"] == {"incomplete_opening_prefix": 2}
    assert report["h1_status_counts"] == report["h2_status_counts"] == {}
    assert report["received_size_distribution_bytes"]["count"] == 0


def test_mixed_campaign_counts_only_accepted_contexts(tmp_path):
    calls = []

    async def session(capture, **kwargs):
        script = (
            [(0.01, REJECTED_PREFIXES[0] + RESPONSE * 3)]
            if not calls
            else [(0.01, OPENED_PREFIX), (2, NOTIFICATION), (3, b"")]
        )
        calls.append(script)
        world = VirtualStream(script, replies=False)
        return await collect_session(
            capture,
            **kwargs,
            transport_factory=world.factory,
            clock=world.clock,
            sleep=world.sleep,
            waiter=world.wait,
        )

    async def delay(seconds):
        assert seconds == 15.0

    report = asyncio.run(
        run_campaign(
            tmp_path,
            mode="H1",
            user_guid=FIELDS["user_guid"],
            device_guid=FIELDS["device_guid"],
            session_runner=session,
            sleep=delay,
        )
    )
    assert report["schema"] == 2
    assert report["executed_sessions"] == 6 and not report["stopped_early"]
    assert report["eligible_sessions"] == 5 and report["excluded_sessions"] == 1
    assert report["opening_context_counts"] == {
        "unsupported_opening": 1,
        "accepted_v4_prefix": 5,
    }
    assert report["h1_status_counts"] == report["h2_status_counts"] == {"compatible": 5}
    assert report["comparison_counts"] == {"compatible_with_both": 5}
    assert report["median_client_gap_distribution_seconds"]["count"] == 5
    assert report["received_size_distribution_bytes"] == {
        "count": 5,
        "min": len(OPENED_PREFIX + NOTIFICATION),
        "median": len(OPENED_PREFIX + NOTIFICATION),
        "max": len(OPENED_PREFIX + NOTIFICATION),
    }
