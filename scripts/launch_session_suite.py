"""Fixed external supervisor: 360/600 s per phase and 1020 s for the suite.

The candidate cannot start phase two until this parent has armed its deadline
and acknowledged the sole fixed IPC transition. No budget or mode is an input.
All candidate stdout/stderr are discarded; only one control byte is inspected.
"""

import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

ALLOWED = (
    "GITHUB_ACTIONS",
    "GITHUB_REPOSITORY",
    "GITHUB_REF",
    "GITHUB_EVENT_NAME",
    "GITHUB_ACTOR",
    "GITHUB_TRIGGERING_ACTOR",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_WORKFLOW_REF",
    "GITHUB_WORKFLOW_SHA",
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "SESSION_SUITE_APPROVED_SHA",
    "SESSION_SUITE_CANDIDATE_SHA",
    "SESSION_SUITE_APPROVED_PR",
    "RUNNER_TEMP",
    "HOBEN_USER_GUID",
    "HOBEN_DEVICE_GUID",
)


def collector_environment(source):
    """Do not inherit runner tokens, OIDC, Python hooks or Actions command files."""
    return {
        **{k: source[k] for k in ALLOWED if k in source},
        "PATH": "/usr/bin:/bin",
        "SESSION_SUITE_PHASE": "live",
    }


def supervise(candidate, source, *, clock=time.monotonic):
    """Own one process group and its fixed transition, including descendants.

    Stop one second before each hard limit, reserving that second for SIGKILL
    and reaping. An asyncio cancellation-resistant candidate cannot extend it.
    No report is fabricated on timeout, malformed IPC or process failure.
    """
    started = clock()
    global_end, phase_end = started + 1020, started + 360
    descriptors = set()
    process = None
    try:
        control_r, control_w = os.pipe()
        descriptors.update((control_r, control_w))
        ack_r, ack_w = os.pipe()
        descriptors.update((ack_r, ack_w))
        environment = collector_environment(source) | {
            "SESSION_SUITE_CONTROL_FD": str(control_w),
            "SESSION_SUITE_ACK_FD": str(ack_r),
        }
        # Deliver a stop only after ownership of the new process is recorded.
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT}
        )
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", str(candidate / "scripts/run_session_suite.py")],
                cwd=candidate,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(control_w, ack_r),
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        for descriptor in (control_w, ack_r):
            os.close(descriptor)
            descriptors.remove(descriptor)
        phase_two = False
        with selectors.DefaultSelector() as selector:
            selector.register(control_r, selectors.EVENT_READ)
            while True:
                remaining = min(global_end, phase_end) - clock() - 1
                if remaining <= 0:
                    return 1
                result = process.poll()
                if result is not None:
                    return 0 if result == 0 else 1
                if selector.select(timeout=min(0.2, remaining)):
                    token = os.read(control_r, 2)
                    if not token:
                        selector.unregister(control_r)
                    elif token != b"2" or phase_two:
                        return 1
                    else:
                        # Arm before ACK. The candidate is still blocked before
                        # constructing its second lifecycle, after first cleanup.
                        phase_end = clock() + 600
                        if min(global_end, started + 360) - clock() <= 1:
                            return 1
                        phase_two = True
                        os.write(ack_w, b"2")
    finally:
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT}
        )
        try:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=max(0.001, min(1, global_end - clock())))
        finally:
            try:
                for descriptor in descriptors:
                    os.close(descriptor)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


class LauncherStopped(BaseException):
    """A parent stop signal must pass through process-group cleanup."""


def main():
    def stop(signum, frame):
        raise LauncherStopped()

    original = signal.signal(signal.SIGTERM, stop)
    try:
        if len(sys.argv) != 1:
            return 1
        candidate = Path(__file__).resolve().parents[2] / "candidate"
        return supervise(candidate, os.environ)
    except (Exception, KeyboardInterrupt, LauncherStopped):
        return 1
    finally:
        signal.signal(signal.SIGTERM, original)


if __name__ == "__main__":
    raise SystemExit(main())
