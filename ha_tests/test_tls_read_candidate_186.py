"""#186 real HA owners; synthetic deliveries, no candidate model in runtime."""

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from ha_tests.test_persistent_client import assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from tests.tls_read_candidate_186 import PING, RESPONSE


@pytest.mark.parametrize("split", [1, 7, 49])
async def test_real_ha_decodes_fragmented_response_and_retains_original_freshness(
    hass, entry, peers, split
):
    wire = peers.wire(DEVICE_GUID, [[PING + RESPONSE[:split], RESPONSE[split:] + PING]])
    coordinator = await load(hass, entry)
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
async def test_info_candidate_cannot_refresh_ha_or_credit_concatenated_response(
    hass, entry, peers, code, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [bytes((12, code)) + PING + RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    previous_state = sensor(hass, entry)
    await coordinator.async_refresh()
    coordinator._async_unsub_refresh()
    await peers.backoff.entered.get()
    observation = coordinator.client.session_observation
    assert not coordinator.last_update_success and coordinator.data is previous
    assert coordinator.last_successful_read_at == stamp
    assert sensor(hass, entry) is previous_state  # B7 hold, no new decoded sample.
    assert coordinator.last_snapshot_held
    assert observation.cleaned_generation == 1 and not observation.cleanup_failed
    assert not observation.active and peers.factory.call_count == 1
    assert session_state(hass, entry).state == "reconnecting"
    assert session_state(hass, entry).attributes["last_error_phase"] == "frame_boundary"
    wire.close.assert_awaited_once_with()
    assert [call.args[0][0] for call in wire.write.await_args_list] == [3, 13, 13]
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
