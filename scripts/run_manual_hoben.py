"""Fixed manual scenarios behind the admitted isolated parent. No public modes."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manual_hoben_context import proof, require  # noqa: E402


def arm(name):
    """Parent arms a fixed deadline before ACK; no duration comes from this pipe."""
    token = {"h1h2": b"H", "session-300": b"S", "session-reconnect": b"R"}[name]
    require(os.write(int(os.environ["MANUAL_CONTROL_FD"]), token) == 1)
    require(os.read(int(os.environ["MANUAL_ACK_FD"]), 1) == token)


def save(folder, report, limit):
    from scripts.run_session_300 import write_report

    require(len(json.dumps(report).encode()) <= limit)
    path = Path(os.environ["RUNNER_TEMP"]) / folder
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)
    write_report(path / "report.json", report)


def h1h2(user, device, provenance):
    from scripts import run_experimental_boundary as h1

    private = Path(
        tempfile.mkdtemp(
            prefix="hoben-experimental-private-", dir=os.environ["RUNNER_TEMP"]
        )
    )
    try:
        os.environ["HOBEN_USER_GUID"], os.environ["HOBEN_DEVICE_GUID"] = user, device
        raw, interrupted = h1.collect(private)
        report = h1.safe_report(
            raw,
            interrupted=interrupted,
            provenance=provenance | {"candidate_sha": provenance["merge_sha"]},
        )
        save("hoben-experimental-exports", report, 340 * 1024)
        return report["result"] == "inconclusive"
    finally:
        os.environ.pop("HOBEN_USER_GUID", None)
        os.environ.pop("HOBEN_DEVICE_GUID", None)
        shutil.rmtree(private)


def sessions(
    selection,
    user,
    device,
    provenance,
    *,
    clock=time.monotonic,
    sleep=asyncio.sleep,
    make_lifecycle=None,
):
    from custom_components.hoben.v4_experiment import Session300, SessionReconnect
    from custom_components.hoben.v4_lifecycle import V4Lifecycle
    from custom_components.hoben.v4_no_pong import NoPongAfter120
    from custom_components.hoben.v4_session import V4Session
    from scripts.run_session_300 import observe
    from scripts.session_suite import _observe_reconnect, observe_suite

    def factory(budget, policy):
        if selection == "all" and policy is not None:
            arm("session-reconnect")
        if make_lifecycle is not None:
            return make_lifecycle(budget, policy)
        return V4Lifecycle(
            user_guid=user,
            device_guid=device,
            retry_delays=(1.0, 2.0),
            session_factory=partial(
                V4Session, session_300=budget, no_pong_after_120=policy
            ),
        )

    if selection == "all":
        arm("session-300")
        save(
            "hoben-session-suite-exports",
            asyncio.run(observe_suite(factory, provenance, clock=clock, sleep=sleep)),
            8192,
        )
    elif selection == "session-300":
        arm(selection)
        budget = Session300(clock=clock)
        save(
            "hoben-session-300-exports",
            asyncio.run(
                observe(
                    factory(budget, None), budget, provenance, clock=clock, sleep=sleep
                )
            ),
            4096,
        )
    else:
        arm(selection)
        budget, policy = SessionReconnect(clock=clock), NoPongAfter120(clock=clock)
        save(
            "hoben-session-reconnect-exports",
            asyncio.run(
                _observe_reconnect(
                    factory(budget, policy),
                    budget,
                    policy,
                    provenance,
                    clock=clock,
                    sleep=sleep,
                )
            ),
            8192,
        )


def main():
    try:
        require(len(sys.argv) == 1)
        selection, provenance = proof(os.environ, ROOT)
        require(
            not any(
                os.environ.get(k)
                for k in (
                    "GITHUB_TOKEN",
                    "GH_TOKEN",
                    "ACTIONS_RUNTIME_TOKEN",
                    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                    "ACTIONS_ID_TOKEN_REQUEST_URL",
                    "GITHUB_ENV",
                    "GITHUB_OUTPUT",
                    "GITHUB_STEP_SUMMARY",
                )
            )
        )
        user = os.environ.pop("HOBEN_USER_GUID")
        device = os.environ.pop("HOBEN_DEVICE_GUID", "") or "0" * 32
        if selection in {"h1h2", "all"}:
            arm("h1h2")
            if not h1h2(user, device, provenance):
                return 0  # Valid failure report; remaining scenarios are NOT RUN.
        if selection != "h1h2":
            sessions(selection, user, device, provenance)
        return 0
    except (Exception, KeyboardInterrupt):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
