"""Real HA/client/shared runtime over deterministic in-memory TLS peers only."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from conftest import (
    DEVICE_GUID,
    ROTATED_DEVICE_GUID,
    assert_private_values_absent,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.client import HobenClient
from custom_components.hoben.const import CONF_DEVICE_GUID
from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportEOF,
    TransportTlsError,
)
from tests.test_v4_lifecycle import Backoff
from tests.tls_script import script_transport


def opening(identity):
    return (
        bytes([4, 0, 0, 0, 0, 0, 0, 0, 5, 2, 8, 0, 0, 0])
        + identity.encode()
        + b"\x00\x02"
    )


RESPONSE = bytes.fromhex("0effff0000002b010428") + b"\x00\x11" * 20


@pytest.fixture
def peers(monkeypatch):
    """Only inject byte transports and backoff; instantiate the actual owners."""
    wires, lifecycles, backoff = [], [], Backoff()

    def wire(identity, reads):
        transport = Mock(
            spec=AsyncTlsTransport,
            connect=AsyncMock(),
            read=AsyncMock(),
            write=AsyncMock(),
            close=AsyncMock(),
        )
        transport.queue = script_transport(
            transport, openings=[[opening(identity)]], reads=reads
        )
        wires.append(transport)
        return transport

    real_lifecycle = v4_lifecycle.V4Lifecycle

    def make_lifecycle(**kwargs):
        kwargs["sleep"] = backoff
        lifecycle = real_lifecycle(**kwargs)
        lifecycles.append(lifecycle)
        return lifecycle

    monkeypatch.setattr(v4_lifecycle, "V4Lifecycle", make_lifecycle)
    factory = Mock(side_effect=lambda: wires[factory.call_count - 1])
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", factory)
    return SimpleNamespace(
        wire=wire, wires=wires, lifecycles=lifecycles, factory=factory, backoff=backoff
    )


async def load(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert isinstance(entry.runtime_data.client, HobenClient)
    return entry.runtime_data.coordinator


def sensor(hass, entry):
    registered = next(
        e
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id == f"{entry.unique_id}_ambient_temperature"
    )
    return hass.states.get(registered.entity_id)


def assert_stopped(peers):
    for wire in peers.wires[: peers.factory.call_count]:
        wire.close.assert_awaited_once_with()
    assert all(
        owner.accepted_device_guid_for_persistence is None for owner in peers.lifecycles
    )
    assert not any(
        t.get_name() in {"hoben-v4-lifecycle", "hoben-v4-rx"} and not t.done()
        for t in asyncio.all_tasks()
    )


async def test_actual_client_reuses_tls_and_session_across_ha_refreshes(
    hass, entry, peers
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * 12)
    coordinator = await load(hass, entry)
    client = entry.runtime_data.client
    lifecycle = peers.lifecycles[0]
    for _ in range(11):
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert client._lifecycle is lifecycle
    assert lifecycle.witness.verified_read_sequence == 12
    assert lifecycle.snapshot.attempts == 1 and len(peers.lifecycles) == 1
    assert peers.factory.call_count == 1
    assert [c.args[0][0] for c in wire.write.await_args_list] == [3] + [13] * 12
    wire.close.assert_not_awaited()
    assert sensor(hass, entry).state != "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "loss",
    [
        [b"\x05", b"\x03\x0a" + RESPONSE],
        [b"\x05\x03\xff"],
        [TransportEOF("synthetic-private")],
        [TransportTlsError("synthetic-private")],
    ],
)
async def test_unavailable_until_new_generation_and_valid_read(
    hass, entry, peers, loss, caplog
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], loss])
    second = peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    previous = coordinator.data
    lifecycle = peers.lifecycles[0]
    await coordinator.async_refresh()
    await peers.backoff.entered.get()
    assert not coordinator.last_update_success and coordinator.data is previous
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert sensor(hass, entry).state == "unavailable"
    report = await async_get_config_entry_diagnostics(hass, entry)
    if loss[0] == b"\x05" or loss[0] == b"\x05\x03\xff":
        assert report["coordinator"]["last_error"]["subcode"] == 3
        assert report["client"]["close_client_subcode"] == 3
        assert lifecycle.witness.lost_generation is None  # Close is not EOF.
    else:
        assert "subcode" not in report["coordinator"]["last_error"]
    first.close.assert_awaited_once_with()
    peers.backoff.release.put_nowait(None)
    await lifecycle.wait_connected()
    assert lifecycle.witness.established_generation == 2
    assert lifecycle.witness.verified_read_generation is None
    assert not coordinator.last_update_success  # An opening is not availability.
    await coordinator.async_refresh()
    assert (
        coordinator.last_update_success and sensor(hass, entry).state != "unavailable"
    )
    assert lifecycle.witness.verified_read_generation == 2
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert second.write.await_args_list[0].args[0][37:69] == DEVICE_GUID.encode()
    assert (
        entry.runtime_data.client._lifecycle is lifecycle and len(peers.lifecycles) == 1
    )
    assert all(
        c.args[0][0] in {3, 11, 13}
        for w in (first, second)
        for c in w.write.await_args_list
    )
    assert_private_values_absent(repr(report) + caplog.text)
    assert "synthetic-private" not in caplog.text
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_first_read_error_persists_identity_and_can_cancel_setup(
    hass, entry, peers, caplog
):
    peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE[:1] + b"\x00\x00" + RESPONSE[3:]]])
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    assert await peers.backoff.entered.get() == 60.0
    assert entry.data[CONF_DEVICE_GUID] == ROTATED_DEVICE_GUID
    assert entry.data["future_setting"] == "retained"
    setup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await setup
    assert not hasattr(entry, "runtime_data")
    assert_stopped(peers)
    assert_private_values_absent(caplog.text)


async def test_repeated_losses_keep_same_lifecycle_until_explicit_reload(
    hass, entry, peers
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], [b"\x05\x03"]])
    second = peers.wire(ROTATED_DEVICE_GUID, [[b"\x05\x03"]])
    peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    peers.wire(ROTATED_DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    lifecycle = peers.lifecycles[0]
    for attempt in (1, 2):
        await coordinator.async_refresh()
        assert await peers.backoff.entered.get() == 60.0
        peers.backoff.release.put_nowait(None)
        await lifecycle.wait_connected()
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert peers.factory.call_count == 3 and len(peers.lifecycles) == 1
    first.close.assert_awaited_once_with()
    second.close.assert_awaited_once_with()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.last_update_success
    assert len(peers.lifecycles) == 2 and peers.factory.call_count == 4
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("phase", ["tx", "rx", "backoff"])
async def test_unload_cancels_actual_io_and_recovery(hass, entry, peers, phase):
    wire = peers.wire(
        DEVICE_GUID, [[RESPONSE], [] if phase != "backoff" else [b"\x05\x03"]]
    )
    coordinator = await load(hass, entry)
    waiting = asyncio.Event()
    if phase == "tx":
        previous = wire.write.side_effect

        async def blocked(packet):
            previous(packet)
            if packet[0] == 13:
                waiting.set()
                await asyncio.Future()

        wire.write.side_effect = blocked
    task = asyncio.create_task(coordinator.async_refresh())
    if phase == "backoff":
        await task
        await peers.backoff.entered.get()
    elif phase == "tx":
        await waiting.wait()
    else:
        while wire.write.await_count < 3:
            await asyncio.sleep(0)
    assert await hass.config_entries.async_unload(entry.entry_id)
    if phase != "backoff":
        with pytest.raises(asyncio.CancelledError):
            await task
    assert peers.factory.call_count == 1
    assert_stopped(peers)


@pytest.mark.parametrize("value", [0, 255, True, -1, 256, "PRIVATE_PAYLOAD"])
async def test_close_subcode_publication_is_strict_uint8(
    hass, entry, peers, monkeypatch, value
):
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    await load(hass, entry)
    client = entry.runtime_data.client
    report = client.safe_report()
    monkeypatch.setattr(
        client, "safe_report", lambda: report | {"close_client_subcode": value}
    )
    exported = await async_get_config_entry_diagnostics(hass, entry)
    if type(value) is int and 0 <= value <= 255:
        assert exported["client"]["close_client_subcode"] == value
    else:
        assert "close_client_subcode" not in exported["client"]
    assert_private_values_absent(repr(exported))
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
