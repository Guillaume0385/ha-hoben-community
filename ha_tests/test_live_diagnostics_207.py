"""D3 download and refresh through actual HA owners, synthetic TLS only."""

import asyncio
import json

from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import Clock, pump


async def test_diag_download_has_no_io_and_late_reply_never_increments_freshness(
    hass, entry, peers, freezer, monkeypatch, caplog
):
    wire = peers.wire(
        DEVICE_GUID, [[RESPONSE], [b"\x0c\x0a" + RESPONSE, b"\x0a", RESPONSE], []]
    )
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    freezer.tick(60)
    await coordinator.async_refresh()
    coordinator._async_unsub_refresh()
    data, stamp = coordinator.data, coordinator.last_successful_read_at
    clock = Clock(monkeypatch)
    first = await async_get_config_entry_diagnostics(hass, entry)
    calls, tasks = wire.mock_calls.copy(), asyncio.all_tasks()
    for _ in range(3):
        assert await async_get_config_entry_diagnostics(hass, entry) == first
    assert wire.mock_calls == calls and asyncio.all_tasks() == tasks
    r = first["session"]
    assert r["tls_generation"] == 1 and r["unsupported_deliveries"] == 1
    assert r["pings"] == r["pongs"] == 1
    assert r["v4_requests"] == r["v4_responses_correlated"] == 2
    assert r["responses_after_info_candidate"] == 1
    assert len(json.dumps(r)) < 2048
    task = asyncio.create_task(coordinator.async_refresh())
    try:
        await pump()
        await clock.advance(30.01)
        await task
        wire.queue.put_nowait(RESPONSE)
        await pump()
        last = await async_get_config_entry_diagnostics(hass, entry)
        r = last["session"]
        assert r["v4_requests"] == 3 and r["v4_responses_correlated"] == 2
        assert r["v4_responses_uncredited"] == 1 and r["acquisition_uncertain"]
        assert r["responses_after_info_candidate"] == 1
        assert not r["eof_received"] and not r["cleanup_succeeded"]
        assert last["coordinator"]["snapshot_held"]
        assert not last["coordinator"]["last_update_success"]
        assert coordinator.data is data and coordinator.last_successful_read_at == stamp
        assert_private_values_absent(json.dumps(last) + caplog.text)
        assert peers.factory.call_count == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
    assert coordinator.client.session_diagnostics["cleanup_succeeded"]
