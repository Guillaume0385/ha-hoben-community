"""B7: real HA entities and session owner; only transport/clock are synthetic."""

import asyncio
from datetime import timedelta

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from custom_components.hoben import coordinator as coordinator_module
from custom_components.hoben.client import HobenClient
from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportError,
    TransportTimeout,
)
from custom_components.hoben.v4_state import V4DecodeError
from ha_tests.test_cleanup_b6 import timeout_on
from ha_tests.test_cleanup_b6 import tls_peers as tls_peers  # noqa: F401
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from ha_tests.test_snapshot_continuity import states
from tests.test_data_updated_silence import pump


class LocalClock:
    """Monotone deadline and UTC advance independently of network/polling."""

    def __init__(self, monkeypatch, freezer):
        self.now, self.timers, self.freezer = 0.0, [], freezer
        monkeypatch.setattr(
            coordinator_module, "monotonic", lambda: self.now, raising=False
        )
        monkeypatch.setattr(
            coordinator_module, "async_call_later", self.schedule, raising=False
        )

    def schedule(self, _hass, delay, action):
        row = [self.now + delay, action, False]
        self.timers.append(row)
        return lambda: row.__setitem__(2, True)

    async def advance(self, seconds):
        self.now += seconds
        self.freezer.tick(timedelta(seconds=seconds))
        for row in list(self.timers):
            if not row[2] and row[0] <= self.now:
                row[2] = True
                row[1](None)
        await pump()


@pytest.mark.parametrize("failure", [TransportEOF, TransportTimeout, "close_client"])
async def test_hold_until_exactly_300_from_loss_and_expire_without_poll(
    hass, entry, peers, monkeypatch, freezer, failure
):
    clock = LocalClock(monkeypatch, freezer)
    fault = (
        [b"\x05", b"\x03"]
        if failure == "close_client"
        else [failure("PRIVATE_PAYLOAD")]
    )
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], fault])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()  # Expiry must work with no HA poll.
    before, stamp = states(hass, entry), coordinator.last_successful_read_at
    await clock.advance(120)  # Old measurement age is not outage duration.
    await coordinator.async_refresh()
    assert await peers.backoff.entered.get() == 60
    assert not coordinator.last_update_success
    assert coordinator.last_successful_read_at == stamp
    assert session_state(hass, entry).state == "reconnecting"
    assert all(states(hass, entry)[key] is value for key, value in before.items())
    await clock.advance(299)
    assert coordinator.snapshot_available and coordinator.last_snapshot_held
    assert all(states(hass, entry)[key] is value for key, value in before.items())
    await clock.advance(1)
    assert not coordinator.snapshot_available
    assert all(value.state == "unavailable" for value in states(hass, entry).values())
    assert coordinator.last_successful_read_at == stamp
    assert wire.write.await_count == 3 and peers.factory.call_count == 1
    await clock.advance(1)
    assert not coordinator.snapshot_available
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_idle_eof_starts_deadline_before_next_poll_and_keeps_actual_age(
    hass, entry, peers, monkeypatch, freezer, caplog
):
    clock = LocalClock(monkeypatch, freezer)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    before, stamp = states(hass, entry), coordinator.last_successful_read_at
    assert any(s.state == "unknown" for s in before.values())
    await clock.advance(100)
    wire.queue.put_nowait(TransportEOF("PRIVATE_PAYLOAD"))
    assert await peers.backoff.entered.get() == 60
    await pump()
    for elapsed in (0, 60, 120, 180, 299):
        await clock.advance(100 + elapsed - clock.now)
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert not coordinator.last_update_success and coordinator.snapshot_available
        assert all(states(hass, entry)[k] is s for k, s in before.items())
        report = await async_get_config_entry_diagnostics(hass, entry)
        assert report["coordinator"]["last_successful_read_age"] == 100 + elapsed
        assert coordinator.last_successful_read_at == stamp
        assert_private_values_absent(repr(report) + caplog.text)
    await clock.advance(1)
    assert not coordinator.snapshot_available
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert wire.write.await_count == 2 and peers.factory.call_count == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_double_reconnect_and_failed_polls_cannot_renew_grace_without_read(
    hass, entry, peers, monkeypatch, freezer
):
    clock = LocalClock(monkeypatch, freezer)
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    second = peers.wire(DEVICE_GUID, [])
    third = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    before, stamp = states(hass, entry), coordinator.last_successful_read_at
    first.queue.put_nowait(TransportEOF())
    assert await peers.backoff.entered.get() == 60
    await clock.advance(60)
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    assert coordinator.snapshot_available
    second.queue.put_nowait(TransportEOF())
    assert await peers.backoff.entered.get() == 60
    await clock.advance(60)
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    assert coordinator.last_successful_read_at == stamp
    assert coordinator.client.session_observation.read_generation is None
    await clock.advance(179)
    assert coordinator.snapshot_available
    assert all(states(hass, entry)[k] is s for k, s in before.items())
    await clock.advance(1)
    assert not coordinator.snapshot_available
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    await coordinator.async_refresh()
    coordinator._async_unsub_refresh()
    assert (
        coordinator.last_update_success and coordinator.last_successful_read_at > stamp
    )
    assert coordinator.client.session_observation.read_generation == 3
    assert all(s.state != "unavailable" for s in states(hass, entry).values())
    third.queue.put_nowait(TransportEOF())
    assert await peers.backoff.entered.get() == 60
    await clock.advance(299)
    assert coordinator.snapshot_available  # Only this real read started a new grace.
    await clock.advance(1)
    assert not coordinator.snapshot_available
    assert peers.factory.call_count == 3 and peers.backoff.delays == [60, 60, 60]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "failure", [TransportEOF(), TransportTimeout("read"), b"\x05\x03"]
)
async def test_no_prior_decoded_read_never_holds_or_schedules_a_ui_grace(
    hass, entry, peers, monkeypatch, freezer, failure
):
    clock = LocalClock(monkeypatch, freezer)
    peers.wire(DEVICE_GUID, [[failure]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    coordinator = coordinator_module.HobenDataUpdateCoordinator(hass, entry, client)
    try:
        await coordinator.async_refresh()
        assert await peers.backoff.entered.get() == 60
        assert coordinator.data is None and coordinator.last_successful_read_at is None
        assert not coordinator.snapshot_available and not clock.timers
        await clock.advance(301)
        assert not coordinator.snapshot_available
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
        assert_stopped(peers)


@pytest.mark.parametrize(
    "failure", ["auth", "certificate", "internal", "cleanup", "unknown_open"]
)
async def test_terminal_failure_revokes_immediately_without_poll(
    hass, entry, peers, monkeypatch, freezer, failure
):
    LocalClock(monkeypatch, freezer)
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at
    if failure == "unknown_open":
        from tests.tls_script import script_transport

        second = peers.wire(DEVICE_GUID, [])
        second.queue = script_transport(second, openings=[[b"\x05\x09"]])
        first.queue.put_nowait(TransportEOF())
        assert await peers.backoff.entered.get() == 60
        peers.backoff.release.put_nowait(None)
    elif failure == "cleanup":
        first.close.side_effect = TransportError("PRIVATE_PAYLOAD")
        first.queue.put_nowait(TransportEOF())
    elif failure == "auth":
        first.queue.put_nowait(b"\x05\x02")
    else:
        first.queue.put_nowait(
            TransportCertificateError("PRIVATE_PAYLOAD")
            if failure == "certificate"
            else RuntimeError("PRIVATE_PAYLOAD")
        )
    await pump()
    assert not coordinator.snapshot_available
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert session_state(hass, entry).state == "disconnected"
    assert coordinator.last_successful_read_at == stamp
    assert peers.factory.call_count == (2 if failure == "unknown_open" else 1)
    assert peers.backoff.delays == ([60] if failure == "unknown_open" else [])
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_cancelled_read_revokes_and_closes_without_refreshing_old_values(
    hass, entry, peers, monkeypatch, freezer
):
    clock = LocalClock(monkeypatch, freezer)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp, previous = coordinator.last_successful_read_at, coordinator.data
    refresh = asyncio.create_task(coordinator.async_refresh())
    await pump()
    assert wire.write.await_count == 3
    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh
    assert not coordinator.snapshot_available and not coordinator.last_update_success
    assert coordinator.last_successful_read_at == stamp and coordinator.data is previous
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    await clock.advance(301)
    assert peers.factory.call_count == 1 and all(row[2] for row in clock.timers)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("stop", ["client", "shutdown", "unload", "ha_stop"])
async def test_stop_cancels_expiry_and_late_timer_never_publishes_values(
    hass, entry, peers, monkeypatch, freezer, stop
):
    clock = LocalClock(monkeypatch, freezer)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    wire.queue.put_nowait(TransportEOF())
    assert await peers.backoff.entered.get() == 60
    callback = next(row[1] for row in clock.timers if not row[2])
    if stop == "client":
        await coordinator.client.async_close()
    elif stop == "shutdown":
        await coordinator.async_shutdown()
    elif stop == "ha_stop":
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()
    else:
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert not coordinator.snapshot_available
    before = states(hass, entry)
    callback(None)  # Callback already queued at cancellation boundary.
    await clock.advance(301)
    assert not coordinator.snapshot_available
    assert all(states(hass, entry)[k] is s for k, s in before.items())
    assert all(row[2] for row in clock.timers)
    if stop != "unload":
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_read_reset_rejects_a_stale_timer_even_after_another_loss(
    hass, entry, peers, monkeypatch, freezer
):
    clock = LocalClock(monkeypatch, freezer)
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    second = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    first.queue.put_nowait(TransportEOF())
    assert await peers.backoff.entered.get() == 60
    old_callback = next(row[1] for row in clock.timers if not row[2])
    await clock.advance(60)
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    await coordinator.async_refresh()
    coordinator._async_unsub_refresh()
    second.queue.put_nowait(TransportEOF())
    assert await peers.backoff.entered.get() == 60
    before = sum(not row[2] for row in clock.timers)
    old_callback(None)
    assert sum(not row[2] for row in clock.timers) == before == 1
    await clock.advance(299)
    assert coordinator.snapshot_available
    await clock.advance(1)
    assert not coordinator.snapshot_available
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_decoding_rejection_and_utc_jump_cannot_reset_monotone_deadline(
    hass, entry, peers, monkeypatch, freezer
):
    clock = LocalClock(monkeypatch, freezer)
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    before, stamp = states(hass, entry), coordinator.last_successful_read_at
    first.queue.put_nowait(TransportEOF())
    assert await peers.backoff.entered.get() == 60
    await clock.advance(60)
    peers.backoff.release.put_nowait(None)
    await peers.lifecycles[0].wait_connected()
    with monkeypatch.context() as decoder:

        def reject(_snapshot):
            raise V4DecodeError()

        decoder.setattr(coordinator_module, "decode_v4_snapshot", reject)
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
    assert not coordinator.last_update_success
    assert coordinator.last_successful_read_at == stamp
    assert coordinator.client.session_observation.read_generation == 2
    assert all(states(hass, entry)[k] is s for k, s in before.items())
    freezer.tick(timedelta(days=1))  # Wall time neither expires nor renews grace.
    assert coordinator.snapshot_available
    row = next(row for row in clock.timers if not row[2])
    row[2] = True
    row[1](None)  # An early callback must rearm only the remaining monotone time.
    assert sum(not row[2] for row in clock.timers) == 1
    freezer.tick(timedelta(days=-2))
    await clock.advance(239.999)
    assert coordinator.snapshot_available
    await clock.advance(0.001)
    assert not coordinator.snapshot_available
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert coordinator.last_successful_read_at == stamp
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("failed_close", [False, True])
async def test_b6_pending_tls_close_is_not_cleanup_proof(
    hass, entry, tls_peers, freezer, failed_close
):
    wire = tls_peers.wire([[RESPONSE], []])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    before, stamp = states(hass, entry), coordinator.last_successful_read_at
    owner = tls_peers.owners[0]._session
    finished = asyncio.Event()

    async def wait_closed():
        await finished.wait()
        if failed_close:
            raise OSError("PRIVATE_PAYLOAD")

    wire.writer.wait_closed.side_effect = wait_closed
    refresh = await timeout_on(coordinator, wire, owner, freezer, "read")
    try:
        assert not owner.cleanup_succeeded and not coordinator.snapshot_available
        assert not tls_peers.waits and len(tls_peers.transports) == 1
        assert coordinator.last_successful_read_at == stamp
        finished.set()
        await refresh
        await pump()
        assert owner.cleanup_succeeded is (not failed_close)
        assert coordinator.snapshot_available is (not failed_close)
        if failed_close:
            assert all(s.state == "unavailable" for s in states(hass, entry).values())
            assert (
                session_state(hass, entry).attributes["last_error_category"]
                == "cleanup_failed"
            )
            assert not tls_peers.waits
        else:
            assert all(states(hass, entry)[k] is s for k, s in before.items())
            assert tls_peers.waits == [60]
        assert len(tls_peers.transports) == 1
    finally:
        finished.set()
        await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
