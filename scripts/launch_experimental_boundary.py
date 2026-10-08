"""Trusted main launcher: discard runner tokens before entering reviewed code."""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Guillaume0385/ha-hoben-community"
WORKFLOW = (
    f"{REPOSITORY}/.github/workflows/hoben-experimental-request.yml@refs/heads/main"
)
CONTEXT = (
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
    "RUNNER_TEMP",
    "EXPERIMENTAL_APPROVED_SHA",
    "EXPERIMENTAL_PHASE",
)


def checkout_sha(directory: Path) -> str:
    """No credentials, inherited process environment, shell or arbitrary output."""
    result = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=directory,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        timeout=5,
        check=True,
    )
    return result.stdout.decode("ascii").strip()


def launch() -> None:
    """Only the fixed entry at the admitted SHA; secrets stay out of arguments."""
    expected = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "issues",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
        "EXPERIMENTAL_PHASE": "live",
    }
    main_sha = os.environ.get("GITHUB_SHA", "")
    candidate_sha = os.environ.get("EXPERIMENTAL_APPROVED_SHA", "")
    candidate = ROOT.parent / "candidate"
    script = candidate / "scripts/run_experimental_boundary.py"
    if (
        any(os.environ.get(k) != v for k, v in expected.items())
        or not re.fullmatch(r"[0-9a-f]{40}", main_sha)
        or not re.fullmatch(r"[0-9a-f]{40}", candidate_sha)
        or os.environ.get("GITHUB_WORKFLOW_SHA") != main_sha
        or checkout_sha(ROOT) != main_sha
        or not candidate.is_dir()
        or candidate.is_symlink()
        or not script.is_file()
        or script.is_symlink()
        or checkout_sha(candidate) != candidate_sha
    ):
        raise ValueError("Verified experimental prerequisite unavailable")
    # Never pass GITHUB_TOKEN/GH_TOKEN, Actions runtime credentials, PYTHONPATH,
    # debug flags or any arbitrary inherited value to the candidate process.
    clean = {k: os.environ[k] for k in CONTEXT if k in os.environ}
    clean["PATH"] = "/usr/bin:/bin"
    for k in ("HOBEN_USER_GUID", "HOBEN_DEVICE_GUID"):
        if k in os.environ:
            clean[k] = os.environ[k]
    os.execve(
        sys.executable,
        [sys.executable, "-I", str(script), "live"],
        clean,
    )


if __name__ == "__main__":
    try:
        launch()
    except Exception:
        # Neither a checkout path, identity, subprocess output nor exception is printed.
        raise SystemExit(1) from None
