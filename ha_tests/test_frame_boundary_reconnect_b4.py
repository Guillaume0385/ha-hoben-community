"""B4: one real HA supervisor, three proven wire rejections, no live sockets."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

from conftest import DEVICE_GUID, PRIVATE_TEXT, assert_private_values_absent

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.client import HobenClient
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import pump
from tests.test_frame_logging import records


async def test_three_classified_boundaries_reconnect_after_cleanup_and_60_seconds(
    hass, entry, peers, freezer, monkeypatch, caplog
):
    sleep = AsyncMock(side_effect=asyncio.sleep)

    def owner(**options):
        options["sleep"] = sleep
        result = V4Lifecycle(**options)
        peers.lifecycles.append(result)
        return result

    monkeypatch.setattr(v4_lifecycle, "V4Lifecycle", owner)
    wires = [
        peers.wire(DEVICE_GUID, [[RESPONSE[:10] + bytes((0, n)) * 20]])
        for n in range(17, 21)
    ]
    closed = set()
    for number, wire in enumerate(wires, 1):

        async def close(number=number):
            await asyncio.sleep(0)
            await asyncio.sleep(0)  # #171: wait for the original suspended close.
            closed.add(number)

        wire.close.side_effect = close
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client = coordinator.client
    assert type(client) is HobenClient and client.ha_reconnect_enabled
    lifecycle = peers.lifecycles[0]
    faults = (
        (b"\x04",),  # unsupported post-open discriminator, no length invented
        (b"\x0e\xff\xff\x00\x00\xff\xff",),  # rejected MBAP length
        (b"\x05", TransportEOF(PRIVATE_TEXT)),  # EOF before the close subcode
    )
    try:
        for generation, deliveries in enumerate(faults, 1):
            previous, stamp = coordinator.data, coordinator.last_successful_read_at
            before_writes = sum(w.write.await_count for w in wires)
            for delivery in deliveries:
                wires[generation - 1].queue.put_nowait(delivery)
            await pump()
            assert sleep.await_count == generation
            assert sleep.await_args.args == (60,)
            assert generation in closed
            wires[generation - 1].close.assert_awaited_once_with()
            o = client.session_observation
            assert o.cleaned_generation == generation and not o.cleanup_failed
            assert not o.active
            assert len(peers.lifecycles) == 1 and not lifecycle._task.done()
            assert not any(
                t.get_name() == "hoben-v4-rx" and not t.done()
                for t in asyncio.all_tasks()
            )
            state = session_state(hass, entry)
            assert state.state == "reconnecting"
            assert state.attributes["last_error_category"] == "malformed_response"
            assert state.attributes["last_error_phase"] == "frame_boundary"
            assert state.attributes["reconnect_count"] == generation - 1
            assert state.attributes["recovery_count"] == min(generation, 2)
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert coordinator.data is previous and not coordinator.last_update_success
            assert coordinator.last_successful_read_at == stamp
            # B7 retains the validated value within 300 s of the real loss;
            # opening/retry still proves neither acquisition nor freshness.
            assert sensor(hass, entry).state != "unavailable"
            assert coordinator.last_snapshot_held
            assert sum(w.write.await_count for w in wires) == before_writes
            freezer.tick(timedelta(seconds=59))
            await pump()
            assert peers.factory.call_count == generation
            freezer.tick(timedelta(seconds=1.001))
            await pump()
            assert peers.factory.call_count == generation + 1
            o = client.session_observation
            assert o.active and o.generation == generation + 1
            assert o.read_generation is None and o.read_sequence is None
            assert (
                coordinator.data is previous
                and coordinator.last_successful_read_at == stamp
            )
            assert not coordinator.last_update_success
            assert (
                session_state(hass, entry).attributes["reconnect_count"] == generation
            )
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert coordinator.last_update_success and coordinator.data is not previous
            assert coordinator.last_successful_read_at > stamp
            assert sensor(hass, entry).state != "unavailable"
            o = client.session_observation
            assert o.read_generation == generation + 1 and o.read_sequence == 1
            assert (
                client is entry.runtime_data.client and client._lifecycle is lifecycle
            )
            assert (
                sum(not w.close.await_count for w in wires[: peers.factory.call_count])
                == 1
            )
        errors = records(caplog, "error")
        assert [r["generation"] for r in errors] == [1, 2, 3]
        assert all(r["category"] == "protocol" for r in errors)
        assert errors[0]["expected_total_bytes"] == "unknown"
        assert errors[2]["received_bytes"] == 1
        assert_private_values_absent(caplog.text)
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
