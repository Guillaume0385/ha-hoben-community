"""#192: four actual owners, synthetic V4 timeout and real local fd cleanup.

No network fixture is enabled: the harness permits the local socketpair needed
by asyncio, while DNS/IP connections remain forbidden. Hoben bytes are fed to
StreamReader in memory; no TLS handshake or socket write is performed.
"""

import asyncio
import ssl
from types import SimpleNamespace

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.transport import AsyncTlsTransport
from ha_tests.test_persistent_client import RESPONSE, load, opening
from tests.test_data_updated_silence import Clock, pump
from tests.test_tls_close_recovery_192 import TlsStack
from tests.test_v4_lifecycle import Backoff


@pytest.fixture
def tls_stacks(monkeypatch, legacy_polling_client):
    context = ssl.create_default_context()
    stacks, owners, backoff = [], [], Backoff()
    real_to_thread = asyncio.to_thread
    real_owner = v4_lifecycle.V4Lifecycle
    modes = ["ok", "ok", "ok", "tls", "ok"]

    async def to_thread(function, *args, **kwargs):
        if function is ssl.create_default_context:
            return context
        return await real_to_thread(function, *args, **kwargs)

    async def connect(host, port, **options):
        assert (host, port) == ("myhoben.fr", 465)
        assert options["server_hostname"] == host
        assert options["ssl"].check_hostname
        assert options["ssl"].verify_mode == ssl.CERT_REQUIRED
        assert all(stack.socket.fileno() == -1 for stack in stacks)
        stack = TlsStack(mode=modes[len(stacks)], context=context)
        stack.silent, stack.writes = False, []

        def send(data):
            stack.writes.append(data[0])
            if data[0] == 3:
                stack.reader.feed_data(opening(DEVICE_GUID))
            elif data[0] == 13 and not stack.silent:
                stack.reader.feed_data(RESPONSE)

        stack.writer.write = send
        stacks.append(stack)
        return stack.reader, stack.writer

    def owner(**options):
        # Existing explicit compatibility timing, no production scheduler change.
        options.update(sleep=backoff, ha_fast_reconnect=False)
        result = real_owner(**options)
        owners.append(result)
        return result

    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    monkeypatch.setattr(
        "custom_components.hoben.client.AsyncTlsTransport", AsyncTlsTransport
    )
    monkeypatch.setattr(v4_lifecycle, "V4Lifecycle", owner)
    return SimpleNamespace(stacks=stacks, owners=owners, backoff=backoff, modes=modes)


@pytest.mark.parametrize("mode", ["tls", "callback_only", "missing_callback", "other"])
async def test_gen4_correlation_timeout_reconnects_only_after_independent_release(
    hass, entry, tls_stacks, monkeypatch, caplog, mode
):
    caplog.set_level("DEBUG", logger="custom_components.hoben.close_diagnostic")
    caplog.set_level("DEBUG", logger="custom_components.hoben.v4_lifecycle")
    clock = Clock(monkeypatch)
    tls_stacks.modes[3] = mode
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    life = tls_stacks.owners[0]
    refresh = None
    try:
        for generation in range(1, 4):
            current = tls_stacks.stacks[-1]
            current.reader.feed_eof()
            await pump()
            await clock.advance(0.049)
            assert await tls_stacks.backoff.entered.get() == 60
            assert life.witness.lost_generation == generation
            tls_stacks.backoff.release.put_nowait(None)
            await life.wait_connected()
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert life.witness.verified_read_generation == generation + 1

        old = life._session
        fourth = tls_stacks.stacks[3]
        fourth.silent = True
        previous, stamp = coordinator.data, coordinator.last_successful_read_at
        refresh = asyncio.create_task(coordinator.async_refresh())
        await pump()
        await clock.advance(30)
        await refresh
        coordinator._async_unsub_refresh()
        for _ in range(2):
            await clock.advance(60)
            await clock.advance(30)
        assert fourth.close_count == 1
        assert any(
            "phase=request_correlation" in r.getMessage() for r in caplog.records
        )
        assert fourth.writes.count(13) == 4  # Fresh initial read, three expirations.
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        await clock.advance(0.049)
        assert len(tls_stacks.stacks) == 4
        trace = next(
            r.hoben_tls_close
            for r in caplog.records
            if hasattr(r, "hoben_tls_close") and r.hoben_tls_close["generation"] == 4
        )
        assert trace["first_failure"]["operation"] == "wait_closed"
        assert trace["connection_lost"] == (
            "not_observed" if mode == "missing_callback" else "observed"
        )
        assert trace["future"] == "completed_error"
        assert trace["first_failure"]["at_ms"] <= 50
        assert trace["first_failure"]["result"] == (
            "raised_other" if mode == "other" else "raised_tls"
        )
        if mode == "tls":
            assert old.cleanup_succeeded
            assert await tls_stacks.backoff.entered.get() == 60
            assert fourth.socket.fileno() == -1
            tls_stacks.backoff.release.put_nowait(None)
            await life.wait_connected()
            assert coordinator.last_successful_read_at == stamp
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert coordinator.last_update_success
            assert life.witness.verified_read_generation == 5
        else:
            await pump()
            assert not old.cleanup_succeeded
            assert life._task.done() and tls_stacks.backoff.entered.empty()
            assert len(tls_stacks.stacks) == 4
        assert_private_values_absent(caplog.text)
        assert "SYNTHETIC_PRIVATE" not in caplog.text
    finally:
        if refresh is not None:
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        unload = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
        await pump()
        await clock.advance(0.049)
        assert await unload
        for stack in tls_stacks.stacks:
            await stack.cleanup()
        assert not any(
            t.get_name() in {"hoben-tls-close", "hoben-v4-rx", "hoben-v4-lifecycle"}
            and not t.done()
            for t in asyncio.all_tasks()
        )
