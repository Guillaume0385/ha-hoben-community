"""MANAGER-only GitHub Actions H1/H2 exploration for #48, never automatic CI.

The trusted opened-client-boundary.yml must first be installed on protected main.
Only encrypted captures and fixed anonymized reports leave the runner. This tool
does not confirm a boundary or modify HobenClient, HA or the existing live gate.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.hoben.myhoben import (  # noqa: E402
    INITIAL_DEVICE_GUID,
    normalize_user_guid,
)
from scripts.boundary_archive import prepare_recipient, seal_captures  # noqa: E402
from scripts.boundary_capture import private_json, run_campaign  # noqa: E402

REPOSITORY = "Guillaume0385/ha-hoben-community"
WORKFLOW_REF = (
    f"{REPOSITORY}/.github/workflows/opened-client-boundary.yml@refs/heads/main"
)


class SafeParser(argparse.ArgumentParser):
    """Never echo accidental secrets or CLI input in argument errors."""

    def error(self, message: str) -> None:
        self.exit(2, "Invalid boundary-probe arguments; use --help.\n")


def verify_actions_context() -> None:
    """Refuse local use, other actors, replay and a changed candidate checkout."""
    expected = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
    }
    sha = os.environ.get("HOBEN_BOUNDARY_APPROVED_SHA", "")
    if any(os.environ.get(k) != v for k, v in expected.items()) or not re.fullmatch(
        r"[0-9a-f]{40}", sha
    ):
        raise ValueError("Trusted GitHub MANAGER dispatch required")
    checkout = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    ).stdout.strip()
    if checkout != sha:
        raise ValueError("Reviewed checkout mismatch")


async def campaign_with_signals(private: Path, **kwargs) -> dict:
    """SIGTERM cancels the session and lets the CLI seal saved partial captures."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        return await run_campaign(private, **kwargs)
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


def main(argv: list[str] | None = None) -> int:
    """Opt-in collection; every failure message is fixed and payload-free."""
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--live", required=True, action="store_true")
    parser.add_argument("--mode", required=True, choices=("H1", "H2", "both"))
    parser.add_argument("--seconds", type=int, default=90, choices=range(30, 91))
    parser.add_argument("--recipient-sha256", required=True)
    args = parser.parse_args(argv)
    private = None
    exports = None
    try:
        verify_actions_context()
        root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        checkout = Path(__file__).resolve().parents[1]
        if root == checkout or root.is_relative_to(checkout) or not root.is_dir():
            raise ValueError("Private runner storage required")
        user_guid = normalize_user_guid(os.environ["HOBEN_USER_GUID"])
        device_guid = os.environ.get("HOBEN_DEVICE_GUID") or INITIAL_DEVICE_GUID
        if len(device_guid) != 32 or not device_guid.isascii():
            raise ValueError("Invalid private identity")
        private = Path(tempfile.mkdtemp(prefix="hoben-boundary-private-", dir=root))
        # Exports have a fixed location and are never a wildcard of private data.
        exports = root / "hoben-boundary-exports"
        exports.mkdir(mode=0o700)
        recipient = prepare_recipient(
            private, os.environ["HOBEN_CAPTURE_CERTIFICATE"], args.recipient_sha256
        )
        interrupted = False
        try:
            report = asyncio.run(
                campaign_with_signals(
                    private,
                    mode=args.mode,
                    user_guid=user_guid,
                    device_guid=device_guid,
                    seconds=args.seconds,
                )
            )
        except (KeyboardInterrupt, asyncio.CancelledError):
            interrupted = True
            sessions = [
                json.loads(path.read_text())
                for path in sorted(private.glob("session-*/analysis.json"))
            ]
            report = {
                "schema": 2,
                "campaign_mode": args.mode,
                "executed_sessions": len(sessions),
                "interrupted": True,
                "boundary_proven": False,
                "sessions": sessions,
            }
        except Exception:
            interrupted = True
            report = {
                "schema": 2,
                "campaign_mode": args.mode,
                "interrupted": True,
                "boundary_proven": False,
                "error": "campaign_failed",
            }
        seal_captures(private, exports, recipient)
        private_json(exports / "report.json", report)
        # Summaries read only this separate allowlisted JSON. No private path,
        # identity, exception text, packet hash or capture byte enters stdout.
        print("Encrypted capture and anonymized report prepared.")
        return 1 if interrupted else 0
    except Exception:
        print(
            "Boundary campaign unavailable; inspect protected prerequisites.",
            file=sys.stderr,
        )
        return 1
    finally:
        if private is not None:
            shutil.rmtree(private)


if __name__ == "__main__":
    raise SystemExit(main())
