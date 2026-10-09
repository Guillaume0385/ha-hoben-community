"""Fixed, token-free subprocess launcher for the reviewed HA-parity scenario.

The Actions job receives GitHub read-only access. The Hoben-bearing child gets
only an explicit allowlist, no GITHUB_TOKEN, OIDC, Actions command files, or
user-provided arguments. It never inherits stdout/stderr into public logs.
"""
from __future__ import annotations

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
    "LIVE_APPROVED_SHA",
    "RUNNER_TEMP",
    "HOBEN_USER_GUID",
    "HOBEN_DEVICE_GUID",
)
ROOT = Path(__file__).resolve().parents[1]


def child_environment(env: dict[str, str]) -> dict[str, str]:
    return {**{key: env[key] for key in ALLOWED if key in env},
            "PATH": "/usr/bin:/bin"}


def main() -> int:
    try:
        candidate = ROOT.parent / "candidate"
        result = subprocess.run(
            [sys.executable, "-I", str(candidate / "scripts/run_live_ha_parity.py")],
            cwd=candidate,
            env=child_environment(dict(os.environ)),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=180,
        )
        return 0 if result.returncode == 0 else 1
    except (Exception, KeyboardInterrupt):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
