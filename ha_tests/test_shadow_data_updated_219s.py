"""#219-S: twenty real RX deliveries, synthetic transport, no HA publication."""

import logging
from unittest.mock import Mock

from conftest import DEVICE_GUID, assert_private_values_absent

from ha_tests.test_data_updated_ignore import notification
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import pump

LOGGER = "custom_components.hoben.shadow_data_updated"


async def test_twenty_parsed_deliveries_report_unproven_without_changing_ha(
    hass, entry, peers, caplog
):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    life = peers.lifecycles[0]
    session, snapshot = life._session, life._session._snapshot
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        for _ in range(20):
            wire.queue.put_nowait(notification())
            await pump()
        events = [
            r.hoben_shadow
            for r in caplog.records
            if hasattr(r, "hoben_shadow")
        ]
        assert len(events) == 20, "one shadow decision per parsed delivery is missing"
        assert all(e["event"] == "shadow_mapping_unproven" for e in events)
        assert all(e["proposals"] == 0 and e["simulated"] for e in events)
        assert [e["index"] for e in events] == list(range(1, 21))
        assert coordinator.data is previous
        assert coordinator.last_successful_read_at == stamp
        assert session._snapshot is snapshot
        listener.assert_not_called()
        assert life.witness.verified_read_sequence == 1
        assert peers.factory.call_count == 1 and not peers.backoff.delays
        assert [c.args[0][0] for c in wire.write.await_args_list] == [3, 13]
        wire.close.assert_not_awaited()
        assert_private_values_absent(caplog.text)
        assert "candidate_value=" not in caplog.text
        assert "actual_state=" not in caplog.text
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
