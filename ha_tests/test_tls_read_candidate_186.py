"""#186 real HA owners; synthetic deliveries, no candidate model in runtime."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from ha_tests.test_persistent_client import assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import pump
from tests.tls_read_candidate_186 import PING, RESPONSE


@pytest.mark.parametrize("split", [1, 7, 49])
async def test_real_ha_decodes_fragmented_response_and_retains_original_freshness(
    hass, entry, peers, split
):
    wire = peers.wire(DEVICE_GUID, [[PING + RESPONSE[:split], RESPONSE[split:] + PING]])
    coordinator = await load(hass, entry)
    assert peers.lifecycles[0]._session._info_delivery_drop is None
    coordinator._async_unsub_refresh()
    observation = coordinator.client.session_observation
    assert coordinator.last_update_success and observation.read_sequence == 1
    assert observation.generation == observation.read_generation == 1
    assert sensor(hass, entry).state != "unavailable"
    assert coordinator.last_successful_read_at is not None
    assert not coordinator.last_snapshot_held
    assert peers.factory.call_count == 1 and wire.close.await_count == 0
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("code", [0, 2, 4, 7, 255])
async def test_info_does_not_credit_concatenated_response_before_fresh_reply(
    hass, entry, peers, code, caplog, freezer
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [bytes((12, code)) + PING + RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    session = peers.lifecycles[0]._session
    assert session._info_delivery_drop is None
    assert session._discard_unsupported_deliveries
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    previous_state = sensor(hass, entry)
    freezer.tick(10)
    refresh = asyncio.create_task(coordinator.async_refresh())
    try:
        await pump()
        assert not refresh.done() and session.verified_read_sequence == 1
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        assert sensor(hass, entry) is previous_state
        assert session_state(hass, entry).state == "connected"
        wire.close.assert_not_awaited()
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        wire.queue.put_nowait(RESPONSE)
        await refresh
        coordinator._async_unsub_refresh()
        assert coordinator.last_update_success and session.verified_read_sequence == 2
        assert coordinator.last_successful_read_at > stamp
        assert peers.lifecycles[0]._session is session
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 13]
        assert_private_values_absent(caplog.text)
    finally:
        refresh.cancel()
        await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_207_ha_discards_unknown_delivery_then_decodes_on_same_rx(
    hass, entry, peers
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    session = peers.lifecycles[0]._session
    rx = session._rx_task
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    try:
        wire.queue.put_nowait(b"\x0c" + PING + RESPONSE)
        wire.queue.put_nowait(PING)
        await pump()
        wire.close.assert_not_awaited()
        assert session._rx_task is rx and not rx.done()
        assert peers.factory.call_count == 1
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        assert session.verified_read_sequence == 1
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 11]
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert session.verified_read_sequence == 2 and coordinator.last_update_success
        assert coordinator.data is not previous
        assert peers.lifecycles[0]._session is session and session._rx_task is rx
        wire.close.assert_not_awaited()
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
