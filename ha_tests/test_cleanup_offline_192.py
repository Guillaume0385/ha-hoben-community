"""#192 characterization, not RED defect proof: genuine asyncio close witnesses.

Injected shutdown failures must remain fail-closed. Passing this matrix does
not identify the real shutdown failure or establish a corrective change.
"""

import asyncio
import logging
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
from scripts.ha_campaign_evidence import empty
from scripts.ha_campaign_observer import observe
from tests.test_data_updated_silence import pump

LOGGER = "custom_components.hoben.close_diagnostic"


@pytest.fixture(autouse=True)
def close_logging(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)


def close_records(caplog):
    return [r.hoben_tls_close for r in caplog.records if r.name == LOGGER]


def check_trace(trace, generation, mode):
    assert trace["generation"] == generation
    assert trace["connection_lost"] == (
        "not_observed" if mode == "unconfirmed" else "observed"
    )
    assert trace["future"] == (
        "completed_ok"
        if mode == "normal"
        else "cancelled"
        if mode == "unconfirmed"
        else "completed_error"
    )
    assert (
        trace["first_failure"] is None
        if mode == "normal"
        else (
            trace["first_failure"]["operation"] == "wait_closed"
            and trace["first_failure"]["result"]
            == {
                "reset": "raised_connection",
                "ssl_error": "raised_tls",
                "unconfirmed": "timeout",
            }[mode]
        )
    )
    assert 0 <= trace["elapsed_ms"] <= 5000
    assert not trace["truncated"] and not trace["invalid"]
    events = trace["events"]
    assert len(events) <= 12
    assert [e["order"] for e in events] == sorted(e["order"] for e in events)
    assert any(e["operation"] == "writer_close" for e in events)
    assert any(e["operation"] == "reap" and e["result"] == "returned" for e in events)


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
        self.gate_close = False

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
        if self.mode != "unconfirmed" and not self.gate_close:
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
@pytest.mark.parametrize("incident", [b"\x0e\xff\xff\x00\x00\xff\xff", b"\x05\x03"])
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
        logs = close_records(caplog)
        assert len(logs) == 1, "close operation discrimination is missing"
        check_trace(logs[0], 1, mode)
        assert session._rx_error.code == (
            "malformed_response"
            if incident == b"\x0e\xff\xff\x00\x00\xff\xff"
            else "experimental_close_client"
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
            delay = 60 if incident == b"\x0e\xff\xff\x00\x00\xff\xff" else 10
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
@pytest.mark.parametrize("closing", ["ordinary", "double", "cancel"])
async def test_s2_true_campaign_recovery_and_final_generation_close(
    hass, entry, tls, mode, closing, caplog
):
    first, second = tls.wire(), tls.wire(mode)
    second.gate_close = closing != "ordinary"
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

    evidence = empty("hoben-live")
    extras = []
    task = asyncio.create_task(
        observe(
            coordinator,
            "session-reconnect",
            evidence=evidence,
            clock=lambda: tls.now[0],
            sleep=sleep,
        )
    )
    try:
        # The observer does not advance its clock during final teardown.
        while not task.done():
            await pump()
            if second.closing and "teardown" not in marks:
                marks.add("teardown")
                if closing == "double":
                    extras.append(asyncio.create_task(client.async_close()))
                    await pump()
                    assert second.close_count == 1 and not extras[0].done()
                    if mode != "unconfirmed":
                        second.ack()
                elif closing == "cancel":
                    task.cancel()
                    asyncio.get_running_loop().call_soon(task.cancel)
            if second.closing and mode == "unconfirmed":
                tls.tick(1.001)
        if closing == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        await asyncio.gather(*extras)
        logs = close_records(caplog)
        assert len(logs) == 2, "per-generation close discrimination is missing"
        check_trace(logs[0], 1, "normal")
        if closing == "cancel":
            assert logs[1]["generation"] == 2
            assert logs[1]["first_failure"]["result"] == "cancelled"
        else:
            check_trace(logs[1], 2, mode)
        metrics = validated(
            evidence,
            tls.now[0],
            reason="cancelled" if closing == "cancel" else "completed",
        )
        assert evidence["recovery"]["outcome"] == "verified"
        assert evidence["recovery"]["suppressed_pongs"] == 1
        assert evidence["recovery"]["stable_ms"] == 120000
        assert metrics["reads"] == metrics["reads_ok"] == 5
        assert len(tls.transports) == 2 and len(tls.owners) == 1
        assert first.close_count == second.close_count == 1
        assert first.witness.done() and not first.witness.cancelled()
        assert metrics["recovered"]
        assert metrics["cleanup"] is (mode == "normal" and closing != "cancel")
        rows = evidence["diagnostic"]["owners"]
        assert rows[0]["stage"] == "reaped"
        if mode == "normal" and closing != "cancel":
            assert rows[1]["stage"] == "reaped"
            assert evidence["cleanup"]["completed"]
        else:
            assert rows[1]["stage"] == "tls_close" and rows[1]["pending"] == 0
            assert evidence["cleanup"]["observation"]["cleanup_failed"]
            assert not evidence["cleanup"]["completed"]
            assert evidence["recovery"]["diagnostic"]["cleanup"]["generation"] == 2
            assert evidence["recovery"]["diagnostic"]["cleanup"]["category"] == (
                "cancelled"
                if closing == "cancel"
                else "timeout"
                if mode == "unconfirmed"
                else "transport"
            )
            assert evidence["diagnostic"]["first"][3] == "close_client"
        assert_private_values_absent(caplog.text + repr(evidence))
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.async_close()
        await asyncio.gather(*extras, return_exceptions=True)
        for wire in tls.wires:
            if not wire.closed:
                wire.mode = "normal"
                wire.ack()
    assert not any(
        t.get_name() in {"hoben-tls-close", "hoben-v4-rx", "hoben-v4-lifecycle"}
        for t in asyncio.all_tasks()
        if not t.done()
    )


@pytest.mark.parametrize("cancel", [False, True])
async def test_s1_nested_closers_or_concurrent_cancel_keep_original_close_owner(
    hass, entry, tls, caplog, cancel
):
    first = tls.wire("unconfirmed")
    tls.wire()
    coordinator = await load(hass, entry)
    coordinator._async_unsub_refresh()
    client, owner = coordinator.client, tls.owners[0]
    session = owner._session
    stamp = coordinator.last_successful_read_at
    first.reader.feed_data(b"\x0e\xff\xff\x00\x00\xff\xff")
    await pump()
    assert first.closing and first.close_count == 1
    if cancel:
        session._rx_task.cancel()
        session._rx_task.cancel()
        await pump()
        assert session._rx_task.done() and not session.cleanup_succeeded
        assert client.session_observation.cleanup_failed and not tls.delays
        assert close_records(caplog)[0]["first_failure"]["result"] == "cancelled"
        tls.tick(120)
        await pump()
        assert len(tls.transports) == 1
    else:
        tasks = [
            asyncio.create_task(session.close()),
            asyncio.create_task(session.abort()),
        ]
        await pump()
        assert not any(t.done() for t in tasks)
        first.mode = "normal"
        first.ack()
        await asyncio.gather(*tasks)
        assert session.cleanup_succeeded and tls.delays == [60]
        assert len(close_records(caplog)) == 1
        check_trace(close_records(caplog)[0], 1, "normal")
    assert coordinator.last_successful_read_at == stamp
    assert first.close_count == 1
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    for wire in tls.wires:
        if not wire.closed:
            wire.mode = "normal"
            wire.ack()
