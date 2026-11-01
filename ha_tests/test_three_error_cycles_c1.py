"""C1 proof: one real HA client, three ordered faults, synthetic TLS/time only.

The acceptance test is intentionally RED on the integrated policy: the third
fault is permanent. Keep that evidence separate from a deliverable/green CI.
"""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

from conftest import DEVICE_GUID, PRIVATE_TEXT, assert_private_values_absent

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.client import HobenClient
from custom_components.hoben.safe_reports import safe_error_report
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import pump
from tests.test_frame_logging import LOGGER, records


async def observe_three_cycles(hass, entry, peers, freezer, monkeypatch, caplog):
    """Observe actual owners; never fabricate a retry or replace the client."""
    owners = peers.lifecycles
    sleep = AsyncMock(side_effect=asyncio.sleep)

    def make_owner(**options):
        # Use the actual timer, advanced by freezer, instead of the ordinary
        # peers fixture's manually released backoff gate. No retry changes.
        options["sleep"] = sleep
        owner = V4Lifecycle(**options)
        owners.append(owner)
        return owner

    monkeypatch.setattr(v4_lifecycle, "V4Lifecycle", make_owner)
    wires = []
    for value in range(17, 21):
        reply = RESPONSE[:10] + value.to_bytes(2, "big") * 20
        wires.append(peers.wire(DEVICE_GUID, [[reply[:7], reply[7:] + b"\x0a"]]))
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()  # manual acquisitions only in this proof
    client = coordinator.client
    assert type(client) is HobenClient and client.ha_reconnect_enabled
    assert len(owners) == 1
    owner = owners[0]
    report = {"cycles": [], "client_count": 1, "cleanup": False}
    try:
        for generation, fault in enumerate(
            [TransportTlsError(PRIVATE_TEXT), TransportEOF(PRIVATE_TEXT)], 1
        ):
            previous, stamp = coordinator.data, coordinator.last_successful_read_at
            read_sequence = client.session_observation.read_sequence
            before_writes = sum(w.write.await_count for w in wires)
            wires[generation - 1].queue.put_nowait(fault)
            await pump()
            assert sleep.await_count == generation
            assert sleep.await_args.args == (60,)
            wires[generation - 1].close.assert_awaited_once_with()
            o = client.session_observation
            assert o.cleaned_generation == generation and not o.cleanup_failed
            assert o.loss_generation == generation and not o.active
            assert (
                sum(
                    t.get_name() == "hoben-v4-lifecycle" and not t.done()
                    for t in asyncio.all_tasks()
                )
                == 1
            )
            assert not any(
                t.get_name() == "hoben-v4-rx" and not t.done()
                for t in asyncio.all_tasks()
            )
            state = session_state(hass, entry)
            assert state.state == "reconnecting"
            assert state.attributes["last_error_category"] == "transport_unavailable"
            assert state.attributes["last_error_phase"] == "tls_read"
            assert state.attributes["reconnect_count"] == generation - 1
            assert state.attributes["recovery_count"] == 0
            # Polling while backoff is pending cannot publish cached freshness.
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert coordinator.data is previous and not coordinator.last_update_success
            assert coordinator.last_successful_read_at == stamp
            assert sensor(hass, entry).state == "unavailable"
            assert sum(w.write.await_count for w in wires) == before_writes
            freezer.tick(timedelta(seconds=59))
            await pump()
            assert peers.factory.call_count == generation
            assert coordinator.last_successful_read_at == stamp
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
            o = client.session_observation
            assert coordinator.last_update_success and coordinator.data is not previous
            assert coordinator.last_successful_read_at > stamp
            assert sensor(hass, entry).state != "unavailable"
            assert o.read_generation == generation + 1 and o.read_sequence == 1
            assert read_sequence == 1 and o.cleaned_generation == generation
            assert client is entry.runtime_data.client and client._lifecycle is owner
            assert len(owners) == 1 and not owner._task.done()
            assert (
                sum(
                    t.get_name() == "hoben-v4-rx" and not t.done()
                    for t in asyncio.all_tasks()
                )
                == 1
            )
            assert (
                sum(not w.close.await_count for w in wires[: peers.factory.call_count])
                == 1
            )
            report["cycles"].append(
                dict(
                    fault="tls_read" if generation == 1 else "eof",
                    generation=generation,
                    cleaned=o.cleaned_generation == generation and not o.cleanup_failed,
                    delay_seconds=60,
                    read_generation=o.read_generation,
                    correlated=o.read_generation == generation + 1
                    and o.read_sequence == 1,
                    reconnect_count=session_state(hass, entry).attributes[
                        "reconnect_count"
                    ],
                    recovered=coordinator.last_update_success
                    and o.read_generation == generation + 1,
                )
            )

        previous, stamp = coordinator.data, coordinator.last_successful_read_at

        def fatal(_framer, _data, _exchange):
            raise RuntimeError(PRIVATE_TEXT)

        monkeypatch.setattr(
            "custom_components.hoben.v4_experiment.ExperimentalV4Framer.feed", fatal
        )
        wires[2].queue.put_nowait(b"\x0a")
        await pump()
        assert owner._task.done() and owner._session is None
        assert not any(
            t.get_name() == "hoben-v4-rx" and not t.done() for t in asyncio.all_tasks()
        )
        wires[2].close.assert_awaited_once_with()
        o = client.session_observation
        assert o.cleaned_generation == 3 and not o.cleanup_failed and not o.active
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        await pump()
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        assert (
            not coordinator.last_update_success
            and sensor(hass, entry).state == "unavailable"
        )
        safe = safe_error_report(coordinator.last_exception)
        assert safe["error"] == "internal_failure" and safe["phase"] == "frame_boundary"
        state = session_state(hass, entry)
        assert state.state == "disconnected"
        assert state.attributes["last_error_category"] == "internal_failure"
        assert state.attributes["last_error_phase"] == "frame_boundary"
        assert (
            state.attributes["reconnect_count"] == 2
            and state.attributes["recovery_count"] == 0
        )
        # Waiting cannot create a fourth session under this permanent policy.
        freezer.tick(timedelta(seconds=120))
        await pump()
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert sleep.await_count == 2 and peers.factory.call_count == 3
        wires[3].connect.assert_not_awaited()
        assert client is entry.runtime_data.client and len(owners) == 1
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        error_logs = records(caplog, "error")
        assert [r["generation"] for r in error_logs] == [1, 2, 3]
        assert error_logs[-1]["category"] == "unexpected_error"
        assert error_logs[-1]["phase"] == "frame_boundary"
        assert (
            error_logs[-1]["received_bytes"]
            == error_logs[-1]["expected_total_bytes"]
            == "unknown"
        )
        assert all(r.exc_info is None for r in caplog.records if r.name == LOGGER)
        assert_private_values_absent(str(report) + caplog.text)
        report["cycles"].append(
            dict(
                fault="fatal_rx",
                generation=3,
                cleaned=o.cleaned_generation == 3 and not o.cleanup_failed,
                category="internal_failure",
                phase="frame_boundary",
                read_generation=o.read_generation,
                correlated=client.session_observation.read_generation == 4,
                reconnect_count=state.attributes["reconnect_count"],
                recovered=coordinator.last_update_success
                and client.session_observation.read_generation == 4,
            )
        )
        assert all(
            call.args[0][0] in {3, 11, 13}
            for w in wires
            for call in w.write.await_args_list
        )
        assert all(
            call.args[0][8] == 4
            for w in wires
            for call in w.write.await_args_list
            if call.args[0][0] == 13
        )
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)
        assert not any(
            t.get_name() == "hoben-dataupdated-probe" and not t.done()
            for t in asyncio.all_tasks()
        )
        report["cleanup"] = True
    return report


async def test_c1_requires_three_correlated_recoveries(
    hass, entry, peers, freezer, monkeypatch, caplog
):
    report = await observe_three_cycles(
        hass, entry, peers, freezer, monkeypatch, caplog
    )
    assert report["cleanup"]
    assert [c["recovered"] for c in report["cycles"]] == [True, True, True], (
        "C1 blocked: fatal RX remains permanent internal_failure/frame_boundary"
    )


async def test_c1_characterizes_the_existing_permanent_third_fault(
    hass, entry, peers, freezer, monkeypatch, caplog
):
    report = await observe_three_cycles(
        hass, entry, peers, freezer, monkeypatch, caplog
    )
    assert report["cleanup"] and report["client_count"] == 1
    assert [c["fault"] for c in report["cycles"]] == ["tls_read", "eof", "fatal_rx"]
    assert [c["recovered"] for c in report["cycles"]] == [True, True, False]
