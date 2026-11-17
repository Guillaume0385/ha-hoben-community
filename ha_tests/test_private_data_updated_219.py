"""Local-only synthetic journal never publishes an HA value or support payload."""

import asyncio
import json
import logging
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent
from homeassistant.setup import async_setup_component

from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import pump
from tests.test_private_data_updated_219 import FLAG, fields, notification
from tests.test_private_data_updated_219 import (
    private_fifo as private_fifo,  # noqa: F401
)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("ha_debug", [False, True])
async def test_twenty_private_deliveries_leave_ha_and_exports_untouched(
    hass, entry, peers, private_fifo, monkeypatch, caplog, enabled, ha_debug
):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(
        logging.DEBUG if ha_debug else logging.NOTSET,
        logger="custom_components.hoben.shadow_data_updated",
    )
    if not enabled:
        monkeypatch.delenv(FLAG)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    timer = coordinator._unsub_refresh
    life = peers.lifecycles[0]
    session, snapshot = life._session, life._session._snapshot
    states = {s.entity_id: s for s in hass.states.async_all()}
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        for delivery in range(20):
            words = (0, 65535, *range(49123 + delivery, 49141 + delivery))
            wire.queue.put_nowait(notification(words))
            await pump()
            lines = private_fifo.read()
            assert len(lines) == (20 if enabled else 0)
            if enabled:
                rows = [fields(line) for line in lines]
                assert [int(row["raw_value"]) for row in rows] == list(words)
                assert [int(row["register_candidate"]) for row in rows] == list(
                    range(1024, 1044)
                )
        assert coordinator.data is previous
        assert coordinator.last_successful_read_at == stamp
        assert coordinator._unsub_refresh is timer
        assert session._snapshot is snapshot
        listener.assert_not_called()
        current = {s.entity_id: s for s in hass.states.async_all()}
        assert current.keys() == states.keys()
        assert all(current[key] is value for key, value in states.items())
        assert life.witness.verified_read_sequence == 1
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
        wire.close.assert_not_awaited()
        support = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
        assert_private_values_absent(caplog.text + support)
        for forbidden in ("raw_value", "register_candidate", "49123", "SECR"):
            assert forbidden not in support
            if not ha_debug or forbidden == "SECR":
                assert forbidden not in caplog.text
        records = [
            r
            for r in caplog.records
            if r.name == "custom_components.hoben.shadow_data_updated"
        ]
        assert len(records) == (20 if ha_debug else 0)
        assert all(len(r.hoben_shadow["candidate_registers"]) == 20 for r in records)
        assert all(r.levelno == logging.DEBUG for r in records)
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
    # No queued observation or writer outlives unload.
    wire.queue.put_nowait(notification())
    await pump()
    assert private_fifo.read() == []
    assert len(
        [
            r
            for r in caplog.records
            if r.name == "custom_components.hoben.shadow_data_updated"
        ]
    ) == len(records)


async def test_ha_logger_service_enables_and_disables_without_fifo_or_env(
    hass, entry, peers, caplog, monkeypatch
):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv("HOBEN_PRIVATE_DATAUPDATED_FIFO", raising=False)
    logger = "custom_components.hoben.shadow_data_updated"
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.INFO, logger=logger)
    assert await async_setup_component(hass, "logger", {})
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    await load(hass, entry)
    received = asyncio.Event()
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)
            hass.loop.call_soon_threadsafe(received.set)

    handler = Capture()
    logging.getLogger(logger).addHandler(handler)
    try:
        await hass.services.async_call(
            "logger", "set_level", {logger: "debug"}, blocking=True
        )
        wire.queue.put_nowait(notification())
        await asyncio.wait_for(received.wait(), timeout=2)
        assert len(records) == 1
        assert len(records[0].hoben_shadow["candidate_registers"]) == 20
        assert len(records[0].getMessage().encode("utf8")) <= 4096
        await hass.services.async_call(
            "logger", "set_level", {logger: "info"}, blocking=True
        )
        wire.queue.put_nowait(notification())
        async with asyncio.timeout(2):
            while peers.lifecycles[0]._session._data_updated_deliveries != 2:
                await asyncio.sleep(0)
        assert len(records) == 1
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
    finally:
        logging.getLogger(logger).removeHandler(handler)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
