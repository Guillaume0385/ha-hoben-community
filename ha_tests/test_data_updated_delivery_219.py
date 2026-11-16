"""#219-A over the real HA coordinator/client/session, synthetic transport only."""

import logging
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_delivery_219 import reports
from tests.test_data_updated_parser_219 import candidate
from tests.test_data_updated_silence import pump


@pytest.mark.parametrize(
    "delivery,status",
    [
        (candidate(), "parsed"),
        (candidate(b"\x06\x12\x34\xbe\xef"), "unsupported"),
        (candidate()[:5], "incomplete"),
        (candidate() + b"\x0a" + RESPONSE, "ambiguous"),
        (candidate()[:7] + b"\xff\xff" + candidate()[9:], "malformed"),
    ],
)
async def test_notification_preserves_ha_snapshot_freshness_and_polling(
    hass, entry, peers, caplog, delivery, status
):
    caplog.set_level(logging.DEBUG, logger="custom_components.hoben.frame_diagnostic")
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    previous = coordinator.data
    stamp = coordinator.last_successful_read_at
    previous_sensor = sensor(hass, entry)
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    life = peers.lifecycles[0]
    rx = life._session._rx_task
    try:
        wire.queue.put_nowait(delivery)
        await pump()
        (event,) = reports(caplog)
        assert event["status"] == status and event["delivery_bytes"] == len(delivery)
        assert coordinator.data is previous and coordinator.last_update_success
        assert coordinator.last_successful_read_at == stamp
        assert sensor(hass, entry) is previous_sensor
        listener.assert_not_called()
        assert life.witness.verified_read_sequence == 1
        assert life._session._rx_task is rx and not rx.done()
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
        wire.close.assert_not_awaited()
        assert_private_values_absent(caplog.text)
        assert "SECR" not in caplog.text and "48879" not in caplog.text
        if status in {"parsed", "unsupported"}:
            # Reception adds no listener/poller: the existing refresh still
            # performs its real V4 read on the same session.
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert life.witness.verified_read_sequence == 2
            assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13, 13]
            assert coordinator.last_update_success
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
