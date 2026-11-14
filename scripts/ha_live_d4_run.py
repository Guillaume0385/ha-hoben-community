"""Protected #207 HA observer entrypoint. Never called from CI or simulations.

This process is entered only by the existing manual HA workflow AFTER GitHub
admission, immutable claim proof, environment approval and authenticated recheck.
It runs the real HobenClient and Home Assistant coordinator, without exporting
private values, exceptions, GUIDs, frame bytes or Actions command paths.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _context(source):
    sha = source.get("GITHUB_SHA", "")
    run = source.get("GITHUB_RUN_ID", "")
    attempt = source.get("GITHUB_RUN_ATTEMPT", "")
    target = source.get("RUNNER_TEMP", "")
    if (
        source.get("GITHUB_REPOSITORY") != "Guillaume0385/ha-hoben-community"
        or source.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or source.get("GITHUB_REF") != "refs/heads/experimental"
        or source.get("GITHUB_ACTOR") != "Guillaume0385"
        or source.get("GITHUB_TRIGGERING_ACTOR") != "Guillaume0385"
        or not re.fullmatch("[a-f0-9]{40}", sha)
        or not re.fullmatch("[1-9][0-9]{0,14}", run)
        or attempt != "1"
        or not Path(target).is_dir()
    ):
        raise ValueError("ha_d4_context_refused")
    return sha, int(run), int(attempt), Path(target)


def _project(raw, sha, run_id, attempt):
    """Allowlist every scalar; an unknown or synthetic result cannot be exported."""
    fields = {
        "schema",
        "scenario",
        "execution",
        "admission",
        "live_ready",
        "secrets_allowed",
        "boundary_proven",
        "observation",
        "elapsed_ms",
        "drop_at_ms",
        "correlated_at_ms",
        "tls_generation",
        "unknown_drops",
        "info_candidates",
        "correlated_after_drop",
        "pings",
        "pongs",
        "cleanup_attested",
    }
    if type(raw) is not dict or set(raw) != fields:
        raise ValueError("ha_d4_report_refused")
    if (
        raw["schema"] != 1
        or raw["scenario"] != "hoben-live"
        or raw["execution"] != "component_only"
        or raw["admission"] != "NOT RUN"
        or raw["live_ready"] is not False
        or raw["secrets_allowed"] is not False
        or raw["boundary_proven"] is not False
        or raw["observation"] not in {"SUCCESS", "INCONCLUSIVE", "FAILED"}
        or type(raw["cleanup_attested"]) is not bool
    ):
        raise ValueError("ha_d4_report_refused")
    numeric = (
        "elapsed_ms",
        "drop_at_ms",
        "correlated_at_ms",
        "unknown_drops",
        "info_candidates",
        "correlated_after_drop",
        "pings",
        "pongs",
    )
    if any(
        type(raw[key]) is not int or not -1 <= raw[key] <= 900000 for key in numeric
    ):
        raise ValueError("ha_d4_report_refused")
    if raw["tls_generation"] is not None and (
        type(raw["tls_generation"]) is not int
        or not 1 <= raw["tls_generation"] <= 2147483647
    ):
        raise ValueError("ha_d4_report_refused")
    if raw["observation"] == "SUCCESS" and (
        not raw["cleanup_attested"]
        or raw["correlated_at_ms"] < 0
        or raw["drop_at_ms"] < 0
        or raw["elapsed_ms"] - raw["correlated_at_ms"] < 300000
    ):
        raise ValueError("ha_d4_report_refused")
    return {
        "schema": 1,
        "scenario": "hoben-live",
        "sha": sha,
        "run_id": run_id,
        "attempt": attempt,
        **{
            k: raw[k]
            for k in (
                "observation",
                "elapsed_ms",
                "drop_at_ms",
                "correlated_at_ms",
                "tls_generation",
                "unknown_drops",
                "info_candidates",
                "correlated_after_drop",
                "pings",
                "pongs",
                "cleanup_attested",
                "boundary_proven",
            )
        },
    }


async def _collect(identity):
    from scripts.ha_live_d4_observer import observe
    from scripts.ha_session_live_worker import collect

    result = None

    async def recorded(coordinator, *, evidence):
        nonlocal result
        result = await observe(coordinator)
        return evidence

    async with asyncio.timeout(930):
        await collect(identity, observer=recorded, allow_initial_identity=True)
    if result is None:
        raise ValueError("ha_d4_observation_missing")
    return result


def main():
    try:
        source = dict(os.environ)
        sha, run_id, attempt, root = _context(source)
        from custom_components.hoben.myhoben import (
            INITIAL_DEVICE_GUID,
            normalize_user_guid,
        )

        user = normalize_user_guid(source.pop("HOBEN_USER_GUID", ""))
        # Remove the credential and all GitHub/Actions/OIDC metadata from the
        # HA client process, not merely from the child helper's parameters.
        os.environ.clear()
        os.environ.update({"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"})
        identity = {"user_guid": user, "device_guid": INITIAL_DEVICE_GUID}
        raw = asyncio.run(_collect(identity))
        report = _project(raw, sha, run_id, attempt)
        folder = root / "hoben-d4-public"
        folder.mkdir(mode=0o700)
        file = folder / "report.json"
        encoded = json.dumps(report, separators=(",", ":"), allow_nan=False).encode(
            "ascii"
        )
        if len(encoded) > 4096:
            raise ValueError("ha_d4_report_refused")
        fd = os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
        return 0
    except BaseException:
        # Never propagate a traceback, home value, identity or arbitrary error.
        os.write(2, b"::error::ha_live_d4_capture_refused\n")
        return 1


if __name__ == "__main__":
    os._exit(main())
