"""Fixed synthetic pipe peer for tests; no socket, HA, transport or identity log."""

import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.campaign_runtime_contract import empty_metrics, stage  # noqa: E402

mode = sys.argv[1]
Path(os.environ["CAMPAIGN_PRIVATE_DIR"], "private-capture").write_text(
    "PRIVATE_PAYLOAD"
)
assert not any(
    k in os.environ
    for k in ("GITHUB_TOKEN", "GITHUB_OUTPUT", "HOBEN_USER_GUID", "HOBEN_DEVICE_GUID")
)
with os.fdopen(int(os.environ["CAMPAIGN_IDENTITY_FD"]), "rb") as stream:
    assert json.loads(stream.read())["device_guid"] == "synthetic"
if mode == "before_ack":
    os._exit(1)
if mode == "resistant":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.write(int(os.environ["CAMPAIGN_READY_FD"]), b"R")
assert os.read(int(os.environ["CAMPAIGN_ACK_FD"]), 1) == b"A"
if mode == "after_ack":
    os._exit(1)
if mode == "resistant":
    while True:
        time.sleep(1)
metrics = empty_metrics()
metrics.update(opens=1, completed=True, cleanup=True)
value = stage(
    "protocol",
    "tls-only",
    started=True,
    metrics=metrics,
    detail={"rx_bytes": 0, "rx_chunks": 0},
    reason="timeout" if mode == "timeout_receipt" else "observed",
)
if mode == "private":
    value["private"] = "PRIVATE_PAYLOAD"
data = json.dumps(value).encode() if mode != "big" else b"x" * 17000
os.write(int(os.environ["CAMPAIGN_REPORT_FD"]), data)
