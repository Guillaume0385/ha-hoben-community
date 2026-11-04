"""B6: real HA/client/session/TLS wrapper; only streams and time are synthetic."""

import asyncio
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.exceptions import (
    HobenInternalError,
    HobenInvalidCredentialsError,
    HobenTlsVerificationError,
)
from custom_components.hoben.safe_reports import safe_error_report
from custom_components.hoben.transport import AsyncTlsTransport
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from ha_tests.test_persistent_client import RESPONSE, load, opening
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import BAD, pump
from tests.tls_script import script_tls


@pytest.fixture
def tls_peers(monkeypatch):
    """Keep AsyncTlsTransport's connect/read/write/close and verified TLS options."""
    wires, transports, owners, waits = [], [], [], []

    def wire(reads):
        result = SimpleNamespace(
            reader=SimpleNamespace(read=AsyncMock()),
            writer=SimpleNamespace(
                write=Mock(),
                drain=AsyncMock(),
                close=Mock(),
                wait_closed=AsyncMock(),
                transport=SimpleNamespace(abort=Mock()),
            ),
        )
        result.queue = script_tls(
            result, openings=[[opening(DEVICE_GUID)]], reads=reads
        )
        wires.append(result)
        return result

    async def connect(host, port, **options):
        assert (host, port) == ("myhoben.fr", 465)
        assert options["server_hostname"] == "myhoben.fr"
        assert options["ssl"].check_hostname
        assert options["ssl"].verify_mode == ssl.CERT_REQUIRED
        result = wires[len(transports) - 1]
        if getattr(result, "connect_error", None) is not None:
            raise result.connect_error
        return result.reader, result.writer

    def transport():
        result = AsyncTlsTransport()
        transports.append(result)
        return result

    async def backoff(seconds):
        waits.append(seconds)
        await asyncio.sleep(seconds)

    def lifecycle(**options):
        result = V4Lifecycle(**(options | {"sleep": backoff}))
        owners.append(result)
        return result

    monkeypatch.setattr(asyncio, "open_connection", connect)
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", transport)
    monkeypatch.setattr("custom_components.hoben.v4_lifecycle.V4Lifecycle", lifecycle)
    return SimpleNamespace(
        wire=wire, wires=wires, transports=transports, owners=owners, waits=waits
    )


async def timeout_on(coordinator, first, session, freezer, origin):
    """Expire real deadlines; delivery batches never inspect production parsing."""
    if origin in {"probe_write", "read_write", "pong"}:

        async def drain():
            if first.writer.write.call_args.args[0][0] == (
                11 if origin == "pong" else 13
            ):
                await asyncio.Future()

        first.writer.drain.side_effect = drain
    if origin.startswith("probe"):
        first.queue.put_nowait(BAD)
        await pump()
        freezer.tick(30.001)
        await pump()
        assert session._data_updated.task is not None
        if origin == "probe_write":
            freezer.tick(10.001)
        else:
            first.queue.put_nowait(TimeoutError("PRIVATE_PAYLOAD"))
        refresh = None
    else:
        refresh = asyncio.create_task(coordinator.async_refresh())
        await pump()
        if origin == "pong":
            first.queue.put_nowait(b"\x0a")
            await pump()
        freezer.tick(30.001 if origin == "read" else 10.001)
    await pump()
    return refresh


@pytest.mark.parametrize(
    "origin", ["read", "read_write", "pong", "probe_write", "probe_read"]
)
@pytest.mark.parametrize("double_close", [False, True])
async def test_timeout_cleanup_finishes_before_backoff_and_new_tls(
    hass, entry, tls_peers, freezer, caplog, origin, double_close
):
    first = tls_peers.wire([[RESPONSE], []])
    fresh = tls_peers.wire([[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client = coordinator.client
    assert type(client) is HobenClient and client.ha_reconnect_enabled
    life = tls_peers.owners[0]
    session = life._session
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    started, finish = asyncio.Event(), asyncio.Event()
    completed, interrupted = [], []

    async def wait_closed():
        started.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            interrupted.append(True)
            raise
        completed.append(True)

    first.writer.wait_closed.side_effect = wait_closed
    refresh = None
    closers = []
    try:
        refresh = await timeout_on(coordinator, first, session, freezer, origin)
        assert started.is_set()
        assert not session.cleanup_succeeded and not tls_peers.waits
        assert len(tls_peers.transports) == 1
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        if double_close:
            closers = [
                asyncio.create_task(session.close()),
                asyncio.create_task(session.abort()),
            ]
            await pump()
            assert not any(t.done() for t in closers)
            assert not session.cleanup_succeeded and len(tls_peers.transports) == 1
        finish.set()
        await pump()
        if refresh is not None:
            await refresh
        await asyncio.gather(*closers)
        assert not interrupted, "lifecycle interrupted the original RX close"
        assert completed and session.cleanup_succeeded
        assert (
            session._rx_task.done()
            and not session._operations
            and not session._tx_operations
        )
        assert (
            session._pending_read
            is session._read_timeout
            is session._opening_task
            is None
        )
        assert session._data_updated.task is None and not session._data_updated.closing
        assert not client.session_observation.cleanup_failed
        assert client.session_observation.cleaned_generation == 1
        assert tls_peers.waits == [60]
        assert not life._task.done() and life._session is None
        assert session._rx_error.code == "timeout"
        assert life._failure.code == "timeout"
        state = session_state(hass, entry)
        assert (
            state.state == "reconnecting" and state.attributes["reconnect_count"] == 0
        )
        assert state.attributes["last_error_category"] == "timeout"
        assert state.attributes["last_successful_read_age"] >= 10
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert not coordinator.last_update_success
        assert safe_error_report(coordinator.last_exception)["error"] in {
            "timeout",
            "transport_unavailable",
        }
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        freezer.tick(59)
        await pump()
        assert len(tls_peers.transports) == 1
        freezer.tick(1.001)
        await pump()
        await life.wait_connected()
        await hass.async_block_till_done()
        assert len(tls_peers.transports) == 2 and len(tls_peers.owners) == 1
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert (
            coordinator.last_update_success
            and coordinator.last_successful_read_at > stamp
        )
        assert client.session_observation.read_generation == 2
        assert client.session_observation.read_sequence == 1
        assert session_state(hass, entry).attributes["reconnect_count"] == 1
        first.writer.close.assert_called_once_with()
        first.writer.wait_closed.assert_awaited_once_with()
        first.writer.transport.abort.assert_not_called()
        assert_private_values_absent(caplog.text + repr(client.safe_report()))
    finally:
        finish.set()
        if refresh is not None and not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        await asyncio.gather(*closers, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
    fresh.writer.close.assert_called_once_with()
    assert not any(
        t.get_name() in {"hoben-v4-lifecycle", "hoben-v4-rx", "hoben-dataupdated-probe"}
        for t in asyncio.all_tasks()
        if not t.done()
    )


@pytest.mark.parametrize("origin", ["read", "probe_write"])
@pytest.mark.parametrize(
    "fault", ["wait_error", "close_error", "timeout", "cancelled", "unload"]
)
async def test_real_cleanup_failure_or_stop_never_opens_another_tls(
    hass, entry, tls_peers, freezer, caplog, origin, fault
):
    first = tls_peers.wire([[RESPONSE], []])
    tls_peers.wire([[RESPONSE]])
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client, life = coordinator.client, tls_peers.owners[0]
    session = life._session
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    entered = asyncio.Event()

    async def wait_closed():
        entered.set()
        if fault == "wait_error":
            raise OSError("PRIVATE_PAYLOAD")
        if fault == "cancelled":
            raise asyncio.CancelledError()
        await asyncio.Future()

    if fault == "close_error":
        first.writer.close.side_effect = OSError("PRIVATE_PAYLOAD")
    first.writer.wait_closed.side_effect = wait_closed
    refresh = None
    unloaded = False
    try:
        refresh = await timeout_on(coordinator, first, session, freezer, origin)
        assert session._rx_error.code == "timeout"  # Original error survives.
        if fault in {"timeout", "unload"}:
            assert entered.is_set() and not session.cleanup_succeeded
            assert not tls_peers.waits and len(tls_peers.transports) == 1
        if fault == "timeout":
            freezer.tick(5.001)
            await pump()
        if fault == "unload":
            unload = asyncio.create_task(
                hass.config_entries.async_unload(entry.entry_id)
            )
            await pump()
            assert unload.done(), "unload left a teardown owner blocked"
            assert await unload
            unloaded = True
        if refresh is not None:
            await asyncio.gather(refresh, return_exceptions=True)
        await pump()
        assert not session.cleanup_succeeded
        assert client.session_observation.cleanup_failed
        assert life._task.done() and not tls_peers.waits
        assert len(tls_peers.transports) == 1 and len(tls_peers.owners) == 1
        first.writer.transport.abort.assert_called_once_with()
        assert session._rx_error.code == "timeout"
        assert (
            session._rx_task.done()
            and not session._operations
            and not session._tx_operations
        )
        assert not session._data_updated.closing and session._data_updated.task is None
        if not unloaded:
            assert life._failure.code == "cleanup_failed"
            state = session_state(hass, entry)
            assert state.state == "disconnected"
            assert state.attributes["last_error_category"] == "cleanup_failed"
            assert state.attributes["last_error_phase"] == "cleanup"
            assert state.attributes["reconnect_count"] == 0
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert (
                safe_error_report(coordinator.last_exception)["error"]
                == "cleanup_failed"
            )
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        freezer.tick(120)
        await pump()
        assert len(tls_peers.transports) == 1 and not tls_peers.waits
        assert_private_values_absent(caplog.text + repr(client.safe_report()))
    finally:
        if refresh is not None and not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        if not unloaded:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("fault", ["identity", "certificate", "internal"])
async def test_cleaned_probe_timeout_cannot_bypass_a_terminal_next_open(
    hass, entry, tls_peers, freezer, caplog, fault
):
    first = tls_peers.wire([[RESPONSE], []])
    fresh = tls_peers.wire([])
    if fault == "identity":
        fresh.queue = script_tls(fresh, openings=[[b"\x05\x02"]])
    else:
        fresh.connect_error = (
            ssl.SSLCertVerificationError("PRIVATE_PAYLOAD")
            if fault == "certificate"
            else RuntimeError("PRIVATE_PAYLOAD")
        )
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client, life = coordinator.client, tls_peers.owners[0]
    old = life._session
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    try:
        assert await timeout_on(coordinator, first, old, freezer, "probe_write") is None
        assert old.cleanup_succeeded and old._rx_error.code == "timeout"
        assert tls_peers.waits == [60] and len(tls_peers.transports) == 1
        freezer.tick(60.001)
        await pump()
        with pytest.raises(
            {
                "identity": HobenInvalidCredentialsError,
                "certificate": HobenTlsVerificationError,
                "internal": HobenInternalError,
            }[fault]
        ):
            await life.wait_stopped()
        report = safe_error_report(life._failure)
        assert (
            report["error"]
            == {
                "identity": "invalid_credentials",
                "certificate": "tls_verification_failed",
                "internal": "internal_failure",
            }[fault]
        )
        assert len(tls_peers.transports) == 2 and len(tls_peers.owners) == 1
        assert tls_peers.waits == [60]
        assert not client.session_observation.cleanup_failed
        assert session_state(hass, entry).attributes["reconnect_count"] == 0
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        freezer.tick(120)
        await pump()
        assert len(tls_peers.transports) == 2
        assert_private_values_absent(caplog.text + repr(report))
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
