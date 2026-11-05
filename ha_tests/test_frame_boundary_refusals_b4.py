"""B4 refuses unclassified/local faults and cannot bypass HA ownership gates."""

import asyncio
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, PRIVATE_TEXT, assert_private_values_absent
from homeassistant.config_entries import ConfigEntryState

from custom_components.hoben.error_phases import with_phase
from custom_components.hoben.exceptions import HobenFrameBoundaryError
from custom_components.hoben.malformed import MalformedDiagnostic
from custom_components.hoben.transport import TransportEOF, TransportError
from custom_components.hoben.v4_session import V4Session
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import BAD, Clock, pump
from tests.tls_script import script_transport


@pytest.mark.parametrize(
    "kind",
    [
        "generic_framer",
        "phase_only",
        "foreign_typed",
        "contract",
        "oversized",
        "close_error",
        "close_cancelled",
        "unconfirmed",
        "postopen_auth",
        "postopen_auth_response",
    ],
)
async def test_unclassified_errors_and_failed_cleanup_never_reopen(
    hass, entry, peers, monkeypatch, caplog, kind
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    spare = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    if kind == "generic_framer":
        monkeypatch.setattr(
            "custom_components.hoben.v4_experiment.ExperimentalV4Framer.feed",
            Mock(side_effect=RuntimeError(PRIVATE_TEXT)),
        )
        fault = b"\x0a"
    elif kind == "phase_only":
        fault = with_phase(RuntimeError(PRIVATE_TEXT), "frame_boundary")
    elif kind == "foreign_typed":
        fault = HobenFrameBoundaryError(MalformedDiagnostic(), "unknown_type")
    elif kind == "contract":
        fault = bytearray(b"\x0a")
    elif kind == "oversized":
        fault = b"\x0a" * 4097
    elif kind in {"postopen_auth", "postopen_auth_response"}:
        fault = b"\x2f" if kind == "postopen_auth" else b"\x30"
    else:
        fault = b"\x04"
        if kind == "unconfirmed":
            monkeypatch.setattr(
                V4Session, "cleanup_succeeded", property(lambda _: False)
            )
        else:
            wire.close.side_effect = (
                TransportError(PRIVATE_TEXT)
                if kind == "close_error"
                else asyncio.CancelledError()
            )
    wire.queue.put_nowait(fault)
    await pump()
    owner = peers.lifecycles[0]
    assert owner._task.done() and not coordinator.client.ha_recovery_pending
    assert not peers.backoff.delays and peers.factory.call_count == 1
    spare.connect.assert_not_awaited()
    await coordinator.async_refresh()
    assert not coordinator.last_update_success and coordinator.data is previous
    assert coordinator.last_successful_read_at == stamp
    assert sensor(hass, entry).state == "unavailable"
    state = session_state(hass, entry)
    assert state.state == "disconnected" and state.attributes["reconnect_count"] == 0
    if kind in {"close_error", "close_cancelled", "unconfirmed"}:
        assert state.attributes["last_error_category"] == "cleanup_failed"
        assert state.attributes["last_error_phase"] == "cleanup"
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "reply", [b"\x05\x02", b"\x2f"], ids=["rejected_identity", "authorization_required"]
)
async def test_auth_refusal_after_boundary_is_terminal_without_false_reconnect(
    hass, entry, peers, reply
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    second = peers.wire(DEVICE_GUID, [])
    script_transport(second, openings=[[reply]])
    coordinator = await load(hass, entry)
    stamp = coordinator.last_successful_read_at
    first.queue.put_nowait(b"\x04")
    assert await peers.backoff.entered.get() == 60
    peers.backoff.release.put_nowait(None)
    await pump()
    assert peers.lifecycles[0]._task.done() and peers.factory.call_count == 2
    assert peers.backoff.delays == [60]
    assert coordinator.last_successful_read_at == stamp
    assert session_state(hass, entry).attributes["reconnect_count"] == 0
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_boundary_during_first_read_recovers_on_same_setup_owner(
    hass, entry, peers
):
    first = peers.wire(DEVICE_GUID, [[b"\x04"]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    try:
        assert await peers.backoff.entered.get() == 60
        assert entry.state is ConfigEntryState.SETUP_IN_PROGRESS and not setup.done()
        assert len(peers.lifecycles) == 1 and peers.factory.call_count == 1
        first.close.assert_awaited_once_with()
        peers.backoff.release.put_nowait(None)
        assert await setup
        assert entry.runtime_data.coordinator.last_update_success
        assert peers.factory.call_count == 2 and len(peers.lifecycles) == 1
    finally:
        if not setup.done():
            setup.cancel()
            await asyncio.gather(setup, return_exceptions=True)
        if entry.state is ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


@pytest.mark.parametrize("stop_at", ["cleanup", "backoff"])
async def test_unload_during_owned_cleanup_or_backoff_prevents_late_open(
    hass, entry, peers, stop_at
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    spare = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    entered = asyncio.Event()
    if stop_at == "cleanup":

        async def close():
            entered.set()
            await asyncio.Future()

        first.close.side_effect = close
    first.queue.put_nowait(b"\x04")
    if stop_at == "cleanup":
        await entered.wait()
    else:
        assert await peers.backoff.entered.get() == 60
    assert await hass.config_entries.async_unload(entry.entry_id)
    await pump()
    assert coordinator.client.session_observation.stopped
    assert peers.factory.call_count == 1
    spare.connect.assert_not_awaited()
    assert_stopped(peers)


async def test_invalid_dataupdated_keeps_original_tls_and_one_30s_probe(
    hass, entry, peers, monkeypatch
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    clock = Clock(monkeypatch)
    wire.queue.put_nowait(BAD)
    await pump()
    assert coordinator.client.data_updated_recovering
    assert (
        not coordinator.client._lifecycle._session.has_classified_frame_boundary_failure
    )
    await clock.advance(29)
    assert wire.write.await_count == 2
    await clock.advance(1)
    assert wire.write.await_count == 3
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    wire.close.assert_not_awaited()
    assert peers.factory.call_count == 1 and not peers.backoff.delays
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("recover", [False, True])
async def test_open_failures_keep_one_supervisor_and_60s_wait_without_attempt_cap(
    hass, entry, peers, recover
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    for _ in range(3):
        wire = peers.wire(DEVICE_GUID, [])
        wire.connect.side_effect = TransportError(PRIVATE_TEXT)
    if recover:
        peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    first.queue.put_nowait(b"\x04")
    try:
        for number in range(1, 5):
            assert await peers.backoff.entered.get() == 60
            assert peers.factory.call_count == number and len(peers.lifecycles) == 1
            assert not peers.lifecycles[0]._task.done()
            peers.wires[number - 1].close.assert_awaited_once_with()
            assert session_state(hass, entry).attributes["reconnect_count"] == 0
            if number < 4 or recover:
                peers.backoff.release.put_nowait(None)
        if recover:
            await peers.lifecycles[0].wait_connected()
            await pump()
            assert peers.factory.call_count == 5
            assert session_state(hass, entry).attributes["reconnect_count"] == 1
            await coordinator.async_refresh()
            assert coordinator.last_update_success
        assert peers.backoff.delays == [60] * 4
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_b7_partial_eof_keeps_owner_loss_visible_while_retaining_old_values(
    hass, entry, peers
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [b"\x04"]])
    second = peers.wire(DEVICE_GUID, [])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    try:
        await coordinator.async_refresh()
        assert await peers.backoff.entered.get() == 60
        assert coordinator.last_snapshot_held
        peers.backoff.release.put_nowait(None)
        await peers.lifecycles[0].wait_connected()
        second.queue.put_nowait(b"\x05")
        second.queue.put_nowait(TransportEOF(PRIVATE_TEXT))
        assert await peers.backoff.entered.get() == 60
        await pump()
        assert coordinator.last_snapshot_held
        assert coordinator.client.session_observation.loss_generation == 2
        await coordinator.async_refresh()
        assert coordinator.snapshot_available and not coordinator.last_update_success
        assert sensor(hass, entry).state != "unavailable"
        assert session_state(hass, entry).state == "reconnecting"
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(peers)


async def test_native_reload_reaps_boundary_supervisor_before_new_client(
    hass, entry, peers, freezer
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    peers.wire(DEVICE_GUID, [[RESPONSE[:10] + b"\x00\x13" * 20]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    old_client, old_owner = coordinator.client, peers.lifecycles[0]
    first.queue.put_nowait(b"\x04")
    assert await peers.backoff.entered.get() == 60
    assert await hass.config_entries.async_reload(entry.entry_id)
    new = entry.runtime_data.coordinator
    new._async_unsub_refresh()
    assert new.client is not old_client and old_owner._task.done()
    assert old_client.session_observation.stopped
    assert new.last_update_success and new.data.raw.registers == (19,) * 20
    assert len(peers.lifecycles) == 2 and peers.factory.call_count == 2
    freezer.tick(600)
    await pump()
    assert peers.factory.call_count == 2
    assert session_state(hass, entry).attributes["reconnect_count"] == 0
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
