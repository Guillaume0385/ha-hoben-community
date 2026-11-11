"""B9: real HA owners and TLS wrapper, synthetic streams and shutdown witness."""

import asyncio

import pytest
from conftest import assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.safe_reports import safe_error_report
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from ha_tests.test_cleanup_b6 import timeout_on
from ha_tests.test_cleanup_b6 import tls_peers as tls_peers  # noqa: F401
from ha_tests.test_persistent_client import RESPONSE, load, sensor
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import pump
from tests.test_frame_logging import records
from tests.test_tls_cleanup_b9 import connected


async def test_malformed_mbap_with_real_asyncio_close_witness_recovers_after_ack(
    hass, entry, tls_peers, freezer
):
    first = tls_peers.wire([[RESPONSE], []])
    tls_peers.wire([[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    life, client = tls_peers.owners[0], coordinator.client
    session = life._session
    sdk, wire, closed = connected()
    # Preserve the real SDK close future and connection_lost callback. Only
    # application I/O is scripted; this wire never owns a socket.
    first.writer.close.side_effect = sdk._writer.close
    first.writer.wait_closed.side_effect = sdk._writer.wait_closed
    first.writer.transport.abort.side_effect = wire.abort
    refresh = asyncio.create_task(coordinator.async_refresh())
    try:
        await pump()
        first.queue.put_nowait(b"\x0e\xff\xff\x00\x00\xff\xff")
        await pump()
        for _ in range(5):
            freezer.tick(1.001)
            await pump()
        await refresh
        coordinator._async_unsub_refresh()
        assert wire.closed and wire.aborts == 1 and not closed.cancelled()
        assert session.cleanup_succeeded and session._rx_task.done()
        assert tls_peers.waits == [60]
        assert not client.session_observation.cleanup_failed
        assert len(tls_peers.transports) == 1
        freezer.tick(58)
        await pump()
        assert len(tls_peers.transports) == 1
        freezer.tick(1.001)
        await pump()
        await life.wait_connected()
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert client.session_observation.read_generation == 2
        assert client.session_observation.read_sequence == 1
        assert coordinator.last_update_success
    finally:
        wire.ack()
        if not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_three_malformed_boundaries_wait_for_abort_ack_then_reconnect(
    hass, entry, tls_peers, freezer, monkeypatch, caplog
):
    # Retain the actual entry's B8 policy, unlike B6's legacy timing fixture.
    async def sleep(seconds):
        tls_peers.waits.append(seconds)
        await asyncio.sleep(seconds)

    def owner(**options):
        life = V4Lifecycle(**(options | {"sleep": sleep}))
        tls_peers.owners.append(life)
        return life

    monkeypatch.setattr("custom_components.hoben.v4_lifecycle.V4Lifecycle", owner)
    wires = [tls_peers.wire([[RESPONSE], []]) for _ in range(4)]
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client, life = coordinator.client, tls_peers.owners[0]
    assert type(client) is HobenClient and client.ha_reconnect_enabled
    supervisor = life._task
    refresh = None
    try:
        for generation, wire in enumerate(wires[:3], 1):
            session = life._session
            previous, stamp = coordinator.data, coordinator.last_successful_read_at
            closed = asyncio.get_running_loop().create_future()

            async def wait_closed():
                await closed  # Only a connection_lost acknowledgement proves close.

            wire.writer.wait_closed.side_effect = wait_closed
            refresh = asyncio.create_task(coordinator.async_refresh())
            await pump()
            assert session._pending_read is not None
            # A concatenated suffix must not become a new frame or a length.
            wire.queue.put_nowait(
                b"\x0e\xff\xff\x00\x00\xff\xff" + b"\x0a" * generation
            )
            await pump()
            assert safe_error_report(session._rx_error)["phase"] == "frame_boundary"
            assert not session.cleanup_succeeded
            assert tls_peers.waits == [60] * (generation - 1)
            assert len(tls_peers.transports) == generation
            # The existing total is five seconds. Reserve its last second for
            # an abort acknowledgement, without cancelling the original waiter.
            freezer.tick(4.001)
            await pump()
            wire.writer.transport.abort.assert_called_once_with()
            assert not closed.cancelled()
            assert not session.cleanup_succeeded
            assert len(tls_peers.transports) == generation
            assert tls_peers.waits == [60] * (generation - 1)
            freezer.tick(0.2)
            closed.set_result(None)
            await pump()
            await refresh
            coordinator._async_unsub_refresh()
            assert session.cleanup_succeeded and session._rx_task.done()
            assert not session._operations and not session._tx_operations
            assert session._pending_read is session._read_timeout is None
            assert session._data_updated.task is None
            assert client.session_observation.cleaned_generation == generation
            assert not client.session_observation.cleanup_failed
            assert life._task is supervisor and not supervisor.done()
            assert tls_peers.waits == [60] * generation
            assert len(tls_peers.transports) == generation
            assert coordinator.data is previous
            assert coordinator.last_successful_read_at == stamp
            assert not coordinator.last_update_success
            assert coordinator.last_snapshot_held
            assert sensor(hass, entry).state != "unavailable"
            state = session_state(hass, entry)
            assert state.state == "reconnecting"
            assert state.attributes["last_error_category"] == "malformed_response"
            assert state.attributes["last_error_phase"] == "frame_boundary"
            assert state.attributes["last_successful_read_age"] >= 4
            freezer.tick(59)
            await pump()
            assert len(tls_peers.transports) == generation
            freezer.tick(1.001)
            await pump()
            await life.wait_connected()
            assert len(tls_peers.transports) == generation + 1
            assert coordinator.last_successful_read_at == stamp
            assert client.session_observation.read_generation is None
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert coordinator.last_update_success and coordinator.data is not previous
            assert coordinator.last_successful_read_at > stamp
            o = client.session_observation
            assert o.read_generation == generation + 1 and o.read_sequence == 1
            assert (
                session_state(hass, entry).attributes["reconnect_count"] == generation
            )
            assert len(tls_peers.owners) == 1 and client._lifecycle is life
            wire.writer.close.assert_called_once_with()
            wire.writer.wait_closed.assert_awaited_once_with()
        assert_private_values_absent(caplog.text + repr(client.safe_report()))
        errors = records(caplog, "error")
        assert len(errors) == 3
        assert all(r["received_bytes"] == 7 for r in errors)
        assert all(r["expected_total_bytes"] == "unknown" for r in errors)
        assert all("message_type_byte" not in r for r in errors)
        assert caplog.text.count("message_type_byte=0x0C") == 0
    finally:
        if refresh is not None and not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert not any(
        t.get_name()
        in {
            "hoben-tls-close",
            "hoben-v4-rx",
            "hoben-v4-lifecycle",
            "hoben-dataupdated-probe",
        }
        for t in asyncio.all_tasks()
        if not t.done()
    )


@pytest.mark.parametrize("origin", ["probe_read", "probe_write", "pong"])
async def test_timeout_racing_with_probe_or_tx_joins_the_same_confirmed_abort(
    hass, entry, tls_peers, freezer, origin
):
    first = tls_peers.wire([[RESPONSE], []])
    tls_peers.wire([[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    life = tls_peers.owners[0]
    session = life._session
    stamp = coordinator.last_successful_read_at
    finished = asyncio.get_running_loop().create_future()

    async def wait_closed():
        await finished

    first.writer.wait_closed.side_effect = wait_closed
    refresh = None
    closers = []
    try:
        refresh = await timeout_on(coordinator, first, session, freezer, origin)
        assert session._rx_error.code == "timeout"
        closers = [
            asyncio.create_task(session.close()),
            asyncio.create_task(session.abort()),
        ]
        await pump()
        assert not any(t.done() for t in closers) and not session.cleanup_succeeded
        freezer.tick(4.001)
        await pump()
        first.writer.transport.abort.assert_called_once_with()
        assert not finished.cancelled() and not tls_peers.waits
        assert len(tls_peers.transports) == 1
        finished.set_result(None)
        await pump()
        await asyncio.gather(*closers)
        if refresh is not None:
            await refresh
        assert session.cleanup_succeeded and session._rx_task.done()
        assert not session._operations and not session._tx_operations
        assert session._data_updated.task is None and not session._data_updated.closing
        assert session._rx_error.code == "timeout"
        assert tls_peers.waits == [60]
        assert coordinator.last_successful_read_at == stamp
        freezer.tick(59)
        await pump()
        assert len(tls_peers.transports) == 1
        freezer.tick(1.001)
        await pump()
        await life.wait_connected()
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert coordinator.last_successful_read_at > stamp
        assert coordinator.client.session_observation.read_generation == 2
        assert coordinator.client.session_observation.read_sequence == 1
        first.writer.close.assert_called_once_with()
        first.writer.wait_closed.assert_awaited_once_with()
    finally:
        if not finished.done():
            finished.set_result(None)
        if refresh is not None and not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        await asyncio.gather(*closers, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "fault", ["no_ack", "wait_error", "abort_error", "cancel", "unload"]
)
async def test_malformed_boundary_with_unproven_or_cancelled_cleanup_stays_terminal(
    hass, entry, tls_peers, freezer, fault, caplog
):
    first = tls_peers.wire([[RESPONSE], []])
    tls_peers.wire([[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client, life = coordinator.client, tls_peers.owners[0]
    session = life._session
    stamp = coordinator.last_successful_read_at
    finished = asyncio.get_running_loop().create_future()

    async def wait_closed():
        if fault == "wait_error":
            raise OSError("PRIVATE_PAYLOAD")
        await finished

    first.writer.wait_closed.side_effect = wait_closed
    if fault == "abort_error":
        first.writer.transport.abort.side_effect = OSError("PRIVATE_PAYLOAD")
    refresh = asyncio.create_task(coordinator.async_refresh())
    unloaded = False
    try:
        await pump()
        first.queue.put_nowait(b"\x0e\xff\xff\x00\x00\xff\xff")
        await pump()
        assert safe_error_report(session._rx_error)["phase"] == "frame_boundary"
        if fault == "unload":
            assert await hass.config_entries.async_unload(entry.entry_id)
            unloaded = True
        elif fault == "cancel":
            session._rx_task.cancel()
            session._rx_task.cancel()  # Concurrent explicit owner cancellation.
            await pump()
        elif fault in {"no_ack", "abort_error"}:
            freezer.tick(4.001)
            await pump()
            if fault == "no_ack":
                assert not session.cleanup_succeeded and not tls_peers.waits
                freezer.tick(1.001)
                await pump()
        await asyncio.gather(refresh, return_exceptions=True)
        await pump()
        assert (
            not session.cleanup_succeeded and client.session_observation.cleanup_failed
        )
        assert life._task.done() and not tls_peers.waits
        assert len(tls_peers.transports) == 1
        assert session._rx_task.done() and not session._operations
        assert not session._tx_operations and session._pending_read is None
        assert safe_error_report(session._rx_error)["phase"] == "frame_boundary"
        if not unloaded:
            assert life._failure.code == "cleanup_failed"
            assert session_state(hass, entry).state == "disconnected"
            assert sensor(hass, entry).state == "unavailable"
        # Neither an idempotent close nor a later completion can resurrect cleanup.
        if not finished.done():
            finished.set_result(None)
        await session.close()
        assert not session.cleanup_succeeded
        freezer.tick(120)
        await pump()
        assert len(tls_peers.transports) == 1 and not tls_peers.waits
        assert coordinator.last_successful_read_at == stamp
        first.writer.transport.abort.assert_called_once_with()
        assert_private_values_absent(caplog.text + repr(client.safe_report()))
    finally:
        if not finished.done():
            finished.set_result(None)
        if not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        if not unloaded:
            assert await hass.config_entries.async_unload(entry.entry_id)
