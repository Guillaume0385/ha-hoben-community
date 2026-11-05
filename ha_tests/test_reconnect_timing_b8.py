"""Production HA B8, real client/coordinator/owners over synthetic TLS and time."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed_exact

from custom_components.hoben import coordinator as coordinator_module
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTlsError,
)
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from ha_tests.test_cleanup_b6 import tls_peers as tls_peers  # noqa: F401
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from ha_tests.test_snapshot_continuity import states
from tests.test_data_updated_silence import pump
from tests.test_ha_reconnect_policy import Clock


@pytest.fixture
def timeline(hass, peers, monkeypatch, freezer):
    clock = Clock()
    original_advance = clock.advance

    async def advance(seconds):
        freezer.tick(seconds)
        if clock.timer is None:
            clock.now += seconds
        else:
            await original_advance(seconds)
        async_fire_time_changed_exact(hass, dt_util.utcnow())
        await pump()

    clock.advance = advance

    def factory(**options):
        life = V4Lifecycle(
            **(options | {"sleep": clock.sleep, "clock": lambda: clock.now})
        )
        peers.lifecycles.append(life)
        return life

    monkeypatch.setattr("custom_components.hoben.v4_lifecycle.V4Lifecycle", factory)
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock.now)
    return clock


@pytest.mark.parametrize("fault", [TransportEOF(), b"", b"\x05\x03", b"\x05\x06"])
async def test_real_ha_cleanup_then_10_tls_then_10_new_read(
    hass, entry, peers, timeline, fault, caplog
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    previous, stamp = states(hass, entry), coordinator.last_successful_read_at
    first.queue.put_nowait(fault)
    assert await timeline.waiting.get() == 10
    assert coordinator.client.session_observation.cleaned_generation == 1
    await timeline.advance(9.999)
    assert peers.factory.call_count == 1
    await timeline.advance(0.0011)
    assert await timeline.waiting.get() == 10
    assert peers.factory.call_count == 2 and fresh.write.await_count == 1
    assert session_state(hass, entry).state == "connected"
    assert (
        not coordinator.last_update_success
        and coordinator.last_successful_read_at == stamp
    )
    assert all(states(hass, entry)[k] is v for k, v in previous.items())
    await timeline.advance(9.999)
    assert fresh.write.await_count == 1
    await timeline.advance(0.0011)
    await pump()
    assert fresh.write.await_count == 2
    assert (
        coordinator.last_update_success and coordinator.last_successful_read_at > stamp
    )
    assert coordinator.client.session_observation.read_generation == 2
    assert coordinator.client.session_observation.read_sequence == 1
    assert_private_values_absent(repr(coordinator.client.safe_report()) + caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_actual_acquisition_timeout_recovers_at_30_without_periodic_poll(
    hass, entry, peers, timeline
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at
    refresh = asyncio.create_task(coordinator.async_refresh())
    await pump()
    assert first.write.await_count == 3
    await timeline.advance(30)
    await refresh
    assert await timeline.waiting.get() == 30
    assert not coordinator.last_update_success
    await timeline.advance(29.999)
    assert (
        peers.factory.call_count == 1 and coordinator.last_successful_read_at == stamp
    )
    await timeline.advance(0.0011)
    await pump()
    assert peers.factory.call_count == 2 and fresh.write.await_count == 2
    assert (
        coordinator.last_update_success and coordinator.last_successful_read_at > stamp
    )
    assert first.write.await_count == 3  # No replay on the old stream.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "fault", [TransportError(), TransportTlsError(), b"\xff", b"\x05\x09"]
)
async def test_conservative_class_waits_60_and_does_not_invent_fast_acquisition(
    hass, entry, peers, timeline, fault
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at
    first.queue.put_nowait(fault)
    assert await timeline.waiting.get() == 60
    await timeline.advance(59.999)
    assert peers.factory.call_count == 1
    await timeline.advance(0.0011)
    await peers.lifecycles[0].wait_connected()
    await pump()
    assert fresh.write.await_count == 1 and coordinator.last_successful_read_at == stamp
    assert not coordinator.last_update_success
    await coordinator.async_refresh()
    assert fresh.write.await_count == 2 and coordinator.last_update_success
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("during", ["backoff", "accepted", "read"])
async def test_unload_owns_pending_recovery_acquisition_and_no_late_tx(
    hass, entry, peers, timeline, during
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    peers.wire(DEVICE_GUID, [[]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    first.queue.put_nowait(TransportEOF())
    assert await timeline.waiting.get() == 10
    if during != "backoff":
        await timeline.advance(10)
        assert await timeline.waiting.get() == 10
    if during == "read":
        await timeline.advance(10)
        await pump()
        assert coordinator._recovery_read_task is not None
    writes = sum(w.write.await_count for w in peers.wires)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await timeline.advance(1000)
    assert sum(w.write.await_count for w in peers.wires) == writes
    assert_stopped(peers)
    assert not any(
        t.get_name() == "hoben-recovery-acquisition" and not t.done()
        for t in asyncio.all_tasks()
    )


@pytest.mark.parametrize("code", [2, 4, 5])
async def test_auth_closes_without_retry_or_held_availability(
    hass, entry, peers, timeline, code
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at
    first.queue.put_nowait(bytes([5, code]))
    await pump()
    assert peers.lifecycles[0]._task.done()
    assert not coordinator.snapshot_available
    assert timeline.waiting.empty() and peers.factory.call_count == 1
    assert coordinator.last_successful_read_at == stamp
    await timeline.advance(301)
    assert peers.factory.call_count == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_partial_close_then_eof_is_ambiguous_and_keeps_60(
    hass, entry, peers, timeline
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    first.queue.put_nowait(b"\x05")
    first.queue.put_nowait(TransportEOF())
    assert await timeline.waiting.get() == 60
    assert coordinator.client.session_observation.close_client_subcode is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_three_proven_losses_have_one_owner_and_a_fresh_read_each_time(
    hass, entry, peers, timeline
):
    wires = [peers.wire(DEVICE_GUID, [[RESPONSE]]) for _ in range(4)]
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    owner = peers.lifecycles[0]
    for index, fault in enumerate([TransportEOF(), b"\x05\x03", b"\x05\x06"]):
        stamp = coordinator.last_successful_read_at
        wires[index].queue.put_nowait(fault)
        assert await timeline.waiting.get() == 10
        assert coordinator.snapshot_available
        assert not coordinator.last_update_success
        assert coordinator.client.session_observation.cleaned_generation == index + 1
        await timeline.advance(10)
        assert await timeline.waiting.get() == 10
        assert coordinator.last_successful_read_at == stamp
        await timeline.advance(10)
        assert coordinator.last_successful_read_at > stamp
        assert coordinator.client.session_observation.read_generation == index + 2
        assert coordinator.client.session_observation.read_sequence == 1
        assert wires[index + 1].write.await_count == 2
        assert len(peers.lifecycles) == 1 and peers.lifecycles[0] is owner
        assert session_state(hass, entry).attributes["reconnect_count"] == index + 1
        coordinator._async_unsub_refresh()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_poll_waiting_for_post_open_gate_coalesces_with_ready_event(
    hass, entry, peers, timeline
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    first.queue.put_nowait(TransportEOF())
    assert await timeline.waiting.get() == 10
    await timeline.advance(10)
    assert await timeline.waiting.get() == 10
    poll = asyncio.create_task(coordinator.async_refresh())
    await pump()
    assert not poll.done() and fresh.write.await_count == 1
    await timeline.advance(10)
    await poll
    await pump()
    assert fresh.write.await_count == 2
    assert coordinator.client.session_observation.read_sequence == 1
    assert coordinator.last_update_success
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_losses_before_acquisition_do_not_renew_b7_300_second_grace(
    hass, entry, peers, timeline
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    second = peers.wire(DEVICE_GUID, [])
    third = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp, previous = coordinator.last_successful_read_at, states(hass, entry)
    first.queue.put_nowait(TransportEOF())
    assert await timeline.waiting.get() == 10
    await timeline.advance(10)
    assert await timeline.waiting.get() == 10
    # Generic next loss during the post-open delay cancels the fast read.
    second.queue.put_nowait(TransportError())
    assert await timeline.waiting.get() == 60
    await timeline.advance(60)
    await pump()
    assert third.write.await_count == 1
    await timeline.advance(229)
    assert timeline.now == 299
    assert coordinator.snapshot_available
    assert coordinator.last_successful_read_at == stamp
    assert all(states(hass, entry)[k] is s for k, s in previous.items())
    await timeline.advance(1)
    assert not coordinator.snapshot_available
    assert all(s.state == "unavailable" for s in states(hass, entry).values())
    assert coordinator.last_successful_read_at == stamp
    # A genuine decoded read restores availability and is the only renewal.
    await coordinator.async_refresh()
    assert coordinator.last_update_success and coordinator.snapshot_available
    assert coordinator.last_successful_read_at > stamp
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.fixture
def tls_timeline(hass, tls_peers, monkeypatch, freezer):
    clock = Clock()
    original_advance = clock.advance

    async def advance(seconds):
        freezer.tick(seconds)
        if clock.timer is None:
            clock.now += seconds
        else:
            await original_advance(seconds)
        async_fire_time_changed_exact(hass, dt_util.utcnow())
        await pump()

    clock.advance = advance

    def factory(**options):
        result = V4Lifecycle(
            **(options | {"sleep": clock.sleep, "clock": lambda: clock.now})
        )
        tls_peers.owners.append(result)
        return result

    monkeypatch.setattr("custom_components.hoben.v4_lifecycle.V4Lifecycle", factory)
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock.now)
    return clock


@pytest.mark.parametrize("double_close", [False, True])
async def test_real_tls_wait_closed_proof_precedes_timeout_deadline_and_new_read(
    hass, entry, tls_peers, tls_timeline, double_close, caplog
):
    first = tls_peers.wire([[RESPONSE], []])
    fresh = tls_peers.wire([[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    life, stamp = tls_peers.owners[0], coordinator.last_successful_read_at
    session = life._session
    entered, release = asyncio.Event(), asyncio.Event()

    async def closing():
        entered.set()
        await release.wait()

    first.writer.wait_closed.side_effect = closing
    refresh = asyncio.create_task(coordinator.async_refresh())
    await pump()
    await tls_timeline.advance(30)
    assert entered.is_set() and not session.cleanup_succeeded
    assert len(tls_peers.transports) == 1 and tls_timeline.waiting.empty()
    closers = (
        [asyncio.create_task(session.close()), asyncio.create_task(session.abort())]
        if double_close
        else []
    )
    await tls_timeline.advance(3)
    release.set()
    await refresh
    await asyncio.gather(*closers)
    assert await tls_timeline.waiting.get() == 27
    assert session.cleanup_succeeded and session._rx_task.done()
    assert not session._operations and not session._tx_operations
    assert coordinator.client.session_observation.cleaned_generation == 1
    assert coordinator.last_successful_read_at == stamp
    await tls_timeline.advance(26.999)
    assert len(tls_peers.transports) == 1
    await tls_timeline.advance(0.0011)
    await life.wait_connected()  # Real certificate context executor also finishes.
    await hass.async_block_till_done()
    await pump()
    assert len(tls_peers.transports) == 2 and fresh.writer.write.call_count == 2
    assert (
        coordinator.last_update_success and coordinator.last_successful_read_at > stamp
    )
    assert coordinator.client.session_observation.read_sequence == 1
    assert_private_values_absent(caplog.text + repr(coordinator.client.safe_report()))
    assert await hass.config_entries.async_unload(entry.entry_id)
    first.writer.close.assert_called_once_with()
    first.writer.wait_closed.assert_awaited_once_with()
    first.writer.transport.abort.assert_not_called()


@pytest.mark.parametrize("fault", ["wait_error", "cancel", "timeout"])
async def test_real_tls_failed_cleanup_never_retries_despite_proven_timeout(
    hass, entry, tls_peers, tls_timeline, fault, caplog
):
    first = tls_peers.wire([[RESPONSE], []])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp, life = coordinator.last_successful_read_at, tls_peers.owners[0]
    old = life._session

    async def closing():
        if fault == "wait_error":
            raise OSError("PRIVATE_PAYLOAD")
        if fault == "cancel":
            raise asyncio.CancelledError()
        await asyncio.Future()

    first.writer.wait_closed.side_effect = closing
    refresh = asyncio.create_task(coordinator.async_refresh())
    await pump()
    await tls_timeline.advance(30)
    if fault == "timeout":
        await tls_timeline.advance(5.001)
    await asyncio.gather(refresh, return_exceptions=True)
    await pump()
    assert old._rx_error.code == "timeout" and life._failure.code == "cleanup_failed"
    assert coordinator.client.session_observation.cleanup_failed
    assert not old.cleanup_succeeded and life._task.done()
    assert (
        not coordinator.snapshot_available
        and coordinator.last_successful_read_at == stamp
    )
    await tls_timeline.advance(301)
    assert tls_timeline.waiting.empty() and len(tls_peers.transports) == 1
    assert_private_values_absent(caplog.text + repr(coordinator.client.safe_report()))
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_first_read_failure_has_no_held_values_and_setup_uses_one_fresh_read(
    hass, entry, peers, timeline
):
    peers.wire(DEVICE_GUID, [[TransportEOF()]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    setup = asyncio.create_task(load(hass, entry))
    assert await timeline.waiting.get() == 10
    assert not setup.done()
    await timeline.advance(10)
    assert await timeline.waiting.get() == 10
    assert fresh.write.await_count == 1
    await timeline.advance(10)
    coordinator = await setup
    await pump()
    assert coordinator.last_update_success
    assert fresh.write.await_count == 2
    assert coordinator.client.session_observation.read_sequence == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_post_open_gate_keeps_ping_pong_live_without_early_v4(
    hass, entry, peers, timeline
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at
    # Complete fragmented CloseClient is sufficient; no TLS chunk is a boundary.
    first.queue.put_nowait(b"\x05")
    first.queue.put_nowait(b"\x03")
    assert await timeline.waiting.get() == 10
    await timeline.advance(10)
    assert await timeline.waiting.get() == 10
    fresh.queue.put_nowait(b"\x0a\x0a")
    await pump()
    assert [c.args[0][0] for c in fresh.write.await_args_list] == [3, 11, 11]
    assert coordinator.last_successful_read_at == stamp
    assert not coordinator.last_update_success
    await timeline.advance(10)
    assert [c.args[0][0] for c in fresh.write.await_args_list] == [3, 11, 11, 13]
    assert coordinator.last_update_success
    assert coordinator.client.session_observation.read_sequence == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_fast_entry_preserves_dataupdated_sliding_silence_and_one_probe(
    hass, entry, peers, timeline, caplog
):
    from tests.test_data_updated_silence import BAD

    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at
    wire.queue.put_nowait(BAD)
    await pump()
    await timeline.advance(29)
    wire.queue.put_nowait(b"\xff" * 4096)
    await pump()
    await timeline.advance(29)
    assert wire.write.await_count == 2 and peers.factory.call_count == 1
    wire.close.assert_not_awaited()
    assert timeline.waiting.empty()
    await timeline.advance(1)
    assert wire.write.await_count == 3 and peers.factory.call_count == 1
    assert coordinator.last_successful_read_at == stamp
    await coordinator.async_refresh()  # Consume the one correlated probe result.
    assert wire.write.await_count == 3
    assert (
        coordinator.last_update_success and coordinator.last_successful_read_at > stamp
    )
    assert_private_values_absent(caplog.text + repr(coordinator.client.safe_report()))
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("pending_read", [False, True])
async def test_pong_timeout_is_not_proof_of_an_expired_acquisition_deadline(
    hass, entry, tls_peers, tls_timeline, pending_read
):
    first = tls_peers.wire([[RESPONSE], []])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at

    async def drain():
        if first.writer.write.call_args.args[0][0] == 11:
            await asyncio.Future()

    first.writer.drain.side_effect = drain
    refresh = asyncio.create_task(coordinator.async_refresh()) if pending_read else None
    await pump()
    first.queue.put_nowait(b"\x0a")
    await pump()
    await tls_timeline.advance(10)
    if refresh is not None:
        await refresh
    assert await tls_timeline.waiting.get() == 60
    assert coordinator.last_successful_read_at == stamp
    assert len(tls_peers.transports) == 1
    assert coordinator.client.session_observation.cleaned_generation == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("fault", "delay"),
    [
        (TransportEOF(), 10),
        (b"\x05\x06", 10),
        (TransportError(), 60),
        (b"\x05\x05", None),
    ],
)
async def test_actual_loss_at_three_seconds_interrupts_post_open_gate_immediately(
    hass, entry, peers, timeline, fault, delay
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    rejected = peers.wire(DEVICE_GUID, [])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    stamp = coordinator.last_successful_read_at
    life = peers.lifecycles[0]
    first.queue.put_nowait(TransportEOF())
    assert await timeline.waiting.get() == 10
    await timeline.advance(10)
    assert await timeline.waiting.get() == 10
    post_open_timer = timeline.timer[1]
    await timeline.advance(3)
    rejected.queue.put_nowait(fault)
    await pump()
    # The real wait_lost raises its typed error; no remaining seven-second wait.
    assert post_open_timer.cancelled()
    assert coordinator.client.session_observation.cleaned_generation == 2
    assert life.ha_acquisition_generation is None
    assert coordinator.client.session_observation.read_generation is None
    assert coordinator.last_successful_read_at == stamp
    assert not coordinator.last_update_success
    assert [c.args[0][0] for c in rejected.write.await_args_list] == [3]
    assert peers.factory.call_count == 2
    if delay is None:
        assert life._task.done() and timeline.waiting.empty()
        assert not coordinator.snapshot_available
        await timeline.advance(100)
        assert peers.factory.call_count == 2
    else:
        assert await timeline.waiting.get() == delay
        assert timeline.timer[0] == 13 + delay
        await timeline.advance(delay - 0.001)
        assert peers.factory.call_count == 2
        await timeline.advance(0.0011)
        if delay == 10:
            assert await timeline.waiting.get() == 10
            assert fresh.write.await_count == 1
            await timeline.advance(10)
            assert fresh.write.await_count == 2 and coordinator.last_update_success
        else:
            assert fresh.write.await_count == 1
            assert not coordinator.last_update_success
        assert peers.factory.call_count == 3 and len(peers.lifecycles) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
