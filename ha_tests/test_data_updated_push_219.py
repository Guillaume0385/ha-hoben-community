"""Owner-authorized #219 push mode, real HA owners and synthetic bytes only."""

import asyncio
import logging
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.modbus import encode_mbap
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_state import decode_v4_snapshot
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_drop_219 import INVALID
from tests.test_data_updated_silence import Clock, pump


@pytest.fixture
def push_peers(peers, monkeypatch):
    # Production entry constructor, unlike explicit legacy polling regressions.
    monkeypatch.setattr("custom_components.hoben.HobenClient", HobenClient)
    return peers


def updated(words):
    return b"\x1bTEST" + encode_mbap(
        65535, 1, b"\x04\x28" + b"".join(w.to_bytes(2, "big") for w in words)
    )


async def test_twenty_updates_publish_atomic_existing_decoded_entities(
    hass, entry, push_peers, caplog
):
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        for index in range(20):
            words = (
                0x0201,
                0x0FFF,
                15,
                90,
                2,
                0,
                0x3205,
                210 + index,
                190,
                0xFFFF,
                0,
                0x20,
                1,
                2,
                3,
                0xFFF6,
                0x0FFF,
                1234,
                99,
                200,
            )
            before = listener.call_count
            wire.queue.put_nowait(updated(words))
            await pump()
            assert coordinator.data.raw.registers == words
            assert coordinator.data.state == decode_v4_snapshot(coordinator.data.raw)
            assert sensor(hass, entry).state == str((210 + index) / 10)
            assert listener.call_count == before + 1
        assert coordinator.update_interval is None
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
        assert push_peers.factory.call_count == 1
        assert_private_values_absent(caplog.text)
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


@pytest.mark.parametrize("value", [17, 222])
async def test_no_periodic_or_explicit_duplicate_initial_read_and_staleness(
    hass, entry, push_peers, monkeypatch, value
):
    from custom_components.hoben import coordinator as module

    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    clock = Clock(monkeypatch)
    monkeypatch.setattr(module, "monotonic", lambda: clock.now)
    coordinator = await load(hass, entry)
    try:
        stamp = coordinator.last_successful_read_at
        assert coordinator.update_interval is None
        await coordinator.async_refresh()
        assert coordinator.last_successful_read_at == stamp
        await clock.advance(299)
        assert coordinator.snapshot_available
        await clock.advance(1)
        assert not coordinator.snapshot_available
        assert sensor(hass, entry).state == "unavailable"
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
        wire.queue.put_nowait(updated((value,) * 20))
        await pump()
        assert coordinator.snapshot_available and sensor(hass, entry).state == str(
            value / 10
        )
        assert push_peers.factory.call_count == 1
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


async def test_initial_reply_keeps_notification_and_each_generation_reads_once(
    hass, entry, push_peers
):
    words = (234,) * 20
    first = push_peers.wire(
        DEVICE_GUID, [[b"\x0c\x0a" + RESPONSE, updated(words), RESPONSE]]
    )
    second = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    life = push_peers.lifecycles[0]
    try:
        assert coordinator.data.raw.registers == words
        assert life.session_diagnostics["info_candidate_deliveries"] == 1
        old = life._session
        callback, item = old._data_callback, old._latest_data_updated
        first.queue.put_nowait(TransportEOF())
        await push_peers.backoff.entered.get()
        assert old.cleanup_succeeded
        push_peers.backoff.release.put_nowait(None)
        await life.wait_connected()
        await pump()
        assert [c.args[0][0] for c in second.write.await_args_list] == [3, 13]
        assert coordinator.data.raw.registers == (17,) * 20
        assert life.witness.verified_read_generation == 2
        previous = coordinator.data
        callback(item)
        await pump()
        assert coordinator.data is previous
        await coordinator.async_refresh()
        assert [c.args[0][0] for c in second.write.await_args_list] == [3, 13]
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)


async def test_parent_debug_does_not_enable_private_values_and_unload_revokes_callback(
    hass, entry, push_peers, caplog
):
    push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    client = coordinator.client
    caplog.set_level(logging.DEBUG, logger="custom_components.hoben")
    caplog.set_level(
        logging.NOTSET, logger="custom_components.hoben.shadow_data_updated"
    )
    wire = push_peers.wires[0]
    wire.queue.put_nowait(updated((321,) * 20))
    await pump()
    assert coordinator.data.raw.registers == (321,) * 20
    assert not any(hasattr(r, "hoben_data_updated_state") for r in caplog.records)
    session = client._lifecycle._session
    callback, item = session._data_callback, session._latest_data_updated
    previous = coordinator.data
    assert await hass.config_entries.async_unload(entry.entry_id)
    callback(item)
    assert coordinator.data is previous and not coordinator.snapshot_available
    assert not client._data_listeners and coordinator._unsub_push_expiry is None
    assert_stopped(push_peers)


async def test_initial_timeout_retries_three_times_then_initializes_fresh_generation(
    hass, entry, push_peers, monkeypatch
):
    clock = Clock(monkeypatch)
    first = push_peers.wire(DEVICE_GUID, [[], [], []])
    second = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    try:
        for _ in range(20):
            await pump()
            if first.write.await_count == 2:
                break
        assert first.write.await_count == 2
        life = push_peers.lifecycles[0]
        await clock.advance(30)
        assert not setup.done() and life._session._failed_reads == 1
        first.queue.put_nowait(updated((345,) * 20))
        await pump()
        assert life.witness.verified_read_generation is None
        for _ in range(2):
            await clock.advance(60)
            await clock.advance(30)
        await push_peers.backoff.entered.get()
        first.close.assert_awaited_once()
        push_peers.backoff.release.put_nowait(None)
        assert await setup
        coordinator = entry.runtime_data.coordinator
        assert coordinator.data.raw.registers == (17,) * 20
        assert coordinator.update_interval is None
        assert [c.args[0][0] for c in first.write.await_args_list] == [3, 13, 13, 13]
        assert [c.args[0][0] for c in second.write.await_args_list] == [3, 13]
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)
    finally:
        if not setup.done():
            setup.cancel()
        await asyncio.gather(setup, return_exceptions=True)


async def test_invalids_then_valid_same_rx_and_debug_explicit_opt_in(
    hass, entry, push_peers, caplog
):
    logger = "custom_components.hoben.shadow_data_updated"
    wire = push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    try:
        previous = coordinator.data
        for delivery in INVALID:
            wire.queue.put_nowait(delivery)
        await pump()
        assert coordinator.data is previous
        words = tuple(range(20))
        caplog.set_level(logging.DEBUG, logger=logger)
        wire.queue.put_nowait(updated(words))
        await pump()
        assert coordinator.data.raw.registers == words
        events = [
            r.hoben_data_updated_state
            for r in caplog.records
            if hasattr(r, "hoben_data_updated_state")
        ]
        assert len(events) == 1
        event = events[0]
        assert [v["register"] for v in event["registers"]] == list(range(1024, 1044))
        assert [v["raw_value"] for v in event["registers"]] == list(words)
        assert event["decoded"]["ambient_temperature"] == 0.7
        assert event["mapping"] == "owner_validated"
        assert "TEST" not in caplog.text
        assert_private_values_absent(caplog.text)
        caplog.set_level(logging.INFO, logger=logger)
        wire.queue.put_nowait(updated((333,) * 20))
        await pump()
        assert coordinator.data.raw.registers == (333,) * 20
        assert (
            len([r for r in caplog.records if hasattr(r, "hoben_data_updated_state")])
            == 1
        )
        wire.close.assert_not_awaited()
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)
