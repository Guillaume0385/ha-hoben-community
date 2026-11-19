"""Real HA owners: drop invalid candidates, retain polling pending mapping proof."""

import logging
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben import v4_session
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_delivery_219 import reports
from tests.test_data_updated_drop_219 import INVALID
from tests.test_data_updated_ignore import notification
from tests.test_data_updated_silence import pump


@pytest.mark.parametrize("parser_error", [False, True])
async def test_twenty_drops_then_valid_keep_tls_ha_snapshot_and_existing_poll(
    hass, entry, peers, monkeypatch, caplog, parser_error
):
    caplog.set_level(logging.DEBUG, logger="custom_components.hoben.frame_diagnostic")
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    previous_sensor, timer = sensor(hass, entry), coordinator._unsub_refresh
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    life = peers.lifecycles[0]
    session, original = life._session, v4_session.parse_data_updated
    rx = session._rx_task

    def broken(data):
        raise RuntimeError("SYNTHETIC_PRIVATE_PARSER_PAYLOAD")

    try:
        if parser_error:
            monkeypatch.setattr(v4_session, "parse_data_updated", broken)
        for index in range(20):
            wire.queue.put_nowait(INVALID[index % len(INVALID)])
        await pump()
        assert not life.data_updated_recovering and not session.acquisition_uncertain
        assert session._rx_task is rx and not rx.done()
        assert session._data_updated.task is None and session._failed_reads == 0
        assert coordinator.data is previous and coordinator.last_update_success
        assert coordinator.last_successful_read_at == stamp
        assert sensor(hass, entry) is previous_sensor
        assert coordinator._unsub_refresh is timer and timer is not None
        listener.assert_not_called()
        assert len(reports(caplog)) == 20
        monkeypatch.setattr(v4_session, "parse_data_updated", original)
        wire.queue.put_nowait(b"\x0a")
        wire.queue.put_nowait(notification())
        await pump()
        assert reports(caplog)[-1]["status"] == "parsed"
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        listener.assert_not_called()  # Mapping still unproven; no fake HA update.
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 11]
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        wire.close.assert_not_awaited()
        await coordinator.async_refresh()  # Existing actual V4 source remains usable.
        assert life.witness.verified_read_sequence == 2
        assert coordinator.last_successful_read_at > stamp
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 11, 13]
        assert_private_values_absent(caplog.text)
        assert "SYNTHETIC_PRIVATE_PARSER_PAYLOAD" not in caplog.text
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
