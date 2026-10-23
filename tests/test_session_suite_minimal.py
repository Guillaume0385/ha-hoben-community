"""Minimal no-Pong path through the real collector, lifecycle and RX owner."""

import asyncio
import json

import pytest

from custom_components.hoben.v4_no_pong import NoPongAfter120
from scripts.session_suite import observe_suite
from tests.test_session_300_probe import PROOF
from tests.test_session_300_runtime import response
from tests.test_session_suite import Harness


class TimedHarness(Harness):
    """Deliver synthetic events at exact times relative to strict acceptance."""

    def __init__(
        self,
        events=(),
        *,
        mode="no_disconnect",
        opening_delay=0,
        bad_read=False,
        eof_on_read=False,
    ):
        super().__init__(mode)
        self.events = list(events)
        self.opening_delay, self.bad_read = opening_delay, bad_read
        self.eof_on_read = eof_on_read
        # The test owns the event schedule, not the inherited EOF at T+160.
        self.first_eof_sent = self.second_eof_sent = True

    def make(self, budget, policy):
        life = super().make(budget, policy)
        factory = life._factory

        def timed_factory(**kwargs):
            session = factory(**kwargs)
            if policy is not None:
                if len(self.second_streams) == 1:
                    self.now += self.opening_delay
                elif self.bad_read:
                    # Wrong transaction ID on a fresh session's solicited read.
                    data = bytearray(response())
                    data[1] = 0
                    self.second_streams[-1].chunks = (bytes(data),)
                elif self.eof_on_read:
                    self.second_streams[-1].chunks = (response(), b"")
            return session

        life._factory = timed_factory
        return life

    async def sleep(self, delay):
        if self.policy is not None and self.events:
            at, _, _ = self.events[0]
            delay = min(delay, max(0, self.policy.first_opened_at + at - self.now))
        await super().sleep(delay)
        while (
            self.policy is not None
            and self.events
            and self.now >= self.policy.first_opened_at + self.events[0][0]
        ):
            _, index, data = self.events.pop(0)
            self.second_streams[index].queue.put_nowait(data)
            await self.spin()


async def observe(h):
    report = await observe_suite(h.make, PROOF, clock=h.clock, sleep=h.sleep)
    h.assert_closed()
    assert report["session_300"]["result"] == "continuous_300s"
    assert report["schema"] == report["session_reconnect_no_pong"]["schema"] == 2
    assert not report["boundary_proven"]
    assert "private" not in json.dumps(report)
    return report, report["session_reconnect_no_pong"]


@pytest.mark.parametrize("eof_at", [160, 238, 238.5, 238.123])
def test_real_eof_reopens_before_240_and_runs_120s_on_new_generation(
    eof_at, monkeypatch
):
    h = TimedHarness([(eof_at, 0, b"")])
    suppress = NoPongAfter120.suppress
    decisions = []

    def record(policy, generation):
        result = suppress(policy, generation)
        if policy is h.policy:
            decisions.append((h.now - policy.first_opened_at, generation, result))
        return result

    monkeypatch.setattr(NoPongAfter120, "suppress", record)
    report, second = asyncio.run(observe(h))
    assert report["result"] == "success" and second["terminal"] == "verified"
    assert second["peer_eofs"] == second["eofs_after_suppression"] == 1
    assert second["opens"] == second["recovery_generation"] == 2
    assert second["stable_ms"] == 120000
    assert second["recovery_reads_ok"] > 0 and second["recovery_pongs"] > 0
    assert second["duration_ms"] <= 360000
    assert h.now - h.policy.first_opened_at == pytest.approx(eof_at + 1 + 120)
    assert all(not suppressed for at, _, suppressed in decisions if at < 120)
    assert (120, 1, True) in decisions
    assert all(
        suppressed for at, gen, suppressed in decisions if at >= 120 and gen == 1
    )
    assert any(gen == 2 for _, gen, _ in decisions)
    assert all(not suppressed for _, gen, suppressed in decisions if gen == 2)


@pytest.mark.parametrize(
    "events,terminal",
    [
        ([], "no_disconnect"),
        ([(239, 0, b"")], "reopen_failed"),
        ([(240, 0, b"")], "reopen_failed"),
    ],
)
def test_eof_and_new_acceptance_must_both_precede_240(events, terminal):
    h = TimedHarness(events)
    report, second = asyncio.run(observe(h))
    assert report["result"] == "not_successful"
    assert second["terminal"] == terminal and second["stable_ms"] == 0
    assert h.now - h.policy.first_opened_at <= 241


@pytest.mark.parametrize(
    "events,terminal",
    [
        ([(151, 0, b"\x05")], "protocol"),
        ([(151, 0, b"\x0e"), (160, 0, b"")], "protocol"),
        ([(160, 0, b""), (170, 1, response())], "stability_lost"),
        ([(160, 0, b""), (220, 1, b"")], "stability_lost"),
        ([(160, 0, b""), (281, 1, b"")], "stability_lost"),
    ],
)
def test_partial_unsolicited_and_second_loss_never_become_success(events, terminal):
    report, second = asyncio.run(observe(TimedHarness(events)))
    assert report["result"] == "not_successful" and second["terminal"] == terminal
    if events[0][2] == b"\x05":
        assert second["peer_eofs"] == second["reconnections"] == 0
        assert second["message_category"] == "close_client"


def test_corrupted_response_on_recovered_session_is_not_a_valid_read():
    report, second = asyncio.run(observe(TimedHarness([(160, 0, b"")], bad_read=True)))
    assert report["result"] == "not_successful" and second["terminal"] == "protocol"
    assert second["recovery_reads_ok"] == 0
    assert second["failure_phase"] == "response_validation"


def test_recovery_loss_while_a_valid_read_returns_is_not_an_internal_error():
    h = TimedHarness([(160, 0, b"")], eof_on_read=True)
    report, second = asyncio.run(observe(h))
    assert report["result"] == "not_successful"
    assert second["terminal"] == "stability_lost"
    assert second["recovery_reads_ok"] == 0


@pytest.mark.parametrize(
    "opening_delay,mode", [(0, "no_recovery_pong"), (350, "no_disconnect")]
)
def test_missing_pong_or_insufficient_remaining_process_budget_is_not_stability(
    opening_delay, mode
):
    h = TimedHarness([(160, 0, b"")], opening_delay=opening_delay, mode=mode)
    report, second = asyncio.run(observe(h))
    assert report["result"] == "not_successful" and second["terminal"] == "timeout"
    assert second["duration_ms"] <= 590000
    assert h.now - h.policy.first_opened_at <= 360
    if not opening_delay:
        assert h.now - h.policy.first_opened_at == 360
        assert second["recovery_pongs"] == 0
    else:
        assert second["stable_ms"] < 120000
