"""Private, fixed C2b worker. No CLI options, Actions token or public logs."""

import asyncio
import json
import os
import signal
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def collect(identity, *, observer=None):
    from homeassistant.config_entries import ConfigEntries, ConfigEntry
    from homeassistant.core import HomeAssistant

    from custom_components.hoben.client import HobenClient
    from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
    from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID
    from scripts.ha_live_proof import empty_evidence
    from scripts.ha_session_observer import observe

    if identity["device_guid"] == INITIAL_DEVICE_GUID:
        raise ValueError("persisted identity required")
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    # /tmp is a private bounded tmpfs in the same memory cgroup, never a host
    # config directory. A bare HA instance avoids extra entity polling/setup.
    with tempfile.TemporaryDirectory() as folder:
        hass = HomeAssistant(folder)
        hass.config_entries = ConfigEntries(hass, {})
        entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain="hoben",
            data=identity,
            options={},
            source="user",
            title="Hoben validation",
            unique_id=None,
            discovery_keys={},
            subentries_data=[],
        )
        # HA 2026.9.4's isolated registry bootstrap: no async_add/automatic first
        # refresh. The real async_update_entry can persist a rotated identity.
        # This private HA API is pinned and tested; no mock or replacement of
        # the client/coordinator/persistence path occurs in the live worker.
        hass.config_entries._entries[entry.entry_id] = entry
        client = HobenClient(identity["user_guid"], identity["device_guid"])
        evidence = empty_evidence()
        try:
            coordinator = HobenDataUpdateCoordinator(hass, entry, client)
            try:
                await (observe if observer is None else observer)(
                    coordinator, evidence=evidence
                )  # live callers always use the native clock
            except asyncio.CancelledError:
                pass
            return evidence
        finally:
            await client.async_close()
            # This validation instance is deliberately never started as a
            # household HA. Force its normal shutdown/final-write hooks so
            # identity persistence timers cannot outlive the private tmpfs.
            await hass.async_stop(force=True)


def main():
    if len(sys.argv) != 1 or os.getuid() != 65534 or os.getgid() != 65534:
        return 1
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if int(status["CapEff"], 16) != 0 or status["NoNewPrivs"].strip() != "1":
        return 1
    if os.access("/sys/fs/cgroup/cgroup.procs", os.W_OK):
        return 1
    descriptor = int(os.environ.pop("HA_IDENTITY_FD"))
    with os.fdopen(descriptor, "rb") as pipe:
        raw = pipe.read(513)
    if len(raw) > 512:
        return 1
    identity = json.loads(raw)
    if type(identity) is not dict or set(identity) != {"user_guid", "device_guid"}:
        return 1
    evidence = asyncio.run(collect(identity))
    data = json.dumps(evidence, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > 8192:
        return 1
    os.write(int(os.environ["HA_EVIDENCE_FD"]), data)
    return 0


if __name__ == "__main__":
    try:
        os._exit(main())
    except BaseException:
        os._exit(1)  # no arbitrary exception/identity can reach stdout/stderr
