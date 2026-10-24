"""Scheduler, isolation and report tests; no network, secret or wall-clock wait."""

import asyncio
import json
import subprocess
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
        return await observe(
            Lifecycle(budget), budget, PROOF, clock=clock, sleep=clock.sleep
        )

    report = asyncio.run(scenario())
    report[key] = value
    with pytest.raises(ValueError, match="^invalid_session_300_report$"):
        validate_report(report, PROOF)


@pytest.mark.parametrize(
    "bad,phase,message",
    [
        (b"\xff", "message_classification", "unknown"),
        (b"\x00", "message_classification", "unknown"),
        (bytes.fromhex("0e00010000ffff"), "frame_boundary", "ambiguous"),
        ("truncated", "frame_boundary", "ambiguous"),
        ("duplicate", "request_correlation", "data_response"),
        ("mismatched", "response_validation", "data_response"),
    ],
)
def test_real_second_slot_failure_is_discriminated_without_changing_rx_rules(
    bad, phase, message
):
    from custom_components.hoben.v4_lifecycle import V4Lifecycle
    from custom_components.hoben.v4_session import V4Session
    from tests.test_session_300_runtime import Stream, response

    class TwoSlots(Stream):
        async def write(self, payload):
            if payload[0] == 13:
                if budget.requests == 1:
                    self.chunks = [response()]
                elif isinstance(bad, bytes):
                    self.chunks = [bad]
                elif bad == "truncated":
                    self.chunks = [response()[:-1], b""]
                elif bad == "duplicate":
                    self.chunks = [response() * 2]
                else:
                    self.chunks = [b"\x0e\x00\x01" + response()[3:]]
            await super().write(payload)

    async def scenario():
        nonlocal budget
        clock = Clock()
        budget = Session300(clock=clock)
        stream, sessions = TwoSlots(), []

        def factory(**kwargs):
            session = V4Session(
                **kwargs, transport_factory=lambda: stream, session_300=budget
            )
            sessions.append(session)
            return session

        life = V4Lifecycle(user_guid="b" * 32, session_factory=factory)
        report = await observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        assert report["duration_ms"] == 60000
        assert report["result"] == "inconclusive"
        assert report["failure_category"] == report["terminal"] == "protocol"
        assert report["failure_phase"] == phase
        assert report["message_category"] == message
        assert report["read_slot"] == report["reads"] == 2
        assert report["reads_ok"] == report["reads_failed"] == 1
        assert report["opens"] == 1 and report["reconnections"] == 0
        assert report["rx_bytes_total"] >= 98 and report["rx_chunks_total"] >= 3
        assert report["boundary_proven"] is False
        assert stream.close_count == 1 and stream.active_reads == 0
        assert all(s._rx_task.done() and not s._operations for s in sessions)

    budget = None
    asyncio.run(scenario())


def test_real_shared_session_accepts_all_five_scheduled_reads_offline():
    from custom_components.hoben.v4_lifecycle import V4Lifecycle
    from custom_components.hoben.v4_session import V4Session
    from tests.test_session_300_runtime import Stream, response

    async def scenario():
        clock = Clock()
        budget, stream = Session300(clock=clock), Stream([response()])
        life = V4Lifecycle(
            user_guid="b" * 32,
            session_factory=lambda **kw: V4Session(
                **kw, transport_factory=lambda: stream, session_300=budget
            ),
        )
        report = await observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        assert report["result"] == "continuous_300s"
        assert report["reads_ok"] == report["read_slot"] == 5
        assert report["failure_phase"] == "none"
        assert report["message_category"] == "unclassified"
        assert report["rx_bytes_total"] == 48 + 5 * len(response())
        assert report["rx_chunks_total"] == 6
        assert stream.close_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("chunk_size", [4096, 4097])
def test_rx_overrun_still_exports_a_bounded_budget_failure(chunk_size):
    from custom_components.hoben.v4_experiment import BudgetTransport
    from scripts.run_session_300 import ROOT

    class Source:
        async def read(self, max_bytes, *, bounded):
            assert max_bytes == 4096
            # The second case deliberately violates the transport contract.
            return b"x" * chunk_size

    class Overrun(Lifecycle):
        async def request_v4_data(self, *, timeout):
            if self.budget.requests == 1:
                self.budget.request()
                transport = BudgetTransport(Source(), self.budget)
                for _ in range(257):
                    await transport.read()
            return await super().request_v4_data(timeout=timeout)

    async def scenario():
        clock = Clock()
        budget = Session300(clock=clock)
        life = Overrun(budget)
        report = await observe(life, budget, PROOF, clock=clock, sleep=clock.sleep)
        assert report["result"] == "inconclusive"
        assert report["terminal"] == report["failure_category"] == "budget"
        assert report["failure_phase"] == "tls_read"
        assert report["message_category"] == "unclassified"
        if chunk_size == 4096:
            assert budget.rx_bytes == 257 * 4096
            assert report["rx_bytes_total"] == 1048576
            assert report["rx_chunks_total"] == 257
        else:
            # Oversized chunks are refused before accounting or routing.
            assert budget.rx_bytes == budget.rx_chunks == 0
            assert report["rx_bytes_total"] == report["rx_chunks_total"] == 0
        assert report["read_slot"] == 2 and report["reads_ok"] == 1
        assert report["reads_failed"] == 1 and report["responses"] == 1
        assert life.closed
        assert report["boundary_proven"] is False
        return report

    # Observe returns the real Python projection; feed that exact JSON to the
    # independent validator used by export and isolated publication.
    report = asyncio.run(scenario())
    assert validate_report(report, PROOF) == report
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const api=require('./.github/scripts/session-300-report.cjs');
const [report,proof]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(api.validate(report,proof)));
""",
        ],
        cwd=ROOT,
        input=json.dumps([report, PROOF]),
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    assert json.loads(result.stdout) == report
    assert result.stderr == ""


def test_python_and_publication_validate_the_same_closed_diagnostic_schema():
    from scripts.run_session_300 import ROOT

    async def healthy():
        clock = Clock()
        budget = Session300(clock=clock)
        return await observe(
            Lifecycle(budget), budget, PROOF, clock=clock, sleep=clock.sleep
        )

    good = asyncio.run(healthy())
    failed = good | {
        "result": "inconclusive",
        "terminal": "protocol",
        "failure_category": "protocol",
        "failure_phase": "scheduled_read",
    }
    cases = [good, failed]
    for phase, message in [
        ("tls_read", "unclassified"),
        ("frame_boundary", "ambiguous"),
        ("message_classification", "unknown"),
        ("request_correlation", "data_response"),
        ("response_validation", "data_response"),
        ("pong_tx", "ping"),
    ]:
        cases.append(failed | {"failure_phase": phase, "message_category": message})
    for field in ["rx_bytes_total", "rx_chunks_total", "read_slot"]:
        for value in [-1, True, None, "private", 1048577]:
            cases.append(failed | {field: value})
    cases += [
        failed | change
        for change in [
            {"read_slot": 0},
            {"failure_phase": "none"},
            {"failure_phase": "private/path"},
            {"failure_category": "raw-exception"},
            {"message_category": "unknown"},
            {"rx_raw": "synthetic-private"},
            {"transaction_id": 1},
            {"traceback": "private"},
            {"rx_bytes_total": 0, "rx_chunks_total": 1},
            {"rx_bytes_total": 1048576, "rx_chunks_total": 1048576},
        ]
    ]
    for key in [
        "failure_phase",
        "failure_category",
        "message_category",
        "rx_bytes_total",
        "rx_chunks_total",
        "read_slot",
    ]:
        cases.append({k: v for k, v in failed.items() if k != key})
    expected = []
    for report in cases:
        try:
            validate_report(report, PROOF)
            expected.append(True)
        except (ValueError, TypeError):
            expected.append(False)
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const api=require('./.github/scripts/session-300-report.cjs');
const [reports,proof]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(reports.map(r=>{
  try {api.validate(r,proof);return true;}catch(_){return false;}
})));
""",
        ],
        cwd=ROOT,
        input=json.dumps([cases, PROOF]),
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    assert json.loads(result.stdout) == expected
    assert expected.count(True) == 9
