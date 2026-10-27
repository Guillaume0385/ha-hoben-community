"""Offline #49 campaign-stop regressions against the reviewed f53512a HEAD.

RX completion and a healthy H2 exchange are separate contracts. All bytes,
identities and arrival times below are synthetic; no network is involved.
"""

import asyncio
import json

import pytest

from scripts.boundary_capture import V4_REQUEST, collect_session, run_campaign
from tests.test_boundary_observations import (
    FIELDS,
    NOTIFICATION,
    OPENED_PREFIX,
    PRIVATE,
    RESPONSE,
    VirtualStream,
)

SCENARIOS = (
    "pending_first_eof",
    "pending_second_eof",
    "unsolicited_before_budget",
    "unsolicited_before_eof",
    "unsupported_prefix_budget",
    "unsupported_prefix_eof",
    "invalid_mbap_prefix_budget",
    "unsolicited_between_budget",
    "unsolicited_between_eof",
    "unsupported_between_budget",
    "unsupported_between_eof",
    "invalid_mbap_between_eof",
)


def error_script(scenario):
    """Keep receiving after a non-pending anomaly; never auto-reply to FFFF."""
    if scenario == "pending_first_eof":
        return [(0.01, OPENED_PREFIX), (8, b"")]
    if scenario == "pending_second_eof":
        return [(0.01, OPENED_PREFIX), (6, RESPONSE), (28, b"")]
    anomaly = (
        RESPONSE
        if scenario.startswith("unsolicited")
        else b"\xff"
        if scenario.startswith("unsupported")
        else b"\x0e\xff\xff\x00\x01\x00\x2b"
    )
    script = [(0.01, OPENED_PREFIX)]
    if "_prefix_" in scenario:
        script = [(0.01, OPENED_PREFIX + anomaly)]
    elif "_between_" in scenario:
        script.extend([(6, RESPONSE), (10, anomaly)])
    else:
        script.append((2, anomaly))
    script.extend([(11, NOTIFICATION + PRIVATE), (12, b"\x0a")])
    if scenario.endswith("_eof"):
        script.append((13, b""))
    return script


def campaign(tmp_path, script_factory, *, mode="H2"):
    """Run the real collector and campaign; verify every private capture/cleanup."""
    worlds, outcomes, calls, spacings = [], [], [], []

    async def session(capture, **kwargs):
        script, replies = script_factory(len(worlds), kwargs["mode"])
        world = VirtualStream(script, replies=replies)
        worlds.append(world)
        calls.append((kwargs["mode"], kwargs["pause"], kwargs["repetition"]))
        tasks_before = asyncio.all_tasks()
        outcome = await collect_session(
            capture,
            **kwargs,
            transport_factory=world.factory,
            clock=world.clock,
            sleep=world.sleep,
            waiter=world.wait,
        )
        assert asyncio.all_tasks() == tasks_before
        assert world.closed and world.connects == 1
        assert world.active_reads == 0 and world.pending is None
        assert world.maximum_readers == 1
        assert (capture.directory / "rx.bin").read_bytes() == b"".join(world.received)
        assert bytes(capture.data) == b"".join(world.received)
        assert (
            json.loads((capture.directory / "analysis.json").read_text())
            == outcome.report
        )
        assert capture.directory.stat().st_mode & 0o777 == 0o700
        assert all(
            p.stat().st_mode & 0o777 == 0o600 for p in capture.directory.iterdir()
        )
        outcomes.append(outcome)
        return outcome

    async def delay(seconds):
        spacings.append(seconds)

    report = asyncio.run(
        run_campaign(
            tmp_path,
            mode=mode,
            user_guid=FIELDS["user_guid"],
            device_guid=FIELDS["device_guid"],
            seconds=30,
            session_runner=session,
            sleep=delay,
        )
    )
    assert len(worlds) == report["executed_sessions"]
    assert spacings == [15.0] * (len(worlds) - 1)
    assert json.loads((tmp_path / "campaign.json").read_text()) == report
    public = json.dumps(report) + repr(outcomes)
    for secret in (
        FIELDS["user_guid"],
        OPENED_PREFIX[14:46].decode(),
        PRIVATE.decode(),
    ):
        assert secret not in public
    return report, worlds, calls


@pytest.mark.parametrize("mode", ["H2", "both"])
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_two_consecutive_h2_errors_stop_before_another_transport(
    tmp_path, mode, scenario
):
    def script_factory(index, selected):
        if selected == "H1":
            return [(0.01, OPENED_PREFIX)], False
        return error_script(scenario), False

    report, worlds, calls = campaign(tmp_path, script_factory, mode=mode)
    prior_h1 = 6 if mode == "both" else 0
    assert report["executed_sessions"] == prior_h1 + 2
    assert report["stopped_early"]
    assert calls[prior_h1:] == [("H2", 0.0, 1), ("H2", 0.0, 2)]
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_dir()) == [
        f"session-{i:02d}" for i in range(1, prior_h1 + 3)
    ]
    sessions = report["sessions"][prior_h1:]
    for session, world in zip(sessions, worlds[prior_h1:], strict=True):
        expected_requests = (
            2
            if scenario == "pending_second_eof"
            else 1
            if "pending" in scenario or "_between_" in scenario
            else 0
        )
        assert session["v4_requests"] == expected_requests
        assert session["correlated_responses"] == (
            1 if expected_requests == 2 or "_between_" in scenario else 0
        )
        assert [packet for _, packet in world.writes] == [
            world.writes[0][1],
            *([V4_REQUEST] * expected_requests),
        ]
        assert world.writes[0][1][0] == 3
        if scenario.startswith("pending"):
            assert session["stop"] == "pending_response_eof"
            assert session["emission_stop"] is None
        else:
            expected_error = (
                "invalid_correlation"
                if scenario.startswith("unsolicited")
                else "unsupported_type_h2"
                if scenario.startswith("unsupported")
                else "invalid_mbap_h2"
            )
            assert session["emission_stop"] == expected_error
            assert session["stop"] == (
                "peer_eof" if scenario.endswith("_eof") else "observation_budget"
            )
            assert b"".join(world.received).endswith(NOTIFICATION + PRIVATE + b"\x0a")
        # A fully collected RX window stays complete even when H2 failed earlier.
        assert session["partial"] is scenario.endswith("_eof")
    assert report["complete_windows"] == prior_h1 + (
        0 if scenario.endswith("_eof") else 2
    )


@pytest.mark.parametrize("eof", [False, True])
def test_healthy_session_resets_error_streak_before_two_distinct_errors(tmp_path, eof):
    def script_factory(index, selected):
        if index == 1 or index >= 4:
            return [(0.01, OPENED_PREFIX)] + ([(28, b"")] if eof else []), True
        scenario = (
            "unsupported_prefix_budget",
            "",
            "pending_first_eof",
            "unsolicited_before_eof",
        )[index]
        return error_script(scenario), False

    report, worlds, _ = campaign(tmp_path, script_factory)
    assert report["executed_sessions"] == len(worlds) == 4
    assert report["stopped_early"]
    assert report["sessions"][1]["emission_stop"] is None
    assert (
        report["sessions"][1]["v4_requests"]
        == report["sessions"][1]["correlated_responses"]
        == 2
    )
    assert report["sessions"][1]["stop"] == (
        "peer_eof" if eof else "observation_budget"
    )


@pytest.mark.parametrize("mode", ["H1", "both"])
def test_passive_h1_eof_is_a_limit_without_a_read_error(tmp_path, mode):
    def script_factory(index, selected):
        if selected == "H1":
            return [(0.01, OPENED_PREFIX + b"\xff" + PRIVATE), (8, b"")], False
        return [(0.01, OPENED_PREFIX)], True

    report, worlds, _ = campaign(tmp_path, script_factory, mode=mode)
    assert (
        report["executed_sessions"]
        == report["planned_sessions"]
        == (12 if mode == "both" else 6)
    )
    assert not report["stopped_early"]
    assert all(
        s["stop"] == "peer_eof" and s["partial"] and s["emission_stop"] is None
        for s in report["sessions"][:6]
    )
    assert all(len(w.writes) == 1 for w in worlds[:6])


@pytest.mark.parametrize("eof", [False, True])
def test_six_healthy_h2_sessions_keep_all_pause_conditions(tmp_path, eof):
    report, worlds, calls = campaign(
        tmp_path,
        lambda index, selected: (
            [(0.01, OPENED_PREFIX)] + ([(28, b"")] if eof else []),
            True,
        ),
    )
    assert report["executed_sessions"] == len(worlds) == 6
    assert not report["stopped_early"]
    assert calls == [
        ("H2", pause, repetition) for pause in (0.0, 0.1, 1.0) for repetition in (1, 2)
    ]
    assert all(
        s["v4_requests"] == s["correlated_responses"] == 2
        and s["emission_stop"] is None
        for s in report["sessions"]
    )


def test_error_streak_survives_mode_transition_without_starting_another_session(
    tmp_path,
):
    def script_factory(index, selected):
        if index == 5:
            return [
                (0.01, OPENED_PREFIX),
                (2, RuntimeError("SYNTHETIC-PRIVATE failure")),
            ], False
        if selected == "H2":
            return error_script("unsupported_prefix_budget"), False
        return [(0.01, OPENED_PREFIX)], False

    report, worlds, calls = campaign(tmp_path, script_factory, mode="both")
    assert report["executed_sessions"] == len(worlds) == 7
    assert report["stopped_early"]
    assert [selected for selected, _, _ in calls] == ["H1"] * 6 + ["H2"]
    assert report["sessions"][5]["stop"] == "transport_or_capture_error"


def test_terminal_close_without_pending_response_is_not_a_framing_failure(tmp_path):
    report, _, _ = campaign(
        tmp_path,
        lambda index, selected: (
            [(0.01, OPENED_PREFIX + b"\x05\x02"), (8, b"")],
            False,
        ),
    )
    assert report["executed_sessions"] == 6 and not report["stopped_early"]
    assert all(
        s["stop"] == "peer_eof" and s["emission_stop"] == "terminal_close_h2"
        for s in report["sessions"]
    )
