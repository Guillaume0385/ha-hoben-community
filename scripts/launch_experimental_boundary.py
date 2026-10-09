"""Launch the reviewed experimental collector with an explicit environment.

The parent has no GitHub write permission. No runner/Actions/OIDC token, output
command file, arbitrary input or dependency installation reaches the child.
"""

import os
import shutil
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
    "GITHUB_EVENT_PATH",
    "EXPERIMENTAL_APPROVED_SHA",
    "RUNNER_TEMP",
    "HOBEN_USER_GUID",
    "HOBEN_DEVICE_GUID",
)
ROOT = Path(__file__).resolve().parents[1]


def collector_environment(source: dict[str, str]) -> dict[str, str]:
    """Allow identities only for this one bounded child; never print values."""
    return {
        **{k: source[k] for k in ALLOWED if k in source},
        "PATH": "/usr/bin:/bin",
        "EXPERIMENTAL_PHASE": "live",
    }


def main() -> int:
    try:
        candidate = ROOT.parent / "candidate"
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(candidate / "scripts/run_experimental_boundary.py"),
                "live",
            ],
            cwd=candidate,
            env=collector_environment(dict(os.environ)),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30 * 60,
        )
        return 0 if result.returncode == 0 else 1
    except (Exception, KeyboardInterrupt):
        return 1
    finally:
        # A subprocess timeout can kill it before its own cleanup. No plaintext
        # artifact is exported; remove its fixed private staging when possible.
        storage = os.environ.get("RUNNER_TEMP")
        if storage:
            for private in Path(storage).glob("hoben-experimental-private-*"):
                if private.is_dir() and not private.is_symlink():
                    shutil.rmtree(private, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
