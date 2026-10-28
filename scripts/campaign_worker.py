"""Isolated host worker. No Actions token/command files or private stdout/stderr."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from scripts.campaign_runtime_contract import need, plan, stage, validate_stage

    need(len(sys.argv) == 3)
    campaign, scenario = sys.argv[1:]
    need(plan(campaign, scenario) == (scenario,))
    with os.fdopen(int(os.environ["CAMPAIGN_IDENTITY_FD"]), "rb") as stream:
        payload = stream.read(513)
    need(len(payload) <= 512)
    identity = json.loads(payload)
    need(type(identity) is dict and set(identity) == {"user_guid", "device_guid"})
    # ACK occurs only after the parent has armed the exact absolute deadline.
    need(os.write(int(os.environ["CAMPAIGN_READY_FD"]), b"R") == 1)
    need(os.read(int(os.environ["CAMPAIGN_ACK_FD"]), 1) == b"A")
    if campaign == "protocol":
        from scripts.protocol_campaign_collect import collect, h1h2

        async def run():
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
            return await (
                h1h2(identity, directory=os.environ["CAMPAIGN_PRIVATE_DIR"])
                if scenario == "h1h2"
                else collect(scenario, identity)
            )

        metrics, detail = asyncio.run(run())
    else:
        from scripts.ha_campaign_evidence import project
        from scripts.ha_session_supervisor import supervise_campaign

        cancelled = False

        def stop(*_):
            nonlocal cancelled
            cancelled = True

        signal.signal(signal.SIGTERM, stop)
        detail = supervise_campaign(
            os.environ["CAMPAIGN_IMAGE"],
            scenario,
            payload + b"\n",
            cancelled=lambda: cancelled,
            _absolute_deadline=int(os.environ["CAMPAIGN_DEADLINE_NS"]) / 1e9,
        )
        metrics = project(scenario, detail)
    # The external parent owns elapsed time and overrides it only after reaping.
    result = stage(
        campaign,
        scenario,
        started=True,
        metrics=metrics,
        detail=detail,
        reason="observed",
    )
    result["elapsed_ms"] = max(
        metrics["useful_ms"],
        detail["supervisor"]["elapsed_ms"] if campaign == "ha" else 0,
    )
    if campaign == "ha" and not detail["supervisor"]["started"]:
        failure = detail["supervisor"]["reason"]
        result = stage(
            campaign,
            scenario,
            reason=failure
            if failure in {"memory", "processes", "timeout", "cancelled"}
            else "supervisor_refused",
        )
    validate_stage(result, campaign)
    encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode()
    need(len(encoded) <= 16384)
    need(os.write(int(os.environ["CAMPAIGN_REPORT_FD"]), encoded) == len(encoded))
    return 0


if __name__ == "__main__":
    try:
        os._exit(main())
    except BaseException:
        os._exit(1)
