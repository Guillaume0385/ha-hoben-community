"""PID 1 guardian outside the HA worker; private offline sandbox only.

No secret reader, network setup, Actions context or live entry. PID namespace
exit is the final cleanup for descendants that escaped the worker's session.
The worker runs as another UID and cannot signal or replace this guardian.
"""

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ha_live_proof import (  # noqa: E402
    MEMORY_BYTES,
    PIDS,
    PROCESS_MS,
    USEFUL_MS,
    build_report,
    empty_evidence,
)
from scripts.ha_session_evidence import require  # noqa: E402

RECEIPT = Path("/run/hoben/receipt.json")
PROVENANCE = {"merge_sha": "0" * 40, "pr_number": 1, "run_id": 1, "run_attempt": 1}
stopping = False
released = False
worker_started = False


def stop(signum, frame):
    global stopping
    stopping = True


def release(signum, frame):
    global released
    released = True


def metrics():
    root = Path("/sys/fs/cgroup")

    def value(name):
        return int((root / name).read_text())

    def events(name):
        return dict(line.split() for line in (root / name).read_text().splitlines())

    return {
        "memory_bytes": value("memory.max"),
        "pids": value("pids.max"),
        "swap": value("memory.swap.max"),
        "oom_killed": int(events("memory.events")["oom_kill"]) > 0,
        "pids_limited": int(events("pids.events")["max"]) > 0,
    }


def worker_deadline(limits, hard_deadline_ns, now_ns):
    """Allow startup/final proof/HA close, keeping independent hard-stop margin.

    With nominal bounds, the worker can return its proof after 300 s and clean
    up until 340 s. The last 20 s remain for termination/reaping/controller.
    Tightened offline limits scale the margins down, never extend 360 s.
    """
    grace_ms = min(40_000, limits["process_ms"] // 6)
    reserve_ms = min(20_000, limits["process_ms"] // 4)
    return min(
        now_ns + (limits["useful_ms"] + grace_ms) * 1_000_000,
        hard_deadline_ns - reserve_ms * 1_000_000,
    )


def run(case, limits, deadline_ns):
    """Attest cgroup bounds before the unprivileged worker can execute."""
    global worker_started
    require(os.getpid() == 1 and os.getuid() == 0)
    require(set(limits) == {"memory_bytes", "pids", "useful_ms", "process_ms"})
    for name, maximum in (
        ("memory_bytes", MEMORY_BYTES),
        ("pids", PIDS),
        ("useful_ms", USEFUL_MS),
        ("process_ms", PROCESS_MS),
    ):
        require(type(limits[name]) is int and 0 < limits[name] <= maximum)
    observed = metrics()
    require(
        observed["swap"] == 0
        and observed["memory_bytes"] == limits["memory_bytes"]
        and observed["pids"] == limits["pids"]
    )
    require(type(deadline_ns) is int and time.monotonic_ns() < deadline_ns)
    require(deadline_ns - time.monotonic_ns() <= limits["process_ms"] * 1_000_000)
    if stopping:
        return {
            "started": False,
            "reason": "cancelled",
            "oom_killed": False,
            "pids_limited": False,
            "evidence": empty_evidence(),
        }
    # The outer deadline was armed before Docker start. Never reset it here.
    started_ns = time.monotonic_ns()
    end = worker_deadline(limits, deadline_ns, started_ns) / 1e9
    require(end > time.monotonic())
    evidence, reason, output = empty_evidence(), "worker_failure", bytearray()
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    started = False
    process = None
    try:
        # Group/cgroup membership and the guardian's absolute timer exist first.
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(ROOT / "tests/fixtures/ha_session_worker.py"),
                case,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HA_EVIDENCE_FD": str(write_fd),
            },
            pass_fds=(write_fd,),
            start_new_session=True,
            user=65534,
            group=65534,
            extra_groups=[],
        )
        started = worker_started = True
        os.close(write_fd)
        write_fd = None
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ)
            while time.monotonic() < end and not stopping:
                for _key, _events in selector.select(
                    min(0.05, max(0, end - time.monotonic()))
                ):
                    data = os.read(read_fd, 8193 - len(output))
                    if not data:
                        selector.unregister(read_fd)
                    output.extend(data)
                if len(output) > 8192:
                    break
                if process.poll() is not None:
                    # Read all remaining bounded evidence before interpreting it.
                    while len(output) <= 8192:
                        try:
                            data = os.read(read_fd, 8193 - len(output))
                        except BlockingIOError:
                            break
                        if not data:
                            break
                        output.extend(data)
                    if process.returncode == 0 and output:
                        candidate = json.loads(output)
                        require(
                            json.dumps(
                                candidate, separators=(",", ":"), allow_nan=False
                            ).encode()
                            == output
                        )
                        receipt = {
                            "started": True,
                            "reason": "completed",
                            **limits,
                            "elapsed_ms": (time.monotonic_ns() - started_ns)
                            // 1_000_000,
                            "oom_killed": False,
                            "pids_limited": False,
                            "reaped": True,
                            "network": "none",
                        }
                        build_report(PROVENANCE, receipt, candidate)
                        evidence, reason = candidate, "completed"
                    break
            else:
                reason = "cancelled" if stopping else "timeout"
    except Exception:
        reason = "worker_failure"
    finally:
        if process is not None:
            # Give responsive HA a bounded chance to run its async_close. The
            # independent guardian still kills an unresponsive original session;
            # PID 1 exit handles descendants that escaped that session.
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(
                        timeout=max(
                            0.001, min(10, deadline_ns / 1e9 - time.monotonic() - 1.5)
                        )
                    )
                except subprocess.TimeoutExpired:
                    pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(
                    timeout=max(0.001, min(0.5, deadline_ns / 1e9 - time.monotonic()))
                )
            except subprocess.TimeoutExpired:
                reason = "timeout"
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
    observed = metrics()
    if observed["oom_killed"]:
        reason = "memory"
    elif observed["pids_limited"]:
        reason = "processes"
    return {
        "started": started,
        "reason": reason,
        "oom_killed": observed["oom_killed"],
        "pids_limited": observed["pids_limited"],
        "evidence": evidence,
    }


def main():
    signal.signal(signal.SIGUSR1, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGUSR2, release)
    deadline = time.monotonic_ns() + 1_000_000_000
    try:
        case, limits_json = sys.argv[1:]
        RECEIPT.parent.chmod(0o700)
        received = int((RECEIPT.parent / "deadline").read_text())
        require(0 < received - time.monotonic_ns() <= PROCESS_MS * 1_000_000)
        deadline = received
        result = run(case, json.loads(limits_json), deadline)
    except Exception:
        result = {
            "started": worker_started,
            "reason": "worker_failure" if worker_started else "unavailable",
            "oom_killed": False,
            "pids_limited": False,
            "evidence": empty_evidence(),
        }
    try:
        encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 8192:
            return 1
        RECEIPT.parent.mkdir(mode=0o700, exist_ok=True)
        temporary = RECEIPT.with_suffix(".pending")
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(encoded)
        os.replace(temporary, RECEIPT)
        # The host copies only the bounded receipt, then acknowledges release.
        # If the host disappears, the original deadline still exits PID 1.
        while not released and time.monotonic_ns() < deadline - 1_000_000_000:
            time.sleep(0.02)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    # Kernel PID-namespace teardown also terminates setsid descendants.
    os._exit(main())
