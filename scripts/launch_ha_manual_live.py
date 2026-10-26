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


def main():
    require(len(sys.argv) == 1)
    candidate = ROOT.parent / "candidate"
    # Complete all local provenance/image checks BEFORE accessing identity.
    p = provenance(os.environ, candidate)
    storage = Path(os.environ["RUNNER_TEMP"])
    image = storage / "hoben-ha-runtime.id"
    require(image.is_file() and not image.is_symlink() and image.stat().st_size <= 72)
    image_id = image.read_text().strip()
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id))
    identity = {
        "user_guid": os.environ.pop("HOBEN_USER_GUID"),
        "device_guid": os.environ.pop("HOBEN_DEVICE_GUID"),
    }
    require(
        all(
            type(x) is str and x.isascii() and 0 < len(x) <= 64
            for x in identity.values()
        )
    )
    require(
        len(identity["device_guid"]) == 32 and set(identity["device_guid"]) != {"0"}
    )
    payload = json.dumps(identity, separators=(",", ":")).encode() + b"\n"
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        report = supervise_live(image_id, p, payload, cancelled=lambda: stopped)
    finally:
        signal.signal(signal.SIGTERM, previous)
    validate_live_report(report, p)
    data = json.dumps(report, separators=(",", ":"), allow_nan=False).encode()
    folder = storage / "hoben-ha-live-public"
    folder.mkdir(mode=0o700)
    path = folder / "report.json"
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)
    return 0  # a validated FAILURE/NOT RUN also needs an explicit public result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt):
        raise SystemExit(1) from None
