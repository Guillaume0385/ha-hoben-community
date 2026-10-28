"""Fixed unprivileged campaign worker, receiving identity only through a pipe."""

import asyncio
import json
import os
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from scripts.campaign_runtime_contract import HA_CHOICES, need
    from scripts.ha_campaign_observer import observe
    from scripts.ha_session_live_worker import collect

    need(len(sys.argv) == 2 and sys.argv[1] in HA_CHOICES[:-1])
    need(os.getuid() == 65534 and os.getgid() == 65534)
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    need(int(status["CapEff"], 16) == 0 and status["NoNewPrivs"].strip() == "1")
    need(not os.access("/sys/fs/cgroup/cgroup.procs", os.W_OK))
    with os.fdopen(int(os.environ.pop("HA_IDENTITY_FD")), "rb") as pipe:
        raw = pipe.read(513)
    need(len(raw) <= 512)
    identity = json.loads(raw)
    need(type(identity) is dict and set(identity) == {"user_guid", "device_guid"})
    data = asyncio.run(
        collect(
            identity,
            observer=partial(
                observe,
                scenario=sys.argv[1],
                absolute_end=int(os.environ["HA_DEADLINE_NS"]) / 1e9,
            ),
        )
    )
    encoded = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
    need(len(encoded) <= 8192)
    need(os.write(int(os.environ["HA_EVIDENCE_FD"]), encoded) == len(encoded))
    return 0


if __name__ == "__main__":
    try:
        os._exit(main())
    except BaseException:
        os._exit(1)
