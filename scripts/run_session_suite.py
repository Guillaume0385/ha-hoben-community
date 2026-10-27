"""Single fixed suite entry point; no public mode for scenario two alone."""

import asyncio
import json
import os
import signal
import stat
import subprocess
import sys
from functools import partial
from pathlib import Path

# The supervisor briefly masks stop signals while acquiring process ownership.
# Restore normal delivery in this isolated child before collecting anything.
if __name__ == "__main__":
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM, signal.SIGINT})

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.hoben.v4_lifecycle import V4Lifecycle  # noqa: E402
from custom_components.hoben.v4_session import V4Session  # noqa: E402
from scripts.run_session_300 import context_proof, require, write_report  # noqa: E402
from scripts.session_suite import observe_suite, validate_suite  # noqa: E402

MAX_REPORT_BYTES = 8192


def suite_proof(source):
    """Keep the same push/actor/SHA proof, with no legacy approval fallback."""
    return context_proof(
        source
        | {
            "SESSION300_PHASE": source.get("SESSION_SUITE_PHASE", ""),
            "SESSION300_APPROVED_SHA": source.get("SESSION_SUITE_APPROVED_SHA", ""),
            "SESSION300_CANDIDATE_SHA": source.get("SESSION_SUITE_CANDIDATE_SHA", ""),
            "SESSION300_APPROVED_PR": source.get("SESSION_SUITE_APPROVED_PR", ""),
        },
        native_rerun=True,
    )


def phase_channels(source):
    descriptors = []
    for key in ("SESSION_SUITE_CONTROL_FD", "SESSION_SUITE_ACK_FD"):
        value = source.get(key, "")
        require(value.isascii() and value.isdecimal())
        descriptor = int(value)
        require(descriptor > 2 and stat.S_ISFIFO(os.fstat(descriptor).st_mode))
        descriptors.append(descriptor)
    require(descriptors[0] != descriptors[1])
    return descriptors


def main():
    channels = []
    try:
        require(len(sys.argv) == 1)
        proof = suite_proof(os.environ)
        actual = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"},
                timeout=5,
            )
            .decode()
            .strip()
        )
        require(actual == proof["merge_sha"])
        channels = phase_channels(os.environ)
        user = os.environ.pop("HOBEN_USER_GUID")
        device = os.environ.pop("HOBEN_DEVICE_GUID", "") or "0" * 32

        def factory(budget, policy):
            if policy is not None:
                require(os.write(channels[0], b"2") == 1)
                require(os.read(channels[1], 1) == b"2")
            return V4Lifecycle(
                user_guid=user,
                device_guid=device,
                retry_delays=(1.0, 2.0),
                session_factory=partial(
                    V4Session, session_300=budget, no_pong_after_120=policy
                ),
            )

        report = validate_suite(asyncio.run(observe_suite(factory, proof)), proof)
        require(len(json.dumps(report).encode("utf-8")) <= MAX_REPORT_BYTES)
        directory = Path(os.environ["RUNNER_TEMP"]) / "hoben-session-suite-exports"
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
        write_report(directory / "report.json", report)
        return 0  # A valid non-success report is published as non-success.
    except (Exception, KeyboardInterrupt):
        return 1
    finally:
        for descriptor in channels:
            os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
