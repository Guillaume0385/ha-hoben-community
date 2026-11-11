"""Two actual session owners over synthetic TLS; virtual time, never live."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import TransportError, TransportTlsError
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.ha_dual_evidence import empty, validate
from scripts.ha_dual_observer import observe


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.pending = []

    async def sleep(self, delay):
        future = asyncio.get_running_loop().create_future()
        self.pending.append((self.now + delay, future))
        try:
            await future
        finally:
            self.pending = [(at, f) for at, f in self.pending if f is not future]

    async def drive(self, task, hook):
        for _ in range(2000):
            for _ in range(30):
                await asyncio.sleep(0)
            if task.done():
                return await task
            pending = [at for at, f in self.pending if not f.done()]
            assert pending, "observer stalled without virtual deadline"
            self.now = min(pending)
            hook(self.now - 1000)
            for at, future in self.pending:
                if at <= self.now and not future.done():
                    future.set_result(None)
        raise AssertionError("virtual budget exceeded")


async def exercise(
    hass,
    entry,
    peers,
    monkeypatch,
    fault=None,
    *,
    opening_delay=0,
    b_opening_delay=0,
    close_delay=0,
    absolute_end=None,
    fragmented=False,
    opening_ping=False,
):
    reads = [[RESPONSE]] * 12
    if fragmented:
        reads = [[RESPONSE[:5], RESPONSE[5:] + b"\x0a"]] + reads[1:]
    a = peers.wire(DEVICE_GUID, reads)
    b = peers.wire(DEVICE_GUID, [[RESPONSE]])
    if opening_ping:
        receive = a.read.side_effect
        first = True

        async def read(*args, **kwargs):
            nonlocal first
            data = await receive(*args, **kwargs)
            if first:
                first = False
                return b"\x0a" + data
            return data

        a.read.side_effect = read
    monkeypatch.setattr("scripts.ha_dual_observer.AsyncTlsTransport", peers.factory)
    client = HobenClient(
        entry.data["user_guid"], DEVICE_GUID, max_attempts=1, ha_reconnect=True
    )
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    clock, e, fired = Clock(), empty(), set()
    if opening_delay:

        async def connect():
            await clock.sleep(opening_delay)

        a.connect.side_effect = connect
    if b_opening_delay:

        async def b_connect():
            await clock.sleep(b_opening_delay)

        b.connect.side_effect = b_connect
    if close_delay:

        async def close():
            await clock.sleep(close_delay)

        b.close.side_effect = close
    if fault == "b_refused":
        b.connect.side_effect = TransportTlsError("PRIVATE_PAYLOAD")
    if fault == "b_auth":
        b.read.side_effect = lambda *args, **kwargs: b"\x2f"
    if fault == "cancel_close":

        async def cancel_close():
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        b.close.side_effect = cancel_close
    if fault in {"a_cleanup", "b_cleanup"}:
        (a if fault == "a_cleanup" else b).close.side_effect = TransportError(
            "PRIVATE_PAYLOAD"
        )
    task = asyncio.create_task(
        observe(
            coordinator,
            evidence=e,
            clock=lambda: clock.now,
            sleep=clock.sleep,
            absolute_end=absolute_end,
        )
    )

    def hook(at):
        for marker in range(30, 661, 30):
            if at >= marker and marker not in fired:
                fired.add(marker)
                if not a.close.await_count:
                    a.queue.put_nowait(b"\x0a")
                if b.connect.await_count and not b.close.await_count:
                    b.queue.put_nowait(b"\x0a")
        if (
            (type(fault) is bytes or isinstance(fault, Exception))
            and at >= 240
            and "fault" not in fired
        ):
            fired.add("fault")
            a.queue.put_nowait(fault)
            if fault == b"\x0e\xff":
                a.queue.put_nowait(b"")
        if fault in {"cancel", "rollback"} and at >= 240 and "fault" not in fired:
            fired.add("fault")
            if fault == "cancel":
                task.cancel()
            else:
                clock.now -= 100

    try:
        try:
            await clock.drive(task, hook)
        except asyncio.CancelledError:
            assert fault in {"cancel", "cancel_close"}
        validate(e)
        return e, a, b
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client.async_close()
        assert_stopped(peers)


async def test_two_real_sessions_follow_180_360_660_schedule(
    hass, entry, peers, monkeypatch, caplog
):
    e, a, b = await exercise(hass, entry, peers, monkeypatch)
    assert e["completed"]
    assert [r["at_ms"] for r in e["reads"]] == list(range(0, 660001, 60000))
    assert e["b"] == dict(
        start_ms=180000,
        accepted_ms=180000,
        read_ms=180000,
        close_ms=360000,
        closed_ms=360000,
    )
    assert e["end_ms"] == 660000
    assert e["clock"] == "synthetic" and not e["boundary_proven"]
    assert sum(p["b"]["pongs"] for p in e["phases"]) > 0
    assert sum(p["a"]["pongs"] for p in e["phases"]) > 0
    assert [call.args[0][0] for call in b.write.await_args_list].count(13) == 1
    assert [call.args[0][0] for call in a.write.await_args_list].count(13) == 12
    assert_private_values_absent(caplog.text)


@pytest.mark.parametrize(
    "fault",
    [b"\x05\x03", b"\x0e\xff\xff\x00\x00\xff\xff", b"", b"\x0e\xff"],
    ids=["close-client", "invalid-mbap", "eof", "partial-eof"],
)
async def test_loss_or_malformed_framing_never_passes(
    hass, entry, peers, monkeypatch, fault
):
    e, _, _ = await exercise(hass, entry, peers, monkeypatch, fault)
    assert not e["completed"] and e["failure"] is not None
    assert len(e["reads"]) < 12


async def test_epoch_is_real_acceptance_and_postwindow_follows_actual_b_cleanup(
    hass, entry, peers, monkeypatch
):
    e, _, _ = await exercise(
        hass, entry, peers, monkeypatch, opening_delay=4, close_delay=5
    )
    assert e["completed"] and e["t0_ms"] == 4000
    assert e["b"]["close_ms"] == 360000 and e["b"]["closed_ms"] == 365000
    assert e["end_ms"] == 665000


@pytest.mark.parametrize(
    "fault",
    [
        "b_refused",
        "b_auth",
        "a_cleanup",
        "b_cleanup",
        "cancel",
        "cancel_close",
        "rollback",
    ],
)
async def test_failures_and_cancellation_preserve_resource_proof(
    hass, entry, peers, monkeypatch, fault, caplog
):
    e, _, _ = await exercise(hass, entry, peers, monkeypatch, fault)
    assert not e["completed"] and e["failure"] is not None
    if fault.endswith("cleanup"):
        assert not e["resources"][fault[0]]["cleanup"]
    assert_private_values_absent(caplog.text)


async def test_insufficient_global_budget_closes_a_without_opening_b(
    hass, entry, peers, monkeypatch
):
    e, _, b = await exercise(hass, entry, peers, monkeypatch, absolute_end=1700)
    assert not e["completed"] and e["error"] == "timeout"
    b.connect.assert_not_awaited()


async def test_fragmented_mbap_and_concatenated_ping_count_logical_messages_once(
    hass, entry, peers, monkeypatch
):
    e, _, _ = await exercise(hass, entry, peers, monkeypatch, fragmented=True)
    assert e["completed"]
    assert sum(p["a"]["fragments"] for p in e["phases"]) == 1
    assert sum(p["a"]["types"][4] for p in e["phases"]) == 12
    assert not e["boundary_proven"]


@pytest.mark.parametrize(
    "fault",
    [
        TransportTlsError("PRIVATE_PAYLOAD"),
        RuntimeError("PRIVATE_PAYLOAD"),
        RESPONSE[:1] + b"\x00\x01" + RESPONSE[3:],
    ],
)
async def test_tls_local_rx_and_uncorrelated_response_fail_closed(
    hass, entry, peers, monkeypatch, fault, caplog
):
    e, _, _ = await exercise(hass, entry, peers, monkeypatch, fault)
    assert not e["completed"] and e["failure"] is not None
    assert_private_values_absent(caplog.text)


async def test_observed_closeclient_subcode_is_preserved(
    hass, entry, peers, monkeypatch
):
    e, _, _ = await exercise(hass, entry, peers, monkeypatch, b"\x05\x03")
    assert e["failure"]["category"] == "closed"
    assert e["failure"]["subcode"] == 3
    assert sum(p["a"]["invalid"] for p in e["phases"]) == 0


async def test_excessive_b_close_duration_cannot_reduce_postwindow(
    hass, entry, peers, monkeypatch
):
    e, _, _ = await exercise(hass, entry, peers, monkeypatch, close_delay=11)
    assert not e["completed"] and e["error"] == "timeout"


async def test_opening_pong_does_not_invent_a_b3_post_open_ping_header(
    hass, entry, peers, monkeypatch
):
    e, _, _ = await exercise(hass, entry, peers, monkeypatch, opening_ping=True)
    assert e["completed"]
    assert sum(p["a"]["opening_pongs"] for p in e["phases"]) == 1


async def test_late_b_acceptance_stops_without_crediting_short_overlap(
    hass, entry, peers, monkeypatch
):
    e, _, b = await exercise(hass, entry, peers, monkeypatch, b_opening_delay=6)
    assert not e["completed"] and e["failure"]["role"] == "b"
    assert e["failure"]["category"] == "timeout"
    assert e["b_read_sequence"] == 0
    assert [c.args[0][0] for c in b.write.await_args_list] == [3]
