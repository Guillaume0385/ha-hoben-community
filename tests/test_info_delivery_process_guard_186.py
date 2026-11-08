"""D5: benign local processes; no network worker, identity or raw output."""

import copy
import json

import pytest

from scripts.info_delivery_process_guard import (
    InvalidProcessGuard,
    ProcessBudget,
    run_dummy,
    validate_process_report,
)


def test_fixed_deadlines_and_repeated_cancel_never_rearm():
    now = [0]
    budget = ProcessBudget(clock_ms=lambda: now[0])
    budget.start()
    now[0] = 3_540_000
    budget.tick()
    assert budget.cleanup_started_ms == 3_540_000
    assert budget.cleanup_deadline_ms == 3_600_000
    now[0] += 1000
    budget.cancel()
    budget.cancel()
    assert budget.cleanup_started_ms == 3_540_000
    assert budget.cleanup_deadline_ms == 3_600_000
    now[0] = 3_600_000
    budget.tick()
    assert budget.expired
    assert budget.first_error == "observation_timeout"


@pytest.mark.parametrize("fixture", ["cooperative", "ignore-term", "tree", "orphan"])
def test_real_fixed_process_group_signals_and_wait(fixture):
    report = run_dummy(fixture=fixture)
    assert report["result"] == "SUCCESS"
    assert report["proof_scope"] == "benign_local_process"
    assert report["info_observation"] == "NOT RUN"
    assert report["live_provenance"] == report["tls_cleanup"] == "not_proven"
    assert report["cleanup_attested"] and report["guard_waited"]
    assert report["group_empty"] and report["control_closed"]
    assert report["reaped_children"] == (2 if fixture in {"tree", "orphan"} else 1)
    assert report["term_confirmed"]
    assert report["kill_confirmed"] == (fixture != "cooperative")
    assert validate_process_report(report) == report
    assert len(json.dumps(report).encode()) <= 8192
    for key in report:
        forged = copy.deepcopy(report)
        del forged[key]
        with pytest.raises(InvalidProcessGuard):
            validate_process_report(forged)


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class FakePort:
    """No OS, never entitled to benign_local_process/os_cleanup_attested."""

    def __init__(self, clock, *, ignore=False, fault=None):
        self.clock, self.ignore, self.fault = clock, ignore, fault
        self.ready = self.termed = self.killed = self.closed = False
        self.ack_term = self.ack_kill = False
        self.waits = 0

    def poll(self):
        self.clock.now += 5
        if self.fault == "control":
            raise OSError("PRIVATE_D5_CONTROL")
        if not self.ready:
            self.ready = True
            return ["isolated", "ready"]
        result = []
        if self.termed and not self.ack_term:
            self.ack_term = True
            result.append("term_confirmed")
        if self.killed and not self.ack_kill:
            self.ack_kill = True
            result.append("kill_confirmed")
        if (self.termed and not self.ignore) or self.killed:
            result += ["reaped_one", "group_empty"]
        return result

    def signal(self, kind):
        if self.fault == "signal":
            raise OSError("PRIVATE_D5_SIGNAL")
        if kind == "term":
            self.termed = True
        else:
            self.killed = True

    def wait(self, seconds):
        self.waits += 1
        if self.fault == "wait":
            raise TimeoutError("PRIVATE_D5_WAIT")
        return 0

    def close(self):
        self.closed = True
        if self.fault == "close":
            raise OSError("PRIVATE_D5_CLOSE")


def simulated(*, fault=None, ignore=False, cancel_at=None):
    from scripts.info_delivery_process_guard import _drive

    clock = Clock()
    budget = ProcessBudget(clock_ms=clock)
    budget.start()
    port = FakePort(clock, fault=fault, ignore=ignore)
    _drive(
        port, budget, cancelled=lambda: cancel_at is not None and clock.now >= cancel_at
    )
    report = budget.finish()
    assert validate_process_report(report) == report
    assert port.closed
    assert not report["os_cleanup_attested"]
    assert report["proof_scope"] == "synthetic_process_events"
    return report


@pytest.mark.parametrize("fault", ["control", "signal", "wait", "close"])
def test_control_failure_does_not_credit_reap_or_cleanup(fault):
    report = simulated(fault=fault)
    assert report["result"] == "FAILURE"
    assert not report["cleanup_attested"]
    assert "PRIVATE_D5" not in json.dumps(report)


def test_repeated_cancellation_does_not_restart_TERM_or_deadlines():
    report = simulated(ignore=True, cancel_at=10)
    assert report["result"] == "FAILURE" and report["first_error"] == "cancelled"
    assert report["cleanup_started_ms"] == 5
    assert report["cleanup_deadline_ms"] == 60005
    assert sum(e["event"] == "cancelled" for e in report["events"]) == 1
    assert sum(e["event"] == "term_requested" for e in report["events"]) == 1
    assert sum(e["event"] == "kill_requested" for e in report["events"]) == 1
    assert report["cleanup_attested"]  # Actual model witnesses, result still FAILURE.


@pytest.mark.parametrize("at", [3_539_999, 3_540_000, 3_540_001, 3_600_000, 3_600_001])
def test_exact_deadlines_and_late_poll(at):
    clock = Clock()
    b = ProcessBudget(clock_ms=clock)
    b.start()
    b.note("spawned")
    b.note("isolated")
    clock.now = at
    b.tick()
    report = b.finish()
    assert report["result"] == "FAILURE"
    assert report["elapsed_ms"] == at
    if at >= 3540000:
        assert report["cleanup_started_ms"] == 3540000
        assert report["cleanup_deadline_ms"] == 3600000
    if at >= 3600000:
        assert report["expired"]
    assert validate_process_report(report) == report


@pytest.mark.parametrize("value", [-1, None, True, float("nan"), 1.5, 2**53])
def test_invalid_clock_before_spawn_is_not_run(value):
    budget = ProcessBudget(clock_ms=lambda: value)
    budget.start()
    report = budget.finish()
    assert report["result"] == "NOT RUN"
    assert report["first_error"] == "clock"
    assert not report["cleanup_attested"]
    assert validate_process_report(report) == report


def test_clock_rollback_cannot_be_repaired():
    c = Clock()
    b = ProcessBudget(clock_ms=c)
    b.start()
    b.note("spawned")
    b.note("isolated")
    c.now = 10
    b.note("ready")
    c.now = 9
    b.tick()
    c.now = 11
    b.note("control_closed")
    report = b.finish()
    assert report["first_error"] == "clock" and not report["clock_valid"]
    assert validate_process_report(report) == report


def test_no_command_path_environment_or_report_can_launch_network(monkeypatch):
    import subprocess

    from scripts.info_delivery_supervisor import InvalidSupervision

    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("unexpected_spawn")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for text in (
        "/bin/sh",
        "curl myhoben.fr",
        "../../worker.py",
        "https://example.org",
        "",
    ):
        with pytest.raises(
            InvalidProcessGuard, match="^invalid_offline_info_process_guard$"
        ):
            run_dummy(fixture=text)
    with pytest.raises(TypeError):
        run_dummy(command="/bin/sh")
    with pytest.raises(InvalidSupervision):
        run_dummy(evidence={"command": "/bin/sh", "mode": "live"})
    assert calls == []


def test_cancel_before_spawn_and_public_typed_cancel(monkeypatch):
    import subprocess
    import threading

    event = threading.Event()
    event.set()

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected_spawn")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    report = run_dummy(cancel=event)
    assert report["result"] == "NOT RUN" and report["reason"] == "cancelled"
    assert not report["spawned"] and not report["cleanup_attested"]
    assert validate_process_report(report) == report
    with pytest.raises(InvalidProcessGuard):
        run_dummy(cancel=lambda: False)


@pytest.mark.parametrize(
    "missing",
    [
        "term_confirmed",
        "group_empty",
        "guard_waited",
        "exit_ok",
        "control_closed",
        "reaped_one",
    ],
)
def test_no_success_without_every_independent_witness(missing):
    c = Clock()
    b = ProcessBudget(clock_ms=c)
    b.start()
    events = [
        "spawned",
        "isolated",
        "ready",
        "term_requested",
        "term_confirmed",
        "reaped_one",
        "group_empty",
        "guard_waited",
        "exit_ok",
        "control_closed",
    ]
    for event in events:
        if event != missing:
            b.note(event)
    report = b.finish()
    assert report["result"] == "FAILURE"
    assert validate_process_report(report) == report


@pytest.mark.parametrize(
    "key,value",
    [
        ("os_cleanup_attested", True),
        ("cleanup_attested", False),
        ("mode", "live"),
        ("info_observation", "SUCCESS"),
        ("tls_cleanup", "proven"),
        ("live_provenance", "authenticated"),
        ("boundary_proven", True),
        ("spawned", 1),
        ("elapsed_ms", True),
        ("reaped_children", 2),
        ("payload", "PRIVATE_D5"),
        ("first_error", "PRIVATE_D5"),
    ],
)
def test_report_tampering_never_upgrades_proof(key, value):
    report = simulated()
    forged = copy.deepcopy(report)
    forged[key] = value
    with pytest.raises(
        InvalidProcessGuard, match="^invalid_offline_info_process_guard$"
    ):
        validate_process_report(forged)


def test_fake_cleanup_and_OS_scope_are_never_confused():
    r = simulated(ignore=True)
    assert r["result"] == "SUCCESS" and r["cleanup_attested"]
    assert not r["os_cleanup_attested"]
    r["os_cleanup_attested"] = True
    with pytest.raises(InvalidProcessGuard):
        validate_process_report(r)


def capture_ports(monkeypatch):
    from scripts.info_delivery_process_guard import _LocalDummy

    ports = []
    init = _LocalDummy.__init__

    def capture(self, fixture):
        init(self, fixture)
        ports.append(self)

    monkeypatch.setattr(_LocalDummy, "__init__", capture)
    return ports


def assert_physically_gone(port):
    import os

    assert port.closed and port.process.returncode is not None
    assert not port._descriptors
    if hasattr(port, "worker_group"):
        with pytest.raises(ProcessLookupError):
            os.killpg(port.worker_group, 0)
    with pytest.raises(ChildProcessError):
        os.waitpid(port.process.pid, os.WNOHANG)  # Already really reaped by wait().


@pytest.mark.parametrize("fixture", ["cooperative", "ignore-term", "tree", "orphan"])
def test_OS_subreaper_has_no_surviving_group_or_zombie(monkeypatch, fixture):
    ports = capture_ports(monkeypatch)
    report = run_dummy(fixture=fixture)
    assert report["result"] == "SUCCESS" and report["os_cleanup_attested"]
    assert len(ports) == 1
    assert_physically_gone(ports[0])


def test_real_repeated_cancel_still_reaps_without_success(monkeypatch):
    import threading

    from scripts.info_delivery_process_guard import _LocalDummy

    event = threading.Event()
    ports = capture_ports(monkeypatch)
    poll = _LocalDummy.poll

    def cancel_after_ready(self):
        events = poll(self)
        if "ready" in events or "term_confirmed" in events:
            event.set()
        return events

    monkeypatch.setattr(_LocalDummy, "poll", cancel_after_ready)
    report = run_dummy(fixture="tree", cancel=event)
    assert report["result"] == "FAILURE" and report["first_error"] == "cancelled"
    assert report["cleanup_attested"] and report["guard_waited"]
    assert sum(e["event"] == "cancelled" for e in report["events"]) == 1
    assert_physically_gone(ports[0])


def test_real_control_EOF_uses_emergency_reap_but_no_attestation(monkeypatch):
    import os

    from scripts.info_delivery_process_guard import _LocalDummy

    ports = capture_ports(monkeypatch)
    poll = _LocalDummy.poll

    def break_control(self):
        events = poll(self)
        if "ready" in events:
            os.close(self.command)
            self._descriptors.remove(self.command)
        return events

    monkeypatch.setattr(_LocalDummy, "poll", break_control)
    report = run_dummy(fixture="orphan")
    assert report["result"] == "FAILURE" and report["first_error"] == "control_error"
    assert not report["cleanup_attested"] and not report["guard_waited"]
    assert_physically_gone(ports[0])


def test_real_wait_failure_is_not_repaired_by_later_emergency_reap(monkeypatch):
    from scripts.info_delivery_process_guard import _LocalDummy

    ports = capture_ports(monkeypatch)

    def no_receipt(self, seconds):
        raise TimeoutError("PRIVATE_D5_WAIT")

    monkeypatch.setattr(_LocalDummy, "wait", no_receipt)
    report = run_dummy(fixture="ignore-term")
    assert report["result"] == "FAILURE" and report["first_error"] == "wait_failed"
    assert not report["guard_waited"] and not report["os_cleanup_attested"]
    assert "PRIVATE_D5_WAIT" not in json.dumps(report)
    assert_physically_gone(ports[0])


def test_real_probe_inherits_no_secret_output_or_command(monkeypatch, capfd):
    import os
    import subprocess

    from scripts.info_delivery_process_guard import _DUMMY_SOURCE

    popen = subprocess.Popen
    observed = []

    def check(args, **kwargs):
        assert args[:4] == [__import__("sys").executable, "-I", "-S", "-c"]
        assert args[4] == _DUMMY_SOURCE and args[5] == "cooperative"
        assert kwargs["env"] == {}
        assert (
            kwargs["stdout"]
            is kwargs["stderr"]
            is kwargs["stdin"]
            is subprocess.DEVNULL
        )
        assert kwargs["start_new_session"] and kwargs["close_fds"]
        assert os.stat(kwargs["cwd"]).st_mode & 0o077 == 0
        observed.append(True)
        return popen(args, **kwargs)

    monkeypatch.setenv("HOBEN_USER_GUID", "PRIVATE_D5_ENV")
    monkeypatch.setenv("SECRET_D5", "PRIVATE_D5_SECRET")
    monkeypatch.setattr(subprocess, "Popen", check)
    report = run_dummy()
    assert report["result"] == "SUCCESS" and observed == [True]
    output = capfd.readouterr()
    assert output.out == output.err == ""
    assert "PRIVATE_D5" not in json.dumps(report)


@pytest.mark.parametrize(
    "delta,success", [(59999, True), (60000, False), (60001, False)]
)
def test_cleanup_deadline_equality_refuses_all_positive_facts(delta, success):
    c = Clock()
    b = ProcessBudget(clock_ms=c)
    b.start()
    for e in ("spawned", "isolated", "ready", "term_requested", "term_confirmed"):
        b.note(e)
    c.now = delta
    for e in ("reaped_one", "group_empty", "guard_waited", "exit_ok", "control_closed"):
        b.note(e)
    report = b.finish()
    assert (report["result"] == "SUCCESS") is success
    assert report["cleanup_deadline_ms"] == 60000
    assert validate_process_report(report) == report


def test_protocol_witnesses_cannot_be_reordered_or_late():
    c = Clock()
    b = ProcessBudget(clock_ms=c)
    b.start()
    b.note("spawned")
    b.note("isolated")
    b.note("ready")
    b.note("kill_requested")  # No TERM and no grace.
    b.note("kill_confirmed")
    for e in ("reaped_one", "group_empty", "guard_waited", "exit_ok", "control_closed"):
        b.note(e)
    report = b.finish()
    assert report["result"] == "FAILURE" and report["first_error"] == "invalid_proof"
    assert validate_process_report(report) == report
    with pytest.raises(InvalidProcessGuard):
        b.start()


def test_trace_budget_and_oversize_are_fail_closed():
    c = Clock()
    b = ProcessBudget(clock_ms=c)
    b.start()
    b.note("spawned")
    for _ in range(100):
        b.note("control_error")
    report = b.finish()
    assert report["result"] == "FAILURE"
    assert len(report["events"]) == 64
    assert validate_process_report(report) == report
    forged = copy.deepcopy(report)
    forged["events"] *= 100
    with pytest.raises(InvalidProcessGuard):
        validate_process_report(forged)
    forged = {**report, "stdout": "PRIVATE_D5" * 10000}
    with pytest.raises(InvalidProcessGuard):
        validate_process_report(forged)


def test_D4_fixture_evidence_remains_unbound_and_live_refused(monkeypatch):
    import asyncio
    import subprocess

    from tests.info_delivery_worker_fixture_186 import run_worker_case

    evidence = asyncio.run(run_worker_case(monkeypatch)).report
    report = run_dummy(evidence=evidence)
    assert report["result"] == "SUCCESS" and report["fixture_evidence"] == evidence
    assert report["info_observation"] == "NOT RUN"  # No V4 ever ran in this process.
    assert len(json.dumps(report).encode()) <= 8192
    driver = """
const api=require('./.github/scripts/info-delivery-manual-report.cjs');
const r=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
try {api.validateForLivePublication(r);process.exit(2);}
catch(e){if(e.message!=='info_live_provenance_not_proven')process.exit(3);}
"""
    proc = subprocess.run(
        ["node", "-e", driver],
        input=json.dumps(report),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert proc.returncode == 0
    forged = copy.deepcopy(report)
    forged["fixture_evidence"]["live_provenance"] = "authenticated"
    with pytest.raises(InvalidProcessGuard):
        validate_process_report(forged)


def test_missing_KILL_confirmation_prevents_success():
    c = Clock()
    b = ProcessBudget(clock_ms=c)
    b.start()
    for e in ("spawned", "isolated", "ready", "term_requested", "term_confirmed"):
        b.note(e)
    c.now = 100
    b.note("kill_requested")
    for e in ("reaped_one", "group_empty", "guard_waited", "exit_ok", "control_closed"):
        b.note(e)
    r = b.finish()
    assert r["result"] == "FAILURE" and not r["cleanup_attested"]
    assert validate_process_report(r) == r


def test_cancel_after_another_error_is_deduplicated_without_reset():
    c = Clock()
    b = ProcessBudget(clock_ms=c)
    b.start()
    b.note("spawned")
    c.now = 3540000
    b.tick()
    for _ in range(100):
        b.cancel()
    r = b.finish()
    assert r["first_error"] == "observation_timeout"
    assert r["cleanup_deadline_ms"] == 3600000
    assert sum(e["event"] == "cancelled" for e in r["events"]) == 1
    assert validate_process_report(r) == r


def test_fixed_sources_have_no_network_import_or_entrypoint():
    import ast
    from pathlib import Path

    from scripts.info_delivery_process_guard import _DUMMY_SOURCE

    source = Path("scripts/info_delivery_process_guard.py").read_text()
    forbidden = {"socket", "ssl", "urllib", "http", "requests", "custom_components"}
    for text in (source, _DUMMY_SOURCE):
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                assert not any(x.name.split(".")[0] in forbidden for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module.split(".")[0] not in forbidden
    assert "__main__" not in source
    assert "_InfoDeliveryDropExperiment" not in source


def test_ignored_SIGCHLD_cannot_fabricate_a_successful_wait(monkeypatch):
    import signal
    import subprocess

    original = signal.getsignal
    monkeypatch.setattr(
        signal,
        "getsignal",
        lambda sig: signal.SIG_IGN if sig == signal.SIGCHLD else original(sig),
    )
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("unexpected_spawn")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    report = run_dummy()
    assert report["result"] == "NOT RUN"
    assert not report["guard_waited"] and not report["cleanup_attested"]
    assert calls == []


def test_concurrent_guards_cannot_signal_or_reap_each_others_groups(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    ports = capture_ports(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_dummy, fixture=kind)
            for kind in ("ignore-term", "orphan")
        ]
        reports = [future.result(timeout=8) for future in futures]
    assert all(r["result"] == "SUCCESS" and r["os_cleanup_attested"] for r in reports)
    assert len(ports) == 2
    assert ports[0].process.pid != ports[1].process.pid
    assert ports[0].worker_group != ports[1].worker_group
    for port in ports:
        assert_physically_gone(port)
