"""Offline suite acceptance with real session/RX/lifecycle and synthetic TLS."""

import asyncio
import copy
import json
import subprocess

import pytest

from custom_components.hoben.exceptions import HobenInvalidInputError
from custom_components.hoben.transport import TransportTlsError
from custom_components.hoben.v4_experiment import (
    Session300,
    Session300BudgetError,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_session import V4Session
from scripts.session_suite import observe_suite, validate_suite
from tests.test_session_300_probe import PROOF
from tests.test_session_300_runtime import Stream, response


class Harness:
    """Advance monotonic time, delivering only synthetic server events."""

    def __init__(self, mode="recovered"):
        self.now = 0.0
        self.mode = mode
        self.budget = self.policy = None
        self.lives, self.sessions, self.streams = [], [], []
        self.second_streams = []
        self.next_ping = None
        self.first_eof_sent = self.second_eof_sent = False
        self.read_times = []

    def clock(self):
        return self.now

    async def spin(self):
        for _ in range(30):
            await asyncio.sleep(0)

    async def backoff(self, delay):
        assert delay in (1, 2)
        self.now += delay
        await asyncio.sleep(0)

    def make(self, budget, policy):
        # Creation of scenario two must follow complete teardown of one.
        if self.lives:
            assert self.lives[-1]._task.done()
            assert all(s.close_count == 1 for s in self.streams)
        self.budget, self.policy = budget, policy
        self.next_ping = self.now + 30
        owner = self

        class RecordingStream(Stream):
            async def connect(self):
                if (
                    policy is not None
                    and budget.opens > 1
                    and owner.mode == "reopen_failed"
                ):
                    raise TransportTlsError("private")

            async def write(self, payload):
                if payload[0] == 13:
                    owner.read_times.append((id(budget), owner.now))
                await super().write(payload)

        def factory(**kwargs):
            stream = RecordingStream(
                [b"\xff"]
                if self.mode == "first_invalid" and policy is None
                else [response()]
            )
            session = V4Session(
                **kwargs,
                session_300=budget,
                no_pong_after_120=policy,
                transport_factory=lambda: stream,
            )
            self.streams.append(stream)
            self.sessions.append(session)
            if policy is not None:
                self.second_streams.append(stream)
            return session

        life = V4Lifecycle(
            user_guid="b" * 32,
            session_factory=factory,
            retry_delays=(1.0, 2.0),
            sleep=self.backoff,
        )
        self.lives.append(life)
        return life

    async def sleep(self, delay):
        self.now += delay
        if self.policy is None:
            self.streams[-1].queue.put_nowait(b"\x0a")
        else:
            policy = self.policy
            if self.now >= self.next_ping and self.mode != "no_ping":
                if not (
                    len(self.second_streams) > 1 and self.mode == "no_recovery_pong"
                ):
                    self.second_streams[-1].queue.put_nowait(b"\x0a")
                self.next_ping = self.now + 30
            await self.spin()
            elapsed = self.now - policy.first_opened_at
            if (
                elapsed >= 160
                and not self.first_eof_sent
                and self.mode not in {"no_ping", "no_disconnect"}
            ):
                self.first_eof_sent = True
                event = TransportTlsError("private") if self.mode == "tls" else b""
                self.second_streams[0].queue.put_nowait(event)
            if (
                self.mode == "stability_loss"
                and len(self.second_streams) == 2
                and self.budget.accepted_at is not None
                and self.now - self.budget.accepted_at >= 60
                and not self.second_eof_sent
            ):
                self.second_eof_sent = True
                self.second_streams[-1].queue.put_nowait(b"")
        await self.spin()

    def assert_closed(self):
        assert all(s.close_count == 1 for s in self.streams)
        assert all(s.active_reads == s.active_tx == 0 for s in self.streams)
        assert all(
            (s._rx_task is None or s._rx_task.done()) and not s._operations
            for s in self.sessions
        )
        assert all(p[0] in {3, 11, 13} for s in self.streams for p in s.writes)
        for key in {key for key, _ in self.read_times}:
            times = [t for k, t in self.read_times if k == key]
            assert all(b - a >= 60 for a, b in zip(times, times[1:]))
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


async def run_harness(mode="recovered", *, proof=PROOF):
    h = Harness(mode)
    r = await observe_suite(h.make, proof, clock=h.clock, sleep=h.sleep)
    h.assert_closed()
    assert r["boundary_proven"] is False
    assert "private" not in json.dumps(r)
    return h, r


@pytest.mark.parametrize(
    "mode,terminal",
    [
        ("recovered", "verified"),
        ("no_ping", "not_exercised"),
        ("no_disconnect", "no_disconnect"),
        ("tls", "no_disconnect"),
        ("stability_loss", "stability_lost"),
        ("no_recovery_pong", "timeout"),
        ("reopen_failed", "reopen_failed"),
    ],
)
def test_real_shared_engine_evidence_and_failure_classification(
    mode, terminal, deadlines
):
    h, r = asyncio.run(run_harness(mode))
    second = r["session_reconnect_no_pong"]
    assert r["session_300"]["result"] == "continuous_300s"
    assert second["terminal"] == terminal
    assert r["result"] == ("success" if mode == "recovered" else "not_successful")
    assert {d for d, _ in deadlines.contexts} >= {1020, 350, 590, 10}
    if mode == "recovered":
        assert second["failure_phase"] == "none"
        assert second["failure_category"] == "verified"
        assert second["stable_ms"] == 120000
        assert second["recovery_reads_ok"] > 0 and second["recovery_pongs"] > 0
        assert second["pongs_suppressed"] > 0
        assert second["eofs_after_suppression"] == second["peer_eofs"] == 1
        assert second["opens"] == 2 and len(h.lives) == 2
        assert second["eof_after_threshold_ms"] == 40000
    if mode == "tls":
        assert second["peer_eofs"] == 0 and second["opens"] == 2
    assert second["read_slot"] == second["reads"]
    assert second["reads"] <= 10


def test_first_failure_prevents_second_factory_and_records_not_run():
    h, r = asyncio.run(run_harness("first_invalid"))
    assert len(h.lives) == 1 and not h.second_streams
    assert r["result"] == "not_successful"
    assert r["session_reconnect_no_pong"]["result"] == "not_run"
    assert r["session_reconnect_no_pong"]["terminal"] == "first_not_admissible"


def test_budgets_are_fixed_non_resetting_and_type_allowlisted():
    now = [0]
    for kind, cap in [(Session300, 6), (SessionReconnect, 10)]:
        b = kind(clock=lambda: now[0])
        for _ in range(cap):
            b.request()
            with pytest.raises(Session300BudgetError):
                b.request()
            now[0] += 60
        with pytest.raises(Session300BudgetError):
            b.request()
        for generation in range(1, 4):
            b.opening()
            b.accepted(generation)
            b.lost(generation)
        with pytest.raises(Session300BudgetError):
            b.opening()
        for _ in range(256):
            b.receive(b"x" * 4096)
        with pytest.raises(Session300BudgetError):
            b.receive(b"x")

    class Unlisted(SessionReconnect):
        MAX_READS = 1000

    with pytest.raises(HobenInvalidInputError):
        V4Session(session_300=Unlisted())


def test_cancellation_closes_the_active_shared_owner():
    async def scenario():
        h = Harness()
        entered = asyncio.Event()

        async def sleep(delay):
            if h.policy is not None:
                entered.set()
                await asyncio.Future()
            await h.sleep(delay)

        task = asyncio.create_task(
            observe_suite(h.make, PROOF, clock=h.clock, sleep=sleep)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        h.assert_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize("limit", [590, 1020])
def test_real_deadline_cancels_shared_owner_without_leaking(limit, deadlines):
    async def scenario():
        h = Harness()

        async def expire(delay):
            if h.policy is None:
                return await h.sleep(delay)
            target = next(
                ctx for seconds, ctx in deadlines.contexts if seconds == limit
            )
            target.reschedule(asyncio.get_running_loop().time())
            await asyncio.Future()

        operation = observe_suite(h.make, PROOF, clock=h.clock, sleep=expire)
        if limit == 1020:
            with pytest.raises(TimeoutError):
                await operation  # No fabricated report at a hard suite cutoff.
        else:
            r = await operation
            assert r["result"] == "not_successful"
            assert r["session_reconnect_no_pong"]["terminal"] == "timeout"
            assert (
                r["session_reconnect_no_pong"]["failure_phase"]
                == "lifecycle_transition"
            )
            assert r["session_reconnect_no_pong"]["failure_category"] == "timeout"
        h.assert_closed()

    asyncio.run(scenario())


def test_close_failure_cannot_leave_a_successful_suite(monkeypatch):
    close = V4Lifecycle.close

    async def fail_after_close(self):
        await close(self)
        if self in second_lives:
            raise RuntimeError("private")

    second_lives = []
    monkeypatch.setattr(V4Lifecycle, "close", fail_after_close)

    async def scenario():
        h = Harness()

        def factory(budget, policy):
            life = h.make(budget, policy)
            if policy is not None:
                second_lives.append(life)
            return life

        r = await observe_suite(factory, PROOF, clock=h.clock, sleep=h.sleep)
        assert r["result"] == "not_successful"
        assert r["session_reconnect_no_pong"]["terminal"] == "closed"
        assert r["session_reconnect_no_pong"]["failure_phase"] == "teardown"
        assert r["session_reconnect_no_pong"]["failure_category"] == "closed"
        h.assert_closed()

    asyncio.run(scenario())


def test_python_node_closed_schemas_and_adversarial_mutations():
    _, good = asyncio.run(run_harness())
    _, failed = asyncio.run(run_harness("first_invalid"))
    valid = [good, failed] + [
        asyncio.run(run_harness(mode))[1]
        for mode in [
            "no_ping",
            "no_disconnect",
            "tls",
            "stability_loss",
            "reopen_failed",
        ]
    ]
    cases = list(valid)
    for field in good:
        changed = copy.deepcopy(good)
        changed.pop(field)
        cases.append(changed)
    second = good["session_reconnect_no_pong"]
    for field in second:
        changed = copy.deepcopy(good)
        changed["session_reconnect_no_pong"].pop(field)
        cases.append(changed)
    for change in [
        {"boundary_proven": True},
        {"raw_rx": "private"},
        {"guid": "private"},
        {"registers": [17]},
        {"traceback": "private"},
        {"terminal": "private"},
        {"reads": 11},
        {"reads": True},
        {"opens": 4},
        {"stable_ms": 119999},
        {"stable_ms": 120001},
        {"recovery_pongs": 0},
        {"recovery_reads_ok": 0},
        {"eof_after_threshold_ms": 180001},
        {"eof_after_threshold_ms": None},
        {"eof_after_threshold_ms": True},
        {"peer_eofs": 0},
        {"pongs_suppressed": 0},
        {"recovery_generation": 1},
        {"duration_ms": 600001},
        {"run_attempt": 2},
        {"merge_sha": "c" * 40},
        {"rx_bytes_total": 1048577},
    ]:
        changed = copy.deepcopy(good)
        changed["session_reconnect_no_pong"].update(change)
        cases.append(changed)
    for change in [
        {"result": "success"},
        {"duration_ms": 1020001},
        {"secret": "private"},
    ]:
        cases.append(failed | change)
    expected = []
    for r in cases:
        try:
            validate_suite(r, PROOF)
            expected.append(True)
        except (ValueError, TypeError):
            expected.append(False)
    assert all(expected[: len(valid)]) and not any(expected[len(valid) :])
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const api=require('./.github/scripts/session-suite-report.cjs');
const [cases,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(r=>{
  try {api.validate(r,p);return true;} catch(_){return false;}
})));
""",
        ],
        input=json.dumps([cases, PROOF]),
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    assert json.loads(result.stdout) == expected and result.stderr == ""
