"""Scheduler, isolation and report tests; no network, secret or wall-clock wait."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from custom_components.hoben.exceptions import HobenProtocolError, HobenTransportError
from custom_components.hoben.v4_experiment import Session300
from custom_components.hoben.v4_session import SessionState
from scripts import launch_session_300 as launcher
from scripts.run_session_300 import context_proof, observe, validate_report

PROOF = {
    "merge_sha": "a" * 40,
    "candidate_sha": "b" * 40,
    "run_id": 123,
    "run_attempt": 1,
    "pr_number": 89,
}


class Clock:
    now = 0

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        self.now += delay
        await asyncio.sleep(0)


class Lifecycle:
    """A scheduler double, not a protocol implementation."""

    def __init__(self, budget, mode="healthy"):
        self.budget, self.mode = budget, mode
        self.snapshot = SimpleNamespace(attempts=1)
        self.state = SessionState.DISCONNECTED
        self.closed = False
        self.started = asyncio.Event()

    async def connect(self):
        self.budget.opening()
        self.budget.accepted(self.budget.opens)
        self.state = SessionState.CONNECTED

    async def wait_stopped(self):
        await asyncio.Future()

    async def wait_connected(self):
        if self.state is SessionState.RECONNECTING:
            self.budget.opening()
            self.budget.accepted(self.budget.opens)
            self.snapshot.attempts += 1
            self.state = SessionState.CONNECTED

    async def request_v4_data(self, *, timeout):
        assert 0 < timeout <= 30
        self.budget.request()
        self.started.set()
        if self.mode == "cancel":
            await asyncio.Future()
        if self.mode == "invalid":
            raise HobenProtocolError()
        if self.mode == "reconnect" and self.budget.requests == 2:
            self.state = SessionState.RECONNECTING
            raise HobenTransportError()
        self.budget.responses += 1
        return {"registers": "synthetic-private-register-marker"}

    async def close(self):
        self.closed = True
        self.state = SessionState.CLOSED


@pytest.mark.parametrize(
    "mode,category",
    [
        ("healthy", "continuous_300s"),
        ("reconnect", "reconnected"),
        ("invalid", "inconclusive"),
    ],
)
def test_300_seconds_with_injected_clock_and_recovery_categories(
    mode, category, deadlines
):
    async def scenario():
        clock = Clock()
        budget = Session300(clock=clock)
        life = Lifecycle(budget, mode)
        report = await observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        assert report["result"] == category
        assert report["duration_ms"] == (0 if mode == "invalid" else 300000)
        assert budget.requests == (1 if mode == "invalid" else 5)
        assert report["reconnections"] == int(mode == "reconnect")
        assert report["reads_failed"] == int(mode != "healthy")
        assert life.closed
        assert {delay for delay, _ in deadlines.contexts} == {350, 10}
        assert report["boundary_proven"] is False
        assert "synthetic-private" not in json.dumps(report)
        return report

    asyncio.run(scenario())


def test_observation_timeout_and_cancellation_always_close(deadlines):
    async def scenario():
        clock = Clock()
        budget, life = Session300(clock=clock), None
        life = Lifecycle(budget)
        report = await observe(life, budget, PROOF, clock=clock, sleep=deadlines.expire)
        assert report["result"] == "interrupted" and report["terminal"] == "timeout"
        assert life.closed
        budget = Session300(clock=clock)
        life = Lifecycle(budget, "cancel")
        task = asyncio.create_task(
            observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        )
        await life.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert life.closed
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key,value",
    [
        ("temperature", 12),
        ("registers", [17]),
        ("terminal", "private-exception"),
        ("opens", 4),
        ("reads", 7),
        ("duration_ms", 299999),
        ("boundary_proven", True),
        ("schema", True),
        ("pr_number", 90),
        ("merge_sha", "c" * 40),
    ],
)
def test_report_rejects_private_or_inconsistent_data(key, value):
    async def make():
        clock = Clock()
        budget = Session300(clock=clock)
        return await observe(
            Lifecycle(budget), budget, PROOF, clock=clock, sleep=clock.sleep
        )

    report = asyncio.run(make())
    report[key] = value
    with pytest.raises(ValueError, match="^invalid_session_300_report$"):
        validate_report(report, PROOF)


def test_live_context_is_exact_and_launcher_strips_runner_capabilities(monkeypatch):
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_WORKFLOW_SHA": "a" * 40,
        "SESSION300_APPROVED_SHA": "a" * 40,
        "SESSION300_CANDIDATE_SHA": "b" * 40,
        "SESSION300_APPROVED_PR": "89",
        "SESSION300_PHASE": "live",
        "GITHUB_WORKFLOW_REF": (
            "Guillaume0385/ha-hoben-community/.github/workflows/"
            "hoben-session-300.yml@refs/heads/experimental"
        ),
    }
    assert context_proof(env) == PROOF
    for key in list(env):
        bad = dict(env)
        bad[key] = "untrusted"
        with pytest.raises((ValueError, TypeError)):
            context_proof(bad)
    source = env | {
        "GITHUB_TOKEN": "private",
        "ACTIONS_RUNTIME_TOKEN": "private",
        "GITHUB_OUTPUT": "private",
        "PYTHONPATH": "untrusted",
        "HOBEN_USER_GUID": "synthetic-private-identity",
    }
    child = launcher.collector_environment(source)
    assert (
        not {"GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "GITHUB_OUTPUT", "PYTHONPATH"}
        & child.keys()
    )
    assert child["HOBEN_USER_GUID"] == "synthetic-private-identity"

    def run(command, **kwargs):
        assert command[1] == "-I"
        assert kwargs["timeout"] == 360
        assert kwargs["stdout"] is launcher.subprocess.DEVNULL
        assert kwargs["stderr"] is launcher.subprocess.DEVNULL
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main() == 0


def test_probe_uses_real_lifecycle_and_session_with_only_an_offline_transport():
    from custom_components.hoben.transport import TransportTlsError
    from custom_components.hoben.v4_lifecycle import V4Lifecycle
    from custom_components.hoben.v4_session import V4Session
    from tests.test_session_300_runtime import Stream, response

    async def scenario():
        clock = Clock()
        budget = Session300(clock=clock)
        streams, sessions = [], []

        def factory(**kwargs):
            stream = Stream([response()])
            if not streams:
                # First wire response is followed by a real transport loss.
                stream.chunks = [response(), TransportTlsError("synthetic-private")]
            streams.append(stream)
            session = V4Session(
                **kwargs, transport_factory=lambda: stream, session_300=budget
            )
            sessions.append(session)
            return session

        life = V4Lifecycle(
            user_guid="b" * 32,
            retry_delays=(1, 2),
            session_factory=factory,
            sleep=clock.sleep,
        )
        report = await observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        assert report["result"] == "reconnected"
        assert report["duration_ms"] == 300000
        assert budget.opens == 2
        assert len(streams) == 2 and all(s.close_count == 1 for s in streams)
        assert all(s._pending_read is None and s._rx_task.done() for s in sessions)
        assert all(not s._operations for s in sessions)
        assert report["reads"] <= 6
        assert all(s.active_reads == s.active_tx == 0 for s in streams)

    asyncio.run(scenario())


def test_authorization_required_is_not_reported_as_a_transport_failure():
    from custom_components.hoben.exceptions import HobenAuthorizationRequiredError

    async def scenario():
        clock = Clock()
        budget = Session300(clock=clock)
        life = Lifecycle(budget)

        async def connect():
            budget.opening()
            raise HobenAuthorizationRequiredError()

        life.connect = connect
        report = await observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        assert report["result"] == "inconclusive"
        assert report["terminal"] == "authorization"
        assert life.closed and report["reads"] == 0

    asyncio.run(scenario())


def test_loss_at_window_end_cannot_use_a_stale_connected_snapshot():
    async def scenario():
        clock = Clock()
        budget = Session300(clock=clock)
        life = Lifecycle(budget)

        async def sleep(delay):
            await clock.sleep(delay)
            if clock() >= 300:
                budget.lost(budget.opens)
                # The supervisor has not yet updated its CONNECTED snapshot.

        report = await observe(life, budget, PROOF, clock=clock, sleep=sleep)
        assert report["result"] == "inconclusive"
        assert report["duration_ms"] == 300000
        assert life.closed

    asyncio.run(scenario())


def test_second_read_failure_reports_only_fixed_diagnostics():
    """A successful first slot followed by a protocol error is not framed anew."""

    class SecondReadFails(Lifecycle):
        async def request_v4_data(self, *, timeout):
            self.budget.request()
            if self.budget.requests == 2:
                raise HobenProtocolError()
            self.budget.responses += 1
            return {"registers": "synthetic-private"}

    async def scenario():
        clock = Clock()
        budget = Session300(clock=clock)
        budget.receive(b"synthetic")
        life = SecondReadFails(budget)
        report = await observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        assert report["result"] == "inconclusive"
        assert report["terminal"] == report["failure_category"] == "protocol"
        assert report["failure_phase"] == "scheduled_read"
        assert report["message_category"] == "unclassified"
        assert report["read_slot"] == 2
        assert report["reads_ok"] == 1
        assert report["rx_bytes_total"] == 9
        assert report["rx_chunks_total"] == 1
        assert "synthetic" not in json.dumps(report)
        assert life.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key,value",
    [
        ("rx_bytes_total", 1048577),
        ("rx_chunks_total", -1),
        ("rx_chunks_total", True),
        ("read_slot", 7),
        ("failure_phase", "private/path"),
        ("failure_category", "raw-exception"),
        ("message_category", "0x0e"),
    ],
)
def test_diagnostic_schema_rejects_unbounded_or_sensitive_values(key, value):
    async def scenario():
        clock = Clock()
        budget = Session300(clock=clock)
        return await observe(Lifecycle(budget), budget, PROOF, clock=clock, sleep=clock.sleep)

    report = asyncio.run(scenario())
    report[key] = value
    with pytest.raises(ValueError, match="^invalid_session_300_report$"):
        validate_report(report, PROOF)
