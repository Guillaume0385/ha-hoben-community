"""B2 proof attempt on the integrated baseline; no production monkeypatches.

Only byte peers and elapsed time are synthetic. A passing baseline cannot
justify changing production recovery or the established availability contract.
"""

import asyncio
from datetime import timedelta

import pytest
from conftest import DEVICE_GUID, ROTATED_DEVICE_GUID, assert_private_values_absent
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util

from custom_components.hoben.const import CONF_DEVICE_GUID
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from custom_components.hoben.transport import TransportCertificateError, TransportEOF
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, opening
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import measures, session_state
from tests.test_data_updated_silence import Clock, pump
from tests.tls_script import script_transport

FRESH = RESPONSE[:10] + b"\x00\x13" * 20


@pytest.fixture
def timed_backoff(peers, monkeypatch):
    async def wait(backoff, delay):
        backoff.delays.append(delay)
        backoff.entered.put_nowait(delay)
        await asyncio.sleep(delay)

    monkeypatch.setattr(type(peers.backoff), "__call__", wait)
    return peers.backoff


async def refresh(coordinator):
    await coordinator.async_refresh()
    # Each refresh rearms the normal HA poll. This test explicitly controls it
    # to distinguish an accepted opening from a subsequent actual acquisition.
    coordinator._async_unsub_refresh()


@pytest.mark.parametrize(
    "delivery,category,phase,reason",
    [
        (
            [b"\x05\x03"],
            "experimental_close_client",
            "post_open",
            "stove_connection_required",
        ),
        (
            [b"\x05", b"\x03"],
            "experimental_close_client",
            "post_open",
            "stove_connection_required",
        ),
        (
            [b"\x05\x03" + RESPONSE + b"\x0a"],
            "experimental_close_client",
            "post_open",
            "stove_connection_required",
        ),
        ([b"\x05\x06"], "experimental_close_client", "post_open", "server_maintenance"),
        ([TransportEOF("PRIVATE_PAYLOAD")], "transport_unavailable", "tls_read", None),
    ],
    ids=[
        "close03",
        "close03_fragmented",
        "close03_suffix",
        "maintenance_postopen",
        "eof",
    ],
)
async def test_baseline_postopen_refresh_recovers_after_elapsed_60s_and_a_new_read(
    hass,
    entry,
    peers,
    timed_backoff,
    monkeypatch,
    freezer,
    caplog,
    delivery,
    category,
    phase,
    reason,
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], delivery])
    second = peers.wire(ROTATED_DEVICE_GUID, [[FRESH], [FRESH]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    lifecycle = peers.lifecycles[0]
    old = lifecycle._session
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    clock = Clock(monkeypatch)

    await refresh(coordinator)
    assert await timed_backoff.entered.get() == 60
    await pump()
    report = await async_get_config_entry_diagnostics(hass, entry)
    error = report["coordinator"]["last_error"]
    assert error["error"] == category and error["phase"] == phase
    if reason:
        assert error["reason"] == reason
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert not coordinator.last_update_success
    state = session_state(hass, entry)
    assert state.state == "reconnecting"
    assert state.attributes["last_error_category"] == category
    assert state.attributes["last_error_phase"] == phase
    assert state.attributes["reconnect_count"] == 0
    error_at = state.attributes["last_error_at"]
    assert peers.factory.call_count == 1 and len(peers.lifecycles) == 1
    first.close.assert_awaited_once_with()
    assert old.cleanup_succeeded and old._transport is None
    assert old._pending_read is None and not old._operations
    assert old._rx_task is None or old._rx_task.done()

    for elapsed in (30, 29):
        freezer.tick(timedelta(seconds=elapsed))
        await clock.advance(elapsed)
        await refresh(coordinator)
        assert peers.factory.call_count == 1
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        assert not coordinator.last_update_success
        state = session_state(hass, entry)
        assert state.state == "reconnecting"
        assert state.attributes["last_error_at"] == error_at
        assert state.attributes["reconnect_count"] == 0

    # A frozen epoch can round asyncio's resolution below one float unit.
    # Observe just after eligibility rather than imposing an exact deadline.
    freezer.tick(timedelta(seconds=1.001))
    await clock.advance(1.001)
    assert peers.factory.call_count == 2 and len(peers.lifecycles) == 1
    assert coordinator.client._lifecycle is lifecycle
    assert session_state(hass, entry).state == "connected"
    assert session_state(hass, entry).attributes["reconnect_count"] == 1
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert not coordinator.last_update_success  # Acceptance is not a fresh read.
    assert all(s.state == "unavailable" for s in measures(hass, entry).values())
    assert second.write.await_count == 1  # Only OpenClient; no failed read replay.

    await refresh(coordinator)
    assert coordinator.last_update_success and coordinator.data is not previous
    assert coordinator.data.raw.registers == (19,) * 20
    assert coordinator.last_successful_read_at == dt_util.utcnow()
    assert lifecycle.witness.verified_read_generation == 2
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert all(s.state != "unavailable" for s in measures(hass, entry).values())
    assert [c.args[0][0] for c in first.write.await_args_list] == [3, 13, 13]
    assert [c.args[0][0] for c in second.write.await_args_list] == [3, 13]
    assert second.write.await_args_list[0].args[0][37:69] == DEVICE_GUID.encode()
    await refresh(coordinator)
    assert peers.factory.call_count == 2 and timed_backoff.delays == [60]
    assert_private_values_absent(str(report) + str(state.attributes) + caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await clock.advance(180)
    assert peers.factory.call_count == 2
    assert_stopped(peers)


@pytest.mark.parametrize("scenario", ["postopen03", "postopen06", "opening06"])
async def test_baseline_setup_keeps_one_owner_until_a_valid_acquisition(
    hass, entry, peers, timed_backoff, monkeypatch, scenario
):
    owners = []

    def make_coordinator(*args):
        owner = HobenDataUpdateCoordinator(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr(
        "custom_components.hoben.coordinator.HobenDataUpdateCoordinator",
        make_coordinator,
    )
    first = peers.wire(
        DEVICE_GUID, [[b"\x05\x03" if scenario == "postopen03" else b"\x05\x06"]]
    )
    if scenario == "opening06":
        script_transport(first, openings=[[b"\x05\x06"]])
    peers.wire(ROTATED_DEVICE_GUID, [[FRESH]])
    clock = Clock(monkeypatch)
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    assert await timed_backoff.entered.get() == 60
    await pump()
    assert entry.state is ConfigEntryState.SETUP_IN_PROGRESS and not setup.done()
    assert len(owners) == len(peers.lifecycles) == 1
    assert owners[0].data is None and owners[0].last_successful_read_at is None
    assert not measures(hass, entry)
    monitor = owners[0].client.session_monitor
    assert monitor.last_error_category == (
        "server_closed" if scenario == "opening06" else "experimental_close_client"
    )
    assert monitor.last_error_phase == (
        "opening" if scenario == "opening06" else "post_open"
    )
    first.close.assert_awaited_once_with()
    await clock.advance(59)
    assert not setup.done() and peers.factory.call_count == 1
    await clock.advance(1)
    assert await setup
    assert entry.state is ConfigEntryState.LOADED
    assert len(owners) == len(peers.lifecycles) == 1 and peers.factory.call_count == 2
    assert entry.runtime_data.coordinator is owners[0]
    assert owners[0].last_update_success and owners[0].data.raw.registers == (19,) * 20
    assert owners[0].last_successful_read_at is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await clock.advance(180)
    assert peers.factory.call_count == 2
    assert_stopped(peers)


async def test_baseline_close03_unload_during_backoff_cannot_reopen(
    hass, entry, peers, timed_backoff, monkeypatch
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [b"\x05\x03"]])
    peers.wire(ROTATED_DEVICE_GUID, [[FRESH]])
    coordinator = await load(hass, entry)
    clock = Clock(monkeypatch)
    await refresh(coordinator)
    assert await timed_backoff.entered.get() == 60
    assert await hass.config_entries.async_unload(entry.entry_id)
    await clock.advance(180)
    assert peers.factory.call_count == 1
    assert not coordinator.client.session_monitor._listeners
    assert_stopped(peers)


@pytest.mark.parametrize("scenario", ["opening03", "auth", "certificate", "profile"])
async def test_baseline_permanent_setup_refusals_never_retry(
    hass, entry, peers, timed_backoff, monkeypatch, scenario
):
    wire = peers.wire(DEVICE_GUID, [])
    if scenario == "certificate":
        wire.connect.side_effect = TransportCertificateError("PRIVATE_PAYLOAD")
    elif scenario in {"opening03", "auth"}:
        script_transport(
            wire, openings=[[b"\x05\x03" if scenario == "opening03" else b"\x05\x02"]]
        )
    else:
        unsupported = bytearray(opening(DEVICE_GUID))
        unsupported[8] = 0
        script_transport(wire, openings=[[bytes(unsupported)]])
    clock = Clock(monkeypatch)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await clock.advance(180)
    assert not hasattr(entry, "runtime_data")
    assert peers.factory.call_count == 1 and timed_backoff.delays == []
    assert_stopped(peers)
