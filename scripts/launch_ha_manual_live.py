"""Fixed entry after the manual gate recheck; never run by DEV or offline CI."""

import json
import os
import re
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ha_manual_live_report import (  # noqa: E402
    not_run,
    validate_live_report,
    validate_proof,
)
from scripts.ha_session_supervisor import supervise_live  # noqa: E402
from scripts.manual_hoben_context import proof as context_proof  # noqa: E402
from scripts.manual_hoben_context import require  # noqa: E402


def provenance(source, candidate):
    selection, p = context_proof(
        source, candidate, plans={"hoben-live": ("hoben-live",)}
    )
    require(selection == "hoben-live")
    for key, name in (
        ("MANUAL_HOBEN_CI", "ci_run_id"),
        ("MANUAL_HOBEN_ENVIRONMENT", "environment_id"),
    ):
        require(re.fullmatch(r"[1-9][0-9]{0,15}", source.get(key, "")))
        p[name] = int(source[key])
    p["claim_sha"] = source.get("MANUAL_HOBEN_CLAIM")
    p["environment_digest"] = source.get("MANUAL_HOBEN_POLICY")
    return validate_proof(p)


def write_report(storage, p, report):
    """Only the existing closed, independently validated public envelope."""
    validate_live_report(report, p)
    data = json.dumps(report, separators=(",", ":"), allow_nan=False).encode()
    folder = storage / "hoben-ha-live-public"
    folder.mkdir(mode=0o700)
    path = folder / "report.json"
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def main():
    """One categorical diagnostic; never echo inputs or caught exceptions."""
    p = storage = None
    phase, category = "provenance", "context_refused"
    started, status, outcome, code = "false", "absent", "NOT_RUN", 1
    try:
        require(len(sys.argv) == 1)
        candidate = ROOT.parent / "candidate"
        # Complete local provenance/image checks BEFORE accessing identity.
        p = provenance(os.environ, candidate)
        storage = Path(os.environ["RUNNER_TEMP"])
        phase, category = "image", "image_refused"
        image = storage / "hoben-ha-runtime.id"
        require(
            image.is_file() and not image.is_symlink() and image.stat().st_size <= 72
        )
        image_id = image.read_text().strip()
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id))
        phase = "identity"
        identity = {
            "user_guid": os.environ.pop("HOBEN_USER_GUID", ""),
            "device_guid": os.environ.pop("HOBEN_DEVICE_GUID", ""),
        }
        for name in ("user_guid", "device_guid"):
            category = (
                "user_input_missing" if name == "user_guid" else "device_input_missing"
            )
            require(identity[name] != "")
        category = "identity_invalid"
        require(
            all(
                type(x) is str and x.isascii() and 0 < len(x) <= 64
                for x in identity.values()
            )
        )
        # Existing C2b requirement: persisted identity, never silently fall back
        # to initial identity/association or manufacture a missing credential.
        require(
            len(identity["device_guid"]) == 32 and set(identity["device_guid"]) != {"0"}
        )
        payload = json.dumps(identity, separators=(",", ":")).encode() + b"\n"
        stopped = False

        def stop(signum, frame):
            nonlocal stopped
            stopped = True

        phase, category = "supervision", "supervisor_failed"
        # An exception here cannot prove whether a worker/connection started.
        started, outcome = "unattested", "FAILURE"
        previous = signal.signal(signal.SIGTERM, stop)
        try:
            report = supervise_live(image_id, p, payload, cancelled=lambda: stopped)
        finally:
            signal.signal(signal.SIGTERM, previous)
        phase, category = "report", "report_refused"
        validate_live_report(report, p)
        started = "true" if report["supervisor"]["started"] else "false"
        write_report(storage, p, report)
        outcome = report["outcome"].replace(" ", "_")
        status, category, code = "valid", "reported", 0
        # Validated FAILURE/NOT RUN must reach independent publication/result.
    except (Exception, KeyboardInterrupt):
        if p is not None and phase in ("image", "identity"):
            try:
                # Only before the supervisor call can absence of start be
                # asserted. Missing/invalid provenance never creates a report.
                write_report(storage, p, not_run(p))
                status = "valid"
            except (Exception, KeyboardInterrupt):
                pass
    print(
        f"HA_LIVE_DIAGNOSTIC phase={phase} category={category} "
        f"started={started} report={status} session={outcome} exit_code={code}",
        file=sys.stderr,
    )
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt):
        raise SystemExit(1) from None
