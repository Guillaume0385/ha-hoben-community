"""#186-D5: fixed benign Linux process probe, never a network worker launcher.

The local auxiliary adopts/reaps its fixed descendants. Public JSON establishes
consistency, not authenticated provenance; D1 still refuses live publication.
"""

import copy
import json
import os
import selectors
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time

from scripts.info_delivery_supervisor import (
    LIMITS,
    MAX_TIME,
    validate_supervision_report,
)

FIXTURES = {"cooperative", "ignore-term", "tree", "orphan"}
TERM_GRACE_MS = 100
POLL_MS = 5
FLAGS = {
    "spawned",
    "isolated",
    "ready",
    "term_requested",
    "term_confirmed",
    "kill_requested",
    "kill_confirmed",
    "group_empty",
    "guard_waited",
    "exit_ok",
    "control_closed",
}
ERRORS = {
    "none",
    "clock",
    "cancelled",
    "observation_timeout",
    "cleanup_timeout",
    "global_timeout",
    "control_error",
    "isolation_failed",
    "wait_failed",
    "missing_proof",
    "invalid_proof",
    "event_budget",
}
EVENTS = (
    FLAGS
    | ERRORS - {"none"}
    | {
        "start",
        "tick",
        "finish",
        "reaped_one",
        "reaped_two",
    }
)
CONSTANTS = {
    "schema": 1,
    "scenario": "info-dummy-process-guard",
    "mode": "offline",
    "info_observation": "NOT RUN",
    "live_provenance": "not_proven",
    "tls_cleanup": "not_proven",
    "boundary_proven": False,
    "info_framing": "INCONCLUSIVE",
}


class InvalidProcessGuard(ValueError):
    def __init__(self):
        super().__init__("invalid_offline_info_process_guard")


def need(condition):
    if not condition:
        raise InvalidProcessGuard()


def owns_process_group(guardian, worker):
    """Kernel ownership witness shared by the dummy probe and D7 controller.

    Scalars stay private. No signal is sent and no exception text is exported.
    """
    if not all(type(p) is int and p > 1 for p in (guardian, worker)):
        return False
    try:
        return (
            worker != guardian
            and os.getsid(guardian) == os.getpgid(guardian) == guardian
            and os.getsid(worker) == guardian
            and os.getpgid(worker) == worker
            and guardian != os.getsid(0)
            and worker != os.getpgrp()
        )
    except OSError:
        return False


class ProcessBudget:
    """Pure deadline/witness reducer. Synthetic unless driven by our exact port."""

    def __init__(self, *, clock_ms, fixture="cooperative"):
        need(callable(clock_ms) and type(fixture) is str and fixture in FIXTURES)
        self.clock, self.fixture = clock_ms, fixture
        self.origin = self.elapsed = None
        self.cleanup_started_ms = self.cleanup_deadline_ms = None
        self.expired = False
        self.first_error = "none"
        self.clock_valid = True
        self.facts = dict.fromkeys(FLAGS, False)
        self.reaped_children = 0
        self.events = []
        self.scope = "synthetic_process_events"
        self._overflow = False
        self._cancel_seen = False
        self._term_confirmed_ms = None
        self._finished = None

    def _fail(self, reason):
        if self.first_error == "none":
            self.first_error = reason

    def _cleanup(self, at=None):
        if self.cleanup_started_ms is None:
            self.cleanup_started_ms = self.elapsed if at is None else at
            if self.cleanup_started_ms is not None:
                self.cleanup_deadline_ms = min(
                    self.cleanup_started_ms + LIMITS["cleanup_reserve_ms"],
                    LIMITS["total_ms"],
                )

    def _stamp(self, kind):
        need(self._finished is None)
        try:
            value = self.clock()
            need(type(value) is int and 0 <= value <= MAX_TIME)
            if self.origin is None and kind == "start":
                self.origin = value
            need(self.origin is not None)
            at = value - self.origin
            need(0 <= at <= MAX_TIME and (self.elapsed is None or at >= self.elapsed))
            self.elapsed = at
        except Exception:
            self.clock_valid = False
            self._fail("clock")
            return None
        return at

    def _advance(self):
        if self.elapsed is not None:
            if self.elapsed >= LIMITS["observation_ms"]:
                if self.cleanup_started_ms is None:
                    self._fail("observation_timeout")
                    self._cleanup(LIMITS["observation_ms"])
            if self.cleanup_deadline_ms is not None:
                if self.elapsed >= self.cleanup_deadline_ms:
                    self.expired = True
                    self._fail(
                        "global_timeout"
                        if self.elapsed >= LIMITS["total_ms"]
                        else "cleanup_timeout"
                    )

    def note(self, kind):
        need(type(kind) is str and kind in EVENTS and self._finished is None)
        if self._overflow:
            return
        self._record(kind, self._stamp(kind))

    def _record(self, kind, at):
        self._advance()
        if len(self.events) == LIMITS["max_events"] - 1:
            kind, self._overflow = "event_budget", True
        self.events.append({"event": kind, "at_ms": at})
        if kind == "cancelled":
            self._cancel_seen = True
        if kind in ERRORS - {"none"}:
            self._fail(kind)
            self._cleanup()
        if kind == "ready":
            if not self.facts["isolated"]:
                self._fail("invalid_proof")
            self._cleanup()
        if kind in FLAGS:
            if self.facts[kind]:
                self._fail("invalid_proof")
            dependencies = {
                "isolated": ("spawned",),
                "ready": ("isolated",),
                "term_requested": ("isolated",),
                "term_confirmed": ("term_requested",),
                "kill_requested": ("term_requested", "term_confirmed"),
                "kill_confirmed": ("kill_requested", "term_confirmed"),
                "group_empty": ("spawned",),
                "guard_waited": ("spawned",),
                "exit_ok": ("guard_waited",),
                "control_closed": ("guard_waited",),
            }
            if not all(self.facts[k] for k in dependencies.get(kind, ())):
                self._fail("invalid_proof")
            if kind in {"term_requested", "kill_requested"}:
                if self.cleanup_started_ms is None:
                    self._fail("invalid_proof")
                if kind == "kill_requested" and self.elapsed is not None:
                    if (
                        self._term_confirmed_ms is None
                        or self.elapsed < self._term_confirmed_ms + TERM_GRACE_MS
                    ):
                        self._fail("invalid_proof")
            self.facts[kind] = True
            if kind == "term_confirmed" and self._term_confirmed_ms is None:
                self._term_confirmed_ms = self.elapsed
        if kind in {"reaped_one", "reaped_two"}:
            if self.reaped_children or not self.facts["spawned"]:
                self._fail("invalid_proof")
            self.reaped_children = 1 if kind == "reaped_one" else 2

    def start(self):
        need(self.origin is None and not self.events)
        self.note("start")

    def tick(self):
        # Do not fill a bounded public trace with ordinary polls.
        before = (self.first_error, self.expired, self.cleanup_started_ms)
        at = self._stamp("tick")
        self._advance()
        if at is None or before != (
            self.first_error,
            self.expired,
            self.cleanup_started_ms,
        ):
            self._record("tick", at)

    def cancel(self):
        if not self._cancel_seen:
            self.note("cancelled")
        else:
            self.tick()

    def finish(self, evidence=None):
        if self._finished is not None:
            return copy.deepcopy(self._finished)
        if evidence is not None:
            evidence = validate_supervision_report(evidence)
        self.note("finish")
        expected = 2 if self.fixture in {"tree", "orphan"} else 1
        clean = bool(
            self.clock_valid
            and not self.expired
            and self.cleanup_deadline_ms is not None
            and self.elapsed < self.cleanup_deadline_ms
            and all(
                self.facts[k]
                for k in (
                    "spawned",
                    "isolated",
                    "ready",
                    "term_confirmed",
                    "group_empty",
                    "guard_waited",
                    "exit_ok",
                    "control_closed",
                )
            )
            and self.reaped_children == expected
            and (not self.facts["kill_requested"] or self.facts["kill_confirmed"])
        )
        if not self.facts["spawned"]:
            result, reason = "NOT RUN", self.first_error or "not_started"
            if reason == "none":
                reason = "not_started"
        elif self.first_error != "none":
            result, reason = "FAILURE", self.first_error
        elif not clean:
            result, reason = "FAILURE", "missing_proof"
        else:
            result, reason = "SUCCESS", "dummy_group_reaped"
        report = {
            **CONSTANTS,
            "proof_scope": self.scope,
            "fixture": self.fixture,
            "limits": dict(LIMITS),
            "term_grace_ms": TERM_GRACE_MS,
            "events": self.events,
            **self.facts,
            "reaped_children": self.reaped_children,
            "elapsed_ms": self.elapsed,
            "cleanup_started_ms": self.cleanup_started_ms,
            "cleanup_deadline_ms": self.cleanup_deadline_ms,
            "clock_valid": self.clock_valid,
            "expired": self.expired,
            "first_error": self.first_error,
            "cleanup_attested": clean,
            "os_cleanup_attested": clean and self.scope == "benign_local_process",
            "fixture_evidence": evidence,
            "result": result,
            "reason": reason,
        }
        need(len(json.dumps(report, separators=(",", ":")).encode()) <= 8192)
        self._finished = copy.deepcopy(report)
        return report


# Fixed benign code ONLY. -I -S, empty inherited environment and /dev/null
# streams. The auxiliary is a subreaper in its OWN session; targets occupy a
# different process group. It stays alive to reap an orphan after its parent dies.
# No module/path/source/command from an input or report is executed here.
_DUMMY_SOURCE = r"""
import ctypes, os, selectors, signal, struct, sys, time
kind, r, w = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
signal.pthread_sigmask(signal.SIG_SETMASK, [])
def emit(t, n=0): os.write(w, struct.pack('!cI', t, n))
libc = ctypes.CDLL(None, use_errno=True)
flag = ctypes.c_int()
if (libc.prctl(36, 1, 0, 0, 0) != 0 or
    libc.prctl(37, ctypes.byref(flag), 0, 0, 0) != 0 or flag.value != 1 or
    signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL or
    any(k != 'LC_CTYPE' for k in os.environ)):
    emit(b'E'); os._exit(2)
ready_r, ready_w = os.pipe()
worker = os.fork()
if worker == 0:
    os.close(r); os.close(w); os.close(ready_r)
    os.setpgid(0, 0)
    if kind != 'cooperative': signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if kind in ('tree', 'orphan'):
        leaf = os.fork()
        if leaf:
            os.close(ready_w)
            if kind == 'orphan': os._exit(0)
            while True: signal.pause()
    os.write(1, b'PRIVATE_D5_STDOUT')
    os.write(2, b'PRIVATE_D5_STDERR')
    os.write(ready_w, b'R'); os.close(ready_w)
    while True: signal.pause()
os.close(ready_w)
os.setpgid(worker, worker)
selector = selectors.DefaultSelector()
selector.register(r, selectors.EVENT_READ)
selector.register(ready_r, selectors.EVENT_READ)
end, acknowledged, reaped, done, killed = time.monotonic()+3, False, 0, False, False
expected = 2 if kind in ('tree', 'orphan') else 1
def send(sig, token=None):
    global killed
    try: os.killpg(worker, sig)
    except ProcessLookupError: return
    if token is not None: emit(token)
    if sig == signal.SIGKILL: killed = True
try:
    while True:
        for key, _ in selector.select(0.005):
            if key.fd == ready_r:
                token = os.read(ready_r, 1)
                selector.unregister(ready_r); os.close(ready_r)
                if token != b'R': raise ValueError()
                emit(b'R', worker)
            else:
                token = os.read(r, 1)
                if token == b'A': acknowledged = True
                elif token == b'T': send(signal.SIGTERM, b'T')
                elif token == b'K': send(signal.SIGKILL, b'K')
                elif not token:
                    selector.unregister(r); os.close(r)
                    acknowledged = True; send(signal.SIGKILL)
                else: raise ValueError()
        # Hold the leader PID/zombie until the parent has verified SID/PGID.
        if acknowledged:
            while True:
                try: pid, _ = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError: done = True; break
                if not pid: break
                reaped += 1
        if done:
            try: os.killpg(worker, 0)
            except ProcessLookupError:
                if reaped == expected:
                    emit(b'C', reaped); os._exit(0)
            raise ValueError()
        if time.monotonic() >= end:
            if not killed:
                emit(b'E'); acknowledged = True; send(signal.SIGKILL)
                end += 0.5
            else: raise ValueError()
except BaseException:
    send(signal.SIGKILL)
    # Known pause-only children are killable. Reap even on control failure;
    # this is NOT a successful receipt or a report copied from stdout.
    reap_end = time.monotonic()+0.5
    for _ in range(101):
        try: pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError: break
        if time.monotonic() >= reap_end: break
        if not pid: time.sleep(0.005)
    try: emit(b'E')
    except OSError: pass
    os._exit(2)
"""


class _LocalDummy:
    """Own fixed auxiliary/control descriptors. Never accept argv/env/path."""

    def __init__(self, fixture):
        need(sys.platform == "linux" and fixture in FIXTURES)
        # Never change the host's signal policy. Refuse a disposition that can
        # reap elsewhere or make Popen synthesize status zero on ECHILD.
        need(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL)
        self.fixture, self.buffer = fixture, b""
        self.process = None
        self.closed = False
        self._descriptors = set()
        self._directory = tempfile.TemporaryDirectory(prefix="info-process-probe-")
        try:
            r, self.command = os.pipe()
            self.status, w = os.pipe()
            self._descriptors.update((r, self.command, self.status, w))
            previous = signal.pthread_sigmask(
                signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM}
            )
            try:
                self.process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        _DUMMY_SOURCE,
                        fixture,
                        str(r),
                        str(w),
                    ],
                    cwd=self._directory.name,
                    env={},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                    pass_fds=(r, w),
                )
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            for fd in (r, w):
                os.close(fd)
                self._descriptors.remove(fd)
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.status, selectors.EVENT_READ)
        except BaseException:
            self.close()
            raise

    def signal(self, kind):
        need(kind in {"term", "kill"})
        os.write(self.command, b"T" if kind == "term" else b"K")

    def poll(self):
        events = []
        if self.selector.select(POLL_MS / 1000):
            data = os.read(self.status, 65)
            need(len(self.buffer) + len(data) <= 64)
            self.buffer += data
            while len(self.buffer) >= 5:
                kind, number = struct.unpack("!cI", self.buffer[:5])
                self.buffer = self.buffer[5:]
                if kind == b"R":
                    pid = self.process.pid
                    need(owns_process_group(pid, number))
                    self.worker_group = number
                    os.write(self.command, b"A")
                    events.extend(("isolated", "ready"))
                elif kind in (b"T", b"K") and number == 0:
                    events.append(
                        "term_confirmed" if kind == b"T" else "kill_confirmed"
                    )
                elif kind == b"C" and number in (1, 2):
                    events.extend(
                        ("reaped_one" if number == 1 else "reaped_two", "group_empty")
                    )
                else:
                    raise InvalidProcessGuard()
            if not data and self.process.poll() is not None and not events:
                events.append("missing_proof")
        return events

    def wait(self, seconds):
        return self.process.wait(timeout=seconds)

    def close(self):
        if self.closed:
            return
        # EOF independently makes the fixed subreaper kill/reap its children.
        # Do not SIGKILL the adopter before it has reaped descendants.
        for fd in tuple(self._descriptors):
            os.close(fd)
            self._descriptors.remove(fd)
        if hasattr(self, "selector"):
            self.selector.close()
        try:
            if self.process is not None:
                self.process.wait(timeout=4)
        finally:
            self._directory.cleanup()
        self.closed = True


def _drive(port, budget, *, cancelled):
    """Private port injection for model tests; only our exact port claims OS scope."""
    if type(port) is _LocalDummy:
        budget.scope = "benign_local_process"
    budget.note("spawned")
    try:
        for _ in range(720_100):  # Fixed poll cadence plus hard monotone deadlines.
            try:
                budget.tick()
                if cancelled():
                    budget.cancel()
                for event in port.poll():
                    budget.note(event)
                if budget.facts["group_empty"]:
                    try:
                        remaining = (budget.cleanup_deadline_ms - budget.elapsed) / 1000
                        code = port.wait(max(0, min(2, remaining)))
                        budget.note("guard_waited")
                        if code == 0:
                            budget.note("exit_ok")
                    except Exception:
                        budget.note("wait_failed")
                    break
                if budget.cleanup_started_ms is not None:
                    if budget.facts["isolated"] and not budget.facts["term_requested"]:
                        budget.note("term_requested")
                        port.signal("term")
                    if (
                        budget.facts["term_requested"]
                        and not budget.facts["kill_requested"]
                        and budget._term_confirmed_ms is not None
                        and budget.elapsed >= budget._term_confirmed_ms + TERM_GRACE_MS
                    ):
                        budget.note("kill_requested")
                        port.signal("kill")
                if budget.expired or not budget.clock_valid or budget._overflow:
                    break
            except KeyboardInterrupt:
                budget.cancel()
            except Exception:
                budget.note("control_error")
                break
        else:
            budget.note("event_budget")
    finally:
        try:
            port.close()
            budget.note("control_closed")
        except (Exception, KeyboardInterrupt):
            budget.note("wait_failed")


def run_dummy(*, fixture="cooperative", evidence=None, cancel=None):
    """Only a fixed local probe. Never consume a command/path/env from a report.

    Optional D4 evidence is synthetic, parent supplied and UNBOUND to this
    process. SUCCESS here is process-control success, never Info/TLS success.
    """
    need(type(fixture) is str and fixture in FIXTURES)
    need(cancel is None or type(cancel) is threading.Event)
    if evidence is not None:
        evidence = validate_supervision_report(evidence)
    budget = ProcessBudget(
        clock_ms=lambda: time.monotonic_ns() // 1_000_000, fixture=fixture
    )
    budget.start()
    if cancel is not None and cancel.is_set():
        budget.cancel()
    elif budget.clock_valid:
        try:
            port = _LocalDummy(fixture)
        except (Exception, KeyboardInterrupt):
            budget.note("control_error")
        else:
            _drive(
                port, budget, cancelled=lambda: cancel is not None and cancel.is_set()
            )
    return validate_process_report(budget.finish(evidence))


def validate_process_report(report):
    """Closed/replayed consistency only; never authenticate an external report."""
    try:
        need(type(report) is dict)
        fixture = report["fixture"]
        now = [0]
        replay = ProcessBudget(clock_ms=lambda: now[0], fixture=fixture)
        scope = report["proof_scope"]
        need(
            type(scope) is str
            and scope
            in {
                "synthetic_process_events",
                "benign_local_process",
            }
        )
        replay.scope = scope
        evidence = report["fixture_evidence"]
        if evidence is not None:
            validate_supervision_report(evidence)
        events = report["events"]
        need(type(events) is list and len(events) <= LIMITS["max_events"])
        need(all(type(entry) is dict for entry in events))
        need(events and events[0].get("event") == "start")
        need(sum(e.get("event") == "start" for e in events) == 1)
        for index, entry in enumerate(events):
            need(type(entry) is dict and entry.keys() == {"event", "at_ms"})
            kind, at = entry["event"], entry["at_ms"]
            need(type(kind) is str and kind in EVENTS)
            need(at is None or type(at) is int and 0 <= at <= MAX_TIME)
            now[0] = at
            if kind == "finish":
                need(index == len(events) - 1)
                replay.finish(evidence)
            else:
                replay.note(kind)
        expected = replay.finish(evidence)
        need(report.keys() == expected.keys())
        # JSON equality alone confuses bool/int and 1/1.0; compare types too.
        for key, value in expected.items():
            need(type(report[key]) is type(value) and report[key] == value)
        need(
            type(report["limits"]) is dict
            and all(type(v) is int for v in report["limits"].values())
        )
        need(len(json.dumps(report, separators=(",", ":")).encode()) <= 8192)
        return copy.deepcopy(report)
    except Exception:
        raise InvalidProcessGuard() from None
