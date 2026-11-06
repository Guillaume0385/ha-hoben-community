"""#192 characterization, not RED defect proof: genuine asyncio close witnesses.

Injected shutdown failures must remain fail-closed. Passing this matrix does
not identify the real shutdown failure or establish a corrective change.
"""

import asyncio
import ssl
from types import SimpleNamespace

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import AsyncTlsTransport
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from ha_tests.test_persistent_client import RESPONSE, load, opening, sensor
from ha_tests.test_reconnect_cleanup_031 import validated
from ha_tests.test_session_sensor import session_state
from scripts.ha_campaign_observer import observe
from tests.test_data_updated_silence import pump


class Wire(asyncio.Transport):
    """A physical-close flag and a distinct protocol callback, never a socket."""

    def __init__(self, *, mode, tick):
        self.mode, self.tick = mode, tick
        self.reader = asyncio.StreamReader()
        self.protocol = asyncio.StreamReaderProtocol(self.reader)
        self.protocol.connection_made(self)
        self.writer = asyncio.StreamWriter(
            self, self.protocol, self.reader, asyncio.get_running_loop()
        )
        self.witness = self.protocol._get_close_waiter(self.writer)
        self.closing = self.closed = False
        self.close_count = self.abort_count = self.reads = self.pongs = 0
        self.trace = []
        self.silent = False

    def get_extra_info(self, name, default=None):
        return default

    def is_closing(self):
        return self.closing

    def write(self, data):
        if data[0] == 3:
            self.reader.feed_data(opening(DEVICE_GUID))
        elif data[0] == 13:
            self.reads += 1
            if not self.silent:
                self.tick(0.25)
                self.reader.feed_data(RESPONSE)
        elif data == b"\x0b":
            self.pongs += 1
        else:
            raise AssertionError("unexpected synthetic TX")

    def close(self):
        self.closing = True
        self.close_count += 1
        self.trace.append(("close", asyncio.current_task().get_name()))
        self.tick(0.125)
        if self.mode != "unconfirmed":
            asyncio.get_running_loop().call_soon(self.ack)

    def abort(self):
        self.abort_count += 1
        self.trace.append(("abort", asyncio.current_task().get_name()))
        if self.mode != "unconfirmed":
            self.ack()

    def ack(self):
        if not self.closed:
            self.closed = True
            error = (
                ConnectionResetError("PRIVATE_PAYLOAD")
                if self.mode == "reset"
                else ssl.SSLError("PRIVATE_PAYLOAD")
                if self.mode == "ssl_error"
                else None
            )
            self.trace.append(("callback_error" if error else "callback_ok", "sdk"))
            self.protocol.connection_lost(error)


@pytest.fixture
def tls(monkeypatch, freezer):
    wires, transports, owners, delays = [], [], [], []
    now = [0.0]
    context = ssl.create_default_context()
    threaded = asyncio.to_thread

    async def to_thread(function, *args, **kwargs):
        # The CA store is real, preloaded once; OS thread scheduling must not
        # decide when this in-memory handshake advances its synthetic clock.
        if function is ssl.create_default_context:
            return context
        return await threaded(function, *args, **kwargs)

    def tick(seconds):
        now[0] += seconds
        freezer.tick(seconds)

    def wire(mode="normal"):
        result = Wire(mode=mode, tick=tick)
        wires.append(result)
        return result

    async def connect(host, port, **options):
        assert (host, port) == ("myhoben.fr", 465)
        assert options["server_hostname"] == "myhoben.fr"
        assert options["ssl"].check_hostname
        assert options["ssl"].verify_mode == ssl.CERT_REQUIRED
        assert all(w.closed for w in wires[: len(transports) - 1])
        current = wires[len(transports) - 1]
        return current.reader, current.writer

    def transport():
        result = AsyncTlsTransport()
        transports.append(result)
        return result

    async def sleep(seconds):
        delays.append(seconds)
        await asyncio.sleep(seconds)

    def owner(**options):
        result = V4Lifecycle(**(options | {"sleep": sleep}))
        owners.append(result)
        return result

    monkeypatch.setattr(asyncio, "open_connection", connect)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    monkeypatch.setattr("custom_components.hoben.client.AsyncTlsTransport", transport)
    monkeypatch.setattr("custom_components.hoben.v4_lifecycle.V4Lifecycle", owner)
    return SimpleNamespace(
        wire=wire,
        wires=wires,
        transports=transports,
        owners=owners,
        delays=delays,
        tick=tick,
        now=now,
    )


@pytest.mark.parametrize("mode", ["normal", "reset", "ssl_error", "unconfirmed"])
@pytest.mark.parametrize("incident", [b"\x0c", b"\x05\x03"])
async def test_s1_rx_loss_and_real_close_callback(
    hass, entry, tls, mode, incident, caplog
):
    first = tls.wire(mode)
    tls.wire()
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client, owner = coordinator.client, tls.owners[0]
    session = owner._session
    snapshot, stamp = coordinator.data, coordinator.last_successful_read_at
    first.silent = True
    refresh = asyncio.create_task(coordinator.async_refresh())
    try:
        await pump()
        assert session._pending_read is not None
        first.reader.feed_data(incident)
        await pump()
        if mode == "unconfirmed":
            tls.tick(4.001)
            await pump()
            assert not session.cleanup_succeeded and not tls.delays
            tls.tick(1.001)
            await pump()
        await refresh
        coordinator._async_unsub_refresh()
        assert session._rx_error.code == (
            "malformed_response" if incident == b"\x0c" else "experimental_close_client"
        )
        assert first.close_count == 1
        assert session._rx_task.done() and not session._operations
        assert not session._tx_operations and session._pending_read is None
        assert (
            coordinator.data is snapshot
            and coordinator.last_successful_read_at == stamp
        )
        assert not coordinator.last_update_success
        if mode == "normal":
            assert session.cleanup_succeeded and tls.delays
            assert session_state(hass, entry).state == "reconnecting"
            assert sensor(hass, entry).state != "unavailable"
            assert len(tls.transports) == 1
            delay = 60 if incident == b"\x0c" else 10
            assert tls.delays == [delay]
            tls.tick(delay - 0.001)
            await pump()
            assert len(tls.transports) == 1
            tls.tick(0.002)
            await pump()
            assert len(tls.transports) == 2
            assert coordinator.last_successful_read_at == stamp
            assert client.session_observation.read_generation != 2
            if incident == b"\x05\x03":
                tls.tick(10.001)
                await pump()
            await coordinator.async_refresh()
            coordinator._async_unsub_refresh()
            assert coordinator.last_update_success
            assert coordinator.last_successful_read_at > stamp
            assert client.session_observation.read_generation == 2
            assert client.session_observation.read_sequence > 0
        else:
            assert not session.cleanup_succeeded
            assert client.session_observation.cleanup_failed and owner._task.done()
            assert session_state(hass, entry).state == "disconnected"
            assert sensor(hass, entry).state == "unavailable"
            tls.tick(120)
            await pump()
            assert len(tls.transports) == 1 and not tls.delays
        assert_private_values_absent(caplog.text + repr(client.safe_report()))
    finally:
        if not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
        for wire in tls.wires:
            if not wire.closed:
                wire.mode = "normal"
                wire.ack()


@pytest.mark.parametrize("mode", ["normal", "reset", "ssl_error", "unconfirmed"])
async def test_s2_true_campaign_recovery_and_final_generation_close(
    hass, entry, tls, mode, caplog
):
    first, second = tls.wire(), tls.wire(mode)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    marks = set()

    async def sleep(seconds):
        tls.tick(seconds)
        await pump()
        now = tls.now[0]
        for at in (30, 60, 90, 120):
            if now >= at and at not in marks:
                first.reader.feed_data(b"\x0a")
                marks.add(at)
        if now >= 180.55 and "loss" not in marks:
            first.reader.feed_data(b"\x05\x03")
            marks.add("loss")
        if len(tls.transports) == 2:
            second.reader.feed_data(b"\x0a")
        await pump()

    task = asyncio.create_task(
        observe(coordinator, "session-reconnect", clock=lambda: tls.now[0], sleep=sleep)
    )
    try:
        # The observer does not advance its clock during final teardown.
        while not task.done():
            await pump()
            if second.closing and mode == "unconfirmed":
                tls.tick(1.001)
        evidence = await task
        metrics = validated(evidence, tls.now[0])
        assert evidence["recovery"]["outcome"] == "verified"
        assert evidence["recovery"]["suppressed_pongs"] == 1
        assert evidence["recovery"]["stable_ms"] == 120000
        assert metrics["reads"] == metrics["reads_ok"] == 5
        assert len(tls.transports) == 2 and len(tls.owners) == 1
        assert first.close_count == second.close_count == 1
        assert first.witness.done() and not first.witness.cancelled()
        assert metrics["recovered"]
        assert metrics["cleanup"] is (mode == "normal")
        rows = evidence["diagnostic"]["owners"]
        assert rows[0]["stage"] == "reaped"
        if mode == "normal":
            assert rows[1]["stage"] == "reaped"
            assert evidence["cleanup"]["completed"]
        else:
            assert rows[1]["stage"] == "tls_close" and rows[1]["pending"] == 0
            assert evidence["cleanup"]["observation"]["cleanup_failed"]
            assert not evidence["cleanup"]["completed"]
            assert evidence["recovery"]["diagnostic"]["cleanup"]["generation"] == 2
            assert evidence["recovery"]["diagnostic"]["cleanup"]["category"] == (
                "timeout" if mode == "unconfirmed" else "transport"
            )
            assert evidence["diagnostic"]["first"][3] == "close_client"
        assert_private_values_absent(caplog.text + repr(evidence))
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.async_close()
        for wire in tls.wires:
            if not wire.closed:
                wire.mode = "normal"
                wire.ack()
    assert not any(
        t.get_name() in {"hoben-tls-close", "hoben-v4-rx", "hoben-v4-lifecycle"}
        for t in asyncio.all_tasks()
        if not t.done()
    )
