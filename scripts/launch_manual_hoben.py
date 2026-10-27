"""Own the isolated group and fixed deadlines; expose only public stage enums."""

import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manual_hoben_context import PLANS, proof, require  # noqa: E402
from scripts.run_session_300 import write_report  # noqa: E402

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
    "GITHUB_EVENT_PATH",
    "MANUAL_HOBEN_SHA",
    "MANUAL_HOBEN_PR",
    "MANUAL_HOBEN_CANDIDATE",
    "MANUAL_HOBEN_SCENARIO",
    "RUNNER_TEMP",
    "HOBEN_USER_GUID",
    "HOBEN_DEVICE_GUID",
)
SECONDS = {"h1h2": 1800, "session-300": 360, "session-reconnect": 600}
TOKENS = {b"H": "h1h2", b"S": "session-300", b"R": "session-reconnect"}


def collector_environment(source):
    return {**{k: source[k] for k in ALLOWED if k in source}, "PATH": "/usr/bin:/bin"}


def supervise(candidate, source, *, clock=time.monotonic):
    selection, _ = proof(source, candidate)
    plan = PLANS[selection]
    started_at = clock()
    global_end = started_at + (2820 if selection == "all" else SECONDS[plan[0]])
    phase_end = started_at + SECONDS[plan[0]]
    suite_end = global_end
    directory = Path(source["RUNNER_TEMP"]) / "hoben-manual-control"
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    process, descriptors, started, complete = None, set(), [], False
    try:
        control_r, control_w = os.pipe()
        ack_r, ack_w = os.pipe()
        descriptors.update((control_r, control_w, ack_r, ack_w))
        environment = collector_environment(source) | {
            "MANUAL_CONTROL_FD": str(control_w),
            "MANUAL_ACK_FD": str(ack_r),
        }
        previous = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT}
        )
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", str(candidate / "scripts/run_manual_hoben.py")],
                cwd=candidate,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(control_w, ack_r),
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        for descriptor in (control_w, ack_r):
            os.close(descriptor)
            descriptors.remove(descriptor)
        with selectors.DefaultSelector() as selector:
            selector.register(control_r, selectors.EVENT_READ)
            while True:
                remaining = min(global_end, phase_end, suite_end) - clock() - 1
                if remaining <= 0:
                    break
                result = process.poll()
                if result is not None:
                    complete = result == 0 and bool(started)
                    break
                if selector.select(timeout=min(0.2, remaining)):
                    token = os.read(control_r, 2)
                    if not token:
                        selector.unregister(control_r)
                        continue
                    stage = TOKENS.get(token)
                    if min(global_end, phase_end, suite_end) - clock() <= 1:
                        break
                    if len(started) >= len(plan) or stage != plan[len(started)]:
                        break
                    if started:
                        phase_end = clock() + SECONDS[stage]
                    if selection == "all" and stage == "session-300":
                        suite_end = clock() + 1020
                    started.append(stage)
                    os.write(ack_w, token)  # Always arm before ACK.
    except (Exception, KeyboardInterrupt, Stopped):
        complete = False
    finally:
        previous = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT}
        )
        try:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=max(0.001, min(1, global_end - clock())))
            for descriptor in descriptors:
                os.close(descriptor)
            for path in Path(source["RUNNER_TEMP"]).glob(
                "hoben-experimental-private-*"
            ):
                require(path.is_dir() and not path.is_symlink())
                shutil.rmtree(path)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
    write_report(
        directory / "report.json",
        {
            "schema": 1,
            "selection": selection,
            "started": started,
            "process_ok": complete,
        },
    )
    return 0  # A safely collected FAILURE is also published, never a fake success.


class Stopped(BaseException):
    pass


def main():
    def stop(signum, frame):
        raise Stopped()

    original = signal.signal(signal.SIGTERM, stop)
    try:
        require(len(sys.argv) == 1)
        return supervise(ROOT.parent / "candidate", os.environ)
    except (Exception, KeyboardInterrupt, Stopped):
        return 1
    finally:
        signal.signal(signal.SIGTERM, original)


if __name__ == "__main__":
    raise SystemExit(main())
