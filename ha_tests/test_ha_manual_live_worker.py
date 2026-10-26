"""C2b worker bootstraps real isolated HA; all transport/clock inputs synthetic."""

import asyncio
from unittest.mock import Mock

from conftest import DEVICE_GUID, ROTATED_DEVICE_GUID
from homeassistant.config_entries import ConfigEntries

from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts import ha_session_observer
from scripts.ha_session_live_worker import collect


async def test_live_worker_uses_actual_coordinator_and_persists_rotated_identity(
    peers, monkeypatch
):
    wire = peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]] * 6)
    original = ConfigEntries.async_update_entry
    persisted = []

    def update(entries, entry, **kwargs):
        result = original(entries, entry, **kwargs)
        persisted.append(entry.data["device_guid"])
        return result

    monkeypatch.setattr(ConfigEntries, "async_update_entry", update)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", Mock())
    observe = ha_session_observer.observe
    now = 0.0

    async def sleep(delay):
        nonlocal now
        now += delay
        await asyncio.sleep(0)

    async def synthetic(coordinator, **kwargs):
        return await observe(coordinator, clock=lambda: now, sleep=sleep, **kwargs)

    monkeypatch.setattr(ha_session_observer, "observe", synthetic)
    evidence = await collect(
        {"user_guid": "12345678123456781234567812345678", "device_guid": DEVICE_GUID}
    )
    assert persisted and persisted[0] == ROTATED_DEVICE_GUID
    assert evidence["completed"] and evidence["window"]["elapsed_ms"] == 300000
    assert evidence["window"]["clock"] == "synthetic"  # never promoted as live
    assert evidence["cleanup"]["completed"] and wire.write.await_count == 7
    assert_stopped(peers)
