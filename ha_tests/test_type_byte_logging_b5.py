"""Actual HA path, shared framer and unchanged B4 owner, synthetic TLS only."""

import json
import logging

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.safe_reports import safe_error_report
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import pump
from tests.test_frame_logging import LOGGER


@pytest.mark.parametrize("head", [0xFE, 0x2A])
async def test_ha_warning_is_text_only_and_keeps_b4_recovery(
    hass, entry, peers, head, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    wire.queue.put_nowait(bytes([head]) + b"PRIVATE_PAYLOAD")
    try:
        assert await peers.backoff.entered.get() == 60
        await coordinator.async_refresh()
        assert not coordinator.last_update_success and coordinator.data is previous
        assert coordinator.last_successful_read_at == stamp
        (record,) = [
            r
            for r in caplog.records
            if r.name == LOGGER
            and r.levelno == logging.WARNING
            and hasattr(r, "hoben_frame")
        ]
        assert f"message_type_byte=0x{head:02X}" in record.getMessage()
        assert "message_type_byte" not in record.hoben_frame
        assert "message_type_byte" not in json.dumps(
            safe_error_report(coordinator.last_exception)
        )
        state = session_state(hass, entry)
        assert state.state == "reconnecting"
        assert state.attributes["last_error_category"] == "malformed_response"
        assert state.attributes["last_error_phase"] == "frame_boundary"
        peers.backoff.release.put_nowait(None)
        await peers.lifecycles[0].wait_connected()
        await coordinator.async_refresh()
        await pump()
        assert coordinator.last_update_success
        assert coordinator.client.session_observation.read_generation == 2
        assert len(peers.lifecycles) == 1
        assert_private_values_absent(caplog.text)
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
