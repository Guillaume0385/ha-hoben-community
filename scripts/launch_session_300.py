"""Fixed, secret-isolated process boundary with a hard 360 second deadline."""

import os
import subprocess
import sys
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
    "SESSION300_APPROVED_SHA",
    "SESSION300_CANDIDATE_SHA",
    "SESSION300_APPROVED_PR",
    "RUNNER_TEMP",
    "HOBEN_USER_GUID",
    "HOBEN_DEVICE_GUID",
)


def collector_environment(source):
    return {
        **{k: source[k] for k in ALLOWED if k in source},
        "PATH": "/usr/bin:/bin",
        "SESSION300_PHASE": "live",
    }


def main():
    try:
        candidate = Path(__file__).resolve().parents[2] / "candidate"
        result = subprocess.run(
            [sys.executable, "-I", str(candidate / "scripts/run_session_300.py")],
            cwd=candidate,
            env=collector_environment(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=360,
            check=False,
        )
        return 0 if result.returncode == 0 else 1
    except (Exception, KeyboardInterrupt):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
