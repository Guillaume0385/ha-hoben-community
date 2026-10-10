"""Run the real HA protocol client twice; no probes, writes, or secret output.

This tests the existing one-shot client/decoder path, not an invented persistent
session or HA scheduler. Only the MANAGER-gated Actions job may supply credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

# -I excludes the working directory. Import only the actual HA protocol package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.hoben.client import HobenClient  # noqa: E402
from custom_components.hoben.profiles import StoveProfile  # noqa: E402
from custom_components.hoben.v4_state import decode_v4_snapshot  # noqa: E402

SCENARIO = "ha-parity"
BUDGET_SECONDS = 150
REQUIRED = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
    "GITHUB_REF": "refs/heads/experimental",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_ACTOR": "Guillaume0385",
    "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
}
SHA_RE = re.compile(r"[a-f0-9]{40}")


def context_valid(env: dict[str, str]) -> bool:
    """Refuse incomplete workflow context before constructing the TLS client."""
    sha = env.get("GITHUB_SHA", "")
    return (
        all(env.get(key) == value for key, value in REQUIRED.items())
        and SHA_RE.fullmatch(sha) is not None
        and bool(
            re.fullmatch(
                r"(?:[1-9]|[1-4][0-9]|50)",
                env.get("GITHUB_RUN_ATTEMPT", ""),
            )
        )
        and env.get("LIVE_APPROVED_SHA") == sha
        and env.get("GITHUB_WORKFLOW_REF")
        == (
            "Guillaume0385/ha-hoben-community/"
            ".github/workflows/hoben-live-experimental.yml@refs/heads/experimental"
        )
        and env.get("GITHUB_WORKFLOW_SHA") == sha
        and env.get("GITHUB_RUN_ID", "").isascii()
        and env.get("GITHUB_RUN_ID", "").isdigit()
        and int(env.get("GITHUB_RUN_ID", "0")) > 0
        and bool(env.get("HOBEN_USER_GUID"))
        and bool(env.get("RUNNER_TEMP"))
    )


def empty_report() -> dict[str, object]:
    """Fixed public schema; no household values, GUIDs or exception strings."""
    return {
        "schema": 1,
        "scenario": SCENARIO,
        "status": "failure",
        "refreshes_completed": 0,
        "decoded_refreshes": 0,
        "device_identity_assigned": False,
        "device_identity_reused": False,
        "closed": False,
        "session_mode": "one-shot",
        "ping_pong": "unsupported",
        "data_updated": "unsupported",
        "persistent_session": "unsupported",
        "reconnect": "not_tested",
        "error": "client_failure",
    }


async def observe(
    user_guid: str,
    device_guid: str | None,
    *,
    client_factory=HobenClient,
    decoder=decode_v4_snapshot,
) -> dict[str, object]:
    """Use HA's actual HobenClient.async_refresh and V4 decoder unchanged.

    Every async_refresh internally opens a separate verified TLS session and
    performs one correlated function-04 read. Disallow transport retries.
    Never call association, code provider or any write operation.
    """
    report = empty_report()
    client = client_factory(
        user_guid=user_guid,
        device_guid=device_guid,
        max_attempts=1,
        retry_delay=0,
        handshake_timeout=30,
        read_timeout=30,
    )
    try:
        async with asyncio.timeout(BUDGET_SECONDS):
            first_identity = None
            for index in range(2):
                if index == 1 and not client.has_assigned_device_guid:
                    raise RuntimeError("unassigned")
                snapshot = await client.async_refresh()
                if (
                    snapshot.profile is not StoveProfile.V4
                    or len(snapshot.registers) != 20
                ):
                    raise RuntimeError("unsupported")
                decoder(snapshot)  # HA coordinator calls this exact decoder.
                report["refreshes_completed"] = index + 1
                report["decoded_refreshes"] = index + 1
                report["device_identity_assigned"] = client.has_assigned_device_guid
                if index == 0:
                    first_identity = client.device_guid_for_persistence
                else:
                    report["device_identity_reused"] = (
                        client.has_assigned_device_guid
                        and client.device_guid_for_persistence == first_identity
                    )
            report["status"] = "success"
            report["error"] = "none"
    except TimeoutError:
        report["error"] = "timeout"
    except Exception:
        # No exception string, packet, register, device ID or stack is exported.
        report["error"] = "client_failure"
    finally:
        try:
            await client.async_close()  # HA unload closes this exact client API.
            report["closed"] = True
        except BaseException:
            report["status"] = "failure"
            report["error"] = "close_failure"
    if not report["closed"] or not report["device_identity_reused"]:
        report["status"] = "failure"
    return report


def write_report(report: dict[str, object], storage: str) -> bool:
    """Write only a fixed projection to a private, fixed runner path."""
    try:
        root = Path(storage).resolve(strict=True)
        directory = root / "hoben-live-public"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / "report.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, separators=(",", ":"))
        return True
    except (OSError, ValueError, TypeError):
        return False


def main() -> int:
    env = dict(os.environ)
    report = empty_report()
    if not context_valid(env):
        report["error"] = "invalid_context"
    else:
        try:
            report = asyncio.run(
                observe(env["HOBEN_USER_GUID"], env.get("HOBEN_DEVICE_GUID") or None)
            )
        except BaseException:
            report["error"] = "client_failure"
    written = write_report(report, env.get("RUNNER_TEMP", ""))
    return 0 if written and report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
