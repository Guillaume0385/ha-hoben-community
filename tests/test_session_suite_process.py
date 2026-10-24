"""External process deadlines, isolated entry point and real group cleanup offline."""

import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import launch_session_suite as launcher
from scripts import run_session_suite as runner
from scripts.run_session_300 import context_proof
from scripts.session_suite import observe_suite
from tests.test_session_300_probe import PROOF
from tests.test_session_suite import Harness


def source(tmp_path):
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": (
            "Guillaume0385/ha-hoben-community/"
            ".github/workflows/hoben-session-300.yml@refs/heads/experimental"
        ),
        "GITHUB_WORKFLOW_SHA": PROOF["merge_sha"],
        "GITHUB_SHA": PROOF["merge_sha"],
        "GITHUB_RUN_ID": str(PROOF["run_id"]),
        "SESSION_SUITE_PHASE": "live",
        "SESSION_SUITE_APPROVED_SHA": PROOF["merge_sha"],
        "SESSION_SUITE_CANDIDATE_SHA": PROOF["candidate_sha"],
        "SESSION_SUITE_APPROVED_PR": str(PROOF["pr_number"]),
        "HOBEN_USER_GUID": "b" * 32,
        "HOBEN_DEVICE_GUID": "0" * 32,
        "RUNNER_TEMP": str(tmp_path),
    }


@pytest.mark.parametrize("attempt", [1, 2, 50])
def test_suite_preserves_native_attempt_through_isolated_environment(tmp_path, attempt):
    env = source(tmp_path) | {"GITHUB_RUN_ATTEMPT": str(attempt)}
    safe = launcher.collector_environment(env)
    assert safe["GITHUB_RUN_ATTEMPT"] == str(attempt)
    assert runner.suite_proof(safe) == PROOF | {"run_attempt": attempt}
    if attempt > 1:
        legacy = safe | {
            "SESSION300_PHASE": "live",
            "SESSION300_APPROVED_SHA": PROOF["merge_sha"],
            "SESSION300_CANDIDATE_SHA": PROOF["candidate_sha"],
            "SESSION300_APPROVED_PR": str(PROOF["pr_number"]),
        }
        with pytest.raises(ValueError):
            context_proof(legacy)  # Standalone session-300 does not opt into reruns.


@pytest.mark.parametrize("attempt", ["0", "51", "02", "2.0", "-1", "", "true"])
def test_suite_refuses_invalid_native_attempt_before_identity(tmp_path, attempt):
    env = source(tmp_path) | {"GITHUB_RUN_ATTEMPT": attempt}
    with pytest.raises(ValueError):
        runner.suite_proof(env)


def test_only_fixed_suite_context_and_no_runner_token_or_command_file(tmp_path):
    env = source(tmp_path)
    for k in [
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "GITHUB_PATH",
        "GITHUB_STEP_SUMMARY",
        "PYTHONPATH",
        "LD_PRELOAD",
        "SESSION300_APPROVED_SHA",
    ]:
        env[k] = "synthetic-private"
    safe = launcher.collector_environment(env)
    assert "synthetic-private" not in json.dumps(safe)
    assert set(safe) == set(launcher.ALLOWED) | {"PATH", "SESSION_SUITE_PHASE"}
    assert runner.suite_proof(safe) == PROOF
    for key in (
        "SESSION_SUITE_APPROVED_SHA",
        "SESSION_SUITE_CANDIDATE_SHA",
        "SESSION_SUITE_APPROVED_PR",
    ):
        bad = dict(safe)
        bad[key.replace("SESSION_SUITE_", "SESSION300_")] = bad.pop(key)
        with pytest.raises(ValueError):
            runner.suite_proof(bad)


@pytest.mark.parametrize("transition,end", [(None, 360), (100, 700), (100, 1020)])
def test_external_caps_remain_fixed_and_ack_precedes_second_start(
    monkeypatch, tmp_path, transition, end
):
    now = [0.0]
    events, child_environment = [], {}
    process = SimpleNamespace(pid=987654, poll=lambda: None)

    def wait(*, timeout):
        assert 0 < timeout <= 1
        events.append("reaped")

    process.wait = wait

    def popen(args, **kwargs):
        child_environment.update(kwargs["env"])
        assert args == [
            sys.executable,
            "-I",
            str(tmp_path / "scripts/run_session_suite.py"),
        ]
        assert kwargs["start_new_session"] is True
        assert (
            kwargs["stdin"]
            == kwargs["stdout"]
            == kwargs["stderr"]
            == subprocess.DEVNULL
        )
        assert set(kwargs["pass_fds"]) == {
            int(child_environment["SESSION_SUITE_CONTROL_FD"]),
            int(child_environment["SESSION_SUITE_ACK_FD"]),
        }
        return process

    class Selector:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def unregister(self, *args):
            pass

        def select(self, timeout):
            self.calls += 1
            assert self.calls <= 2
            assert 0 < timeout <= 0.2
            if transition is not None and not events:
                now[0] = transition
                events.append("phase_requested")
                return [object()]
            now[0] = end - 1
            return []

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(launcher.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(launcher.os, "read", lambda fd, size: b"2")

    def ack(fd, value):
        assert value == b"2" and now[0] == transition
        events.append("ack")
        return 1

    monkeypatch.setattr(launcher.os, "write", ack)
    monkeypatch.setattr(
        launcher.os, "killpg", lambda pid, sig: events.append((pid, sig))
    )
    assert launcher.supervise(tmp_path, source(tmp_path), clock=lambda: now[0]) == 1
    assert events[-2:] == [(987654, signal.SIGKILL), "reaped"]
    assert ("ack" in events) == (transition is not None)


@pytest.mark.parametrize("token", [b"1", b"22", b"private"])
def test_malformed_phase_protocol_kills_group_without_an_ack(
    monkeypatch, tmp_path, token
):
    process = SimpleNamespace(pid=987654, poll=lambda: None, wait=lambda **kw: 0)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **kw: process)

    class Selector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def select(self, **kw):
            return [object()]

    monkeypatch.setattr(launcher.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(launcher.os, "read", lambda *a: token)

    def forbidden(*a):
        raise AssertionError("unexpected acknowledgement")

    monkeypatch.setattr(launcher.os, "write", forbidden)
    killed = []
    monkeypatch.setattr(launcher.os, "killpg", lambda *a: killed.append(a))
    assert launcher.supervise(tmp_path, source(tmp_path)) == 1
    assert killed == [(987654, signal.SIGKILL)]


@pytest.mark.parametrize("mode", ["recovered", "first_invalid"])
def test_real_entry_point_shared_engine_reports_and_private_export(
    monkeypatch, tmp_path, mode
):
    h = Harness(mode)
    env = source(tmp_path)
    control_r, control_w = os.pipe()
    ack_r, ack_w = os.pipe()
    os.write(ack_w, b"2")
    env.update(SESSION_SUITE_CONTROL_FD=str(control_w), SESSION_SUITE_ACK_FD=str(ack_r))
    monkeypatch.setattr(runner.os, "environ", env)
    monkeypatch.setattr(runner.sys, "argv", ["run_session_suite.py"])
    monkeypatch.setattr(
        runner.subprocess,
        "check_output",
        lambda *a, **kw: (PROOF["merge_sha"] + "\n").encode(),
    )

    def life(**kwargs):
        assert kwargs["retry_delays"] == (1.0, 2.0)
        options = kwargs["session_factory"].keywords
        return h.make(options["session_300"], options["no_pong_after_120"])

    async def observe(factory, proof):
        result = await observe_suite(factory, proof, clock=h.clock, sleep=h.sleep)
        h.assert_closed()
        return result

    monkeypatch.setattr(runner, "V4Lifecycle", life)
    monkeypatch.setattr(runner, "observe_suite", observe)
    try:
        assert runner.main() == 0
        assert os.read(control_r, 2) == (b"2" if mode == "recovered" else b"")
        file = tmp_path / "hoben-session-suite-exports/report.json"
        r = json.loads(file.read_text())
        assert r["result"] == ("success" if mode == "recovered" else "not_successful")
        assert r["session_reconnect_no_pong"]["result"] == (
            "recovered_120s" if mode == "recovered" else "not_run"
        )
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        assert stat.S_IMODE(file.parent.stat().st_mode) == 0o700
        assert file.stat().st_size <= runner.MAX_REPORT_BYTES
        assert "HOBEN_USER_GUID" not in env and "HOBEN_DEVICE_GUID" not in env
    finally:
        for fd in (control_r, control_w, ack_r, ack_w):
            try:
                os.close(fd)
            except OSError:
                pass


BLOCKED_WORKER = """import asyncio,json,os,pathlib,signal,subprocess,sys
child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(1000)"])
pathlib.Path(os.environ["RUNNER_TEMP"],"ready.json").write_text(json.dumps([os.getpid(),child.pid]))
signal.signal(signal.SIGTERM,signal.SIG_IGN)
async def blocked():
    while True:
        try:await asyncio.Future()
        except asyncio.CancelledError:pass
asyncio.run(blocked())
"""


def assert_not_running(pid):
    file = Path(f"/proc/{pid}/stat")
    end = time.monotonic() + 1
    while file.exists():
        try:
            if file.read_text().split()[2] == "Z":
                return
        except FileNotFoundError:
            return
        assert time.monotonic() < end
        time.sleep(0.005)


@pytest.mark.parametrize("second", [False, True])
def test_real_asyncio_resistant_worker_and_descendant_are_killed(tmp_path, second):
    (tmp_path / "scripts").mkdir()
    handshake = (
        (
            "import os\n"
            "os.write(int(os.environ['SESSION_SUITE_CONTROL_FD']),b'2')\n"
            "os.read(int(os.environ['SESSION_SUITE_ACK_FD']),1)\n"
        )
        if second
        else ""
    )
    (tmp_path / "scripts/run_session_suite.py").write_text(handshake + BLOCKED_WORKER)
    ready = tmp_path / "ready.json"
    real_start = time.monotonic()

    def clock():
        if ready.exists():
            try:
                json.loads(ready.read_text())
            except json.JSONDecodeError:
                return 0
            return 599.0 if second else 359.0
        assert time.monotonic() - real_start < 5
        return 0.0

    assert launcher.supervise(tmp_path, source(tmp_path), clock=clock) == 1
    for pid in json.loads(ready.read_text()):
        assert_not_running(pid)


def test_normal_worker_exit_also_kills_remaining_descendants(tmp_path):
    (tmp_path / "scripts").mkdir()
    worker = "\n".join(BLOCKED_WORKER.splitlines()[:3]) + "\n"
    (tmp_path / "scripts/run_session_suite.py").write_text(worker)
    assert launcher.supervise(tmp_path, source(tmp_path), clock=lambda: 0.0) == 0
    for pid in json.loads((tmp_path / "ready.json").read_text()):
        assert_not_running(pid)


def test_parent_sigterm_cleans_the_candidate_group(tmp_path):
    script = tmp_path / "trusted/scripts/launch_session_suite.py"
    script.parent.mkdir(parents=True)
    script.write_text(Path(launcher.__file__).read_text())
    candidate = tmp_path / "candidate/scripts"
    candidate.mkdir(parents=True)
    (candidate / "run_session_suite.py").write_text(BLOCKED_WORKER)
    p = subprocess.Popen(
        [sys.executable, str(script)],
        env=source(tmp_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready = tmp_path / "ready.json"
        end = time.monotonic() + 5
        while True:
            assert p.poll() is None and time.monotonic() < end
            try:
                pids = json.loads(ready.read_text())
                break
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            time.sleep(0.01)
        p.terminate()
        assert p.wait(timeout=3) == 1
        for pid in pids:
            assert_not_running(pid)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=3)
