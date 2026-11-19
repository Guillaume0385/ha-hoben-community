"""#220 bounded HA bootstrap with the real owners and synthetic transports."""

import asyncio

import pytest
from conftest import DEVICE_GUID, ROTATED_DEVICE_GUID, assert_private_values_absent
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState
from homeassistant.helpers import entity_registry as er

from custom_components.hoben.const import CONF_DEVICE_GUID
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportError,
    TransportTlsError,
)
from ha_tests.test_data_updated_push_219 import push_peers as push_peers  # noqa: F401
from ha_tests.test_data_updated_push_219 import updated
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, sensor
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from tests.test_data_updated_silence import Clock, pump
from tests.tls_script import script_transport


async def blocked(*args, **kwargs):
    await asyncio.Future()


def offline_wire(peers, phase):
    wire = peers.wire(ROTATED_DEVICE_GUID, [[]])
    if phase == "connect":
        wire.connect.side_effect = blocked
    elif phase == "opening":
        script_transport(wire, openings=[[]])
    elif phase == "tcp":
        wire.connect.side_effect = TransportError("PRIVATE_PAYLOAD")
    elif phase == "tls":
        wire.connect.side_effect = TransportTlsError("PRIVATE_PAYLOAD")
    elif phase in {"backoff", "stove_offline"}:
        script_transport(
            wire, openings=[[b"\x05\x06" if phase == "backoff" else b"\x05\x03"]]
        )
    return wire


async def settle_attempt(peers):
    for _ in range(20):
        await pump()
        if peers.factory.call_count:
            await pump()
            return
    raise AssertionError("synthetic opening was not reached")


@pytest.mark.parametrize(
    "phase", ["connect", "opening", "read", "tcp", "tls", "backoff", "stove_offline"]
)
async def test_offline_bootstrap_returns_for_native_retry_without_orphans(
    hass, entry, push_peers, monkeypatch, caplog, phase
):
    clock = Clock(monkeypatch)
    offline_wire(push_peers, phase)
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    try:
        await settle_attempt(push_peers)
        if not setup.done():
            await clock.advance(10)
        assert setup.done(), "offline Hoben must release HA bootstrap within 15 s"
        assert not await setup
        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert not hasattr(entry, "runtime_data")
        assert not er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        assert push_peers.factory.call_count == 1
        assert_stopped(push_peers)
        evidence = push_peers.lifecycles[0].session_observation
        assert evidence.stopped and not evidence.active and not evidence.cleanup_failed
        if phase == "read":
            assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
        assert_private_values_absent(caplog.text)
    finally:
        if not setup.done():
            setup.cancel()
        await asyncio.gather(setup, return_exceptions=True)


async def test_native_retry_recovers_after_multiple_failures_with_real_initial_read(
    hass, entry, push_peers, monkeypatch, caplog
):
    hass.set_state(CoreState.running)
    clock = Clock(monkeypatch)
    offline_wire(push_peers, "tcp")
    offline_wire(push_peers, "backoff")
    online = push_peers.wire(
        ROTATED_DEVICE_GUID, [[updated((234,) * 20), b"\x0a", RESPONSE]]
    )
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    try:
        await settle_attempt(push_peers)
        await clock.advance(10)
        await pump()
        await pump()
        assert setup.done(), "first offline attempt still owns bootstrap"
        assert not await setup
        assert_stopped(push_peers)
        assert push_peers.factory.call_count == 1
        # HA owns backoff between complete attempts; no lifecycle is released
        # manually and no new owner may overlap an unclosed previous attempt.
        for delay, expected in [(15, 2), (30, 3)]:
            await clock.advance(delay)
            await pump()
            assert push_peers.factory.call_count == expected
            for owner in push_peers.lifecycles[:-1]:
                assert owner.session_observation.stopped
                assert not owner.session_observation.cleanup_failed
            if expected == 2:
                await clock.advance(10)
                assert entry.state is ConfigEntryState.SETUP_RETRY
                assert_stopped(push_peers)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        coordinator = entry.runtime_data.coordinator
        assert coordinator.data.raw.registers == (234,) * 20
        assert sensor(hass, entry).state == "23.4"
        assert coordinator.update_interval is None
        assert push_peers.lifecycles[-1].witness.verified_read_sequence == 1
        assert [c.args[0][0] for c in online.write.await_args_list] == [3, 13, 11]
        assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
        assert entry.data["future_setting"] == "retained"
        assert_private_values_absent(caplog.text)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)
    finally:
        if not setup.done():
            setup.cancel()
        await asyncio.gather(setup, return_exceptions=True)


@pytest.mark.parametrize("close_fails", [False, True])
async def test_cleanup_is_part_of_fifteen_second_budget_and_gates_native_retry(
    hass, entry, push_peers, monkeypatch, close_fails
):
    clock = Clock(monkeypatch)
    wire = offline_wire(push_peers, "read")
    if close_fails:
        push_peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    closing = asyncio.Event()

    async def close():
        closing.set()
        await asyncio.sleep(5)
        if close_fails:
            raise TransportError("PRIVATE_PAYLOAD")

    wire.close.side_effect = close
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    try:
        await settle_attempt(push_peers)
        await clock.advance(10)
        assert closing.is_set(), "setup deadline must stop the active owner"
        assert not setup.done()
        await clock.advance(5)
        assert setup.done() and not await setup
        assert clock.now == 15
        assert entry.state is (
            ConfigEntryState.SETUP_ERROR
            if close_fails
            else ConfigEntryState.SETUP_RETRY
        )
        assert push_peers.factory.call_count == 1
        assert_stopped(push_peers)
        if close_fails:
            assert entry.runtime_data.setup_cleanup_failed
            assert entry.runtime_data.coordinator.data is None
        else:
            assert not hasattr(entry, "runtime_data")
        assert (
            push_peers.lifecycles[0].session_observation.cleanup_failed is close_fails
        )
        if close_fails:
            await clock.advance(600)
            assert push_peers.factory.call_count == 1
            assert not await hass.config_entries.async_reload(entry.entry_id)
            assert push_peers.factory.call_count == 1
    finally:
        if not setup.done():
            setup.cancel()
            await pump()
            await clock.advance(5)
        await asyncio.gather(setup, return_exceptions=True)


@pytest.mark.parametrize("phase", ["connect", "opening", "read", "backoff"])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancellation_or_ha_stop_reaps_initial_attempt(
    hass, entry, push_peers, monkeypatch, phase, shutdown
):
    clock = Clock(monkeypatch)
    offline_wire(push_peers, phase)
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    await settle_attempt(push_peers)
    if shutdown:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    else:
        setup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await setup
    await pump()
    assert_stopped(push_peers)
    assert not hasattr(entry, "runtime_data")
    await clock.advance(600)
    assert push_peers.factory.call_count == 1


@pytest.mark.parametrize("reply", [b"\x05\x02", b"\x05\x04", b"\x05\x05", b"\x2f"])
async def test_authentication_refusal_stays_terminal(
    hass, entry, push_peers, monkeypatch, reply, caplog
):
    clock = Clock(monkeypatch)
    wire = push_peers.wire(DEVICE_GUID, [])
    script_transport(wire, openings=[[reply]])
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert push_peers.backoff.delays == []
    assert_stopped(push_peers)
    await clock.advance(600)
    assert push_peers.factory.call_count == 1
    assert_private_values_absent(caplog.text)


async def test_certificate_failure_stays_terminal(hass, entry, push_peers):
    wire = push_peers.wire(DEVICE_GUID, [])
    wire.connect.side_effect = TransportCertificateError("PRIVATE_PAYLOAD")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert_stopped(push_peers)


async def test_second_cancellation_during_cleanup_never_permits_reload(
    hass, entry, push_peers, monkeypatch
):
    clock = Clock(monkeypatch)
    wire = offline_wire(push_peers, "read")
    push_peers.wire(DEVICE_GUID, [[RESPONSE]])
    closing = asyncio.Event()

    async def close():
        closing.set()
        await asyncio.Future()

    wire.close.side_effect = close
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    await settle_attempt(push_peers)
    await clock.advance(10)
    assert closing.is_set()
    setup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await setup
    assert_stopped(push_peers)
    assert entry.runtime_data.setup_cleanup_failed
    assert entry.runtime_data.client.session_observation.cleanup_failed
    assert not await hass.config_entries.async_reload(entry.entry_id)
    assert push_peers.factory.call_count == 1


async def test_reload_cancels_native_wait_and_creates_only_one_fresh_owner(
    hass, entry, push_peers, monkeypatch
):
    clock = Clock(monkeypatch)
    offline_wire(push_peers, "read")
    online = push_peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    try:
        await settle_attempt(push_peers)
        await clock.advance(10)
        assert setup.done() and not await setup
        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert_stopped(push_peers)
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert entry.state is ConfigEntryState.LOADED
        assert push_peers.factory.call_count == 2
        assert [c.args[0][0] for c in online.write.await_args_list] == [3, 13]
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert_stopped(push_peers)
    finally:
        if not setup.done():
            setup.cancel()
        await asyncio.gather(setup, return_exceptions=True)
