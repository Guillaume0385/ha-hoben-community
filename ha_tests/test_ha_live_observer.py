"""Actual HA observer with in-memory peers; no sandbox/network dependency."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import TransportEOF
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.ha_live_proof import build_report, empty_evidence, encode_report
from scripts.ha_session_observer import observe
from tests.test_ha_live_proof import PROVENANCE, node_accepts, receipt


@pytest.mark.parametrize(
    "loss",
    [None, [b"\x05", b"\x03\x0a" + RESPONSE], [TransportEOF("synthetic-private")]],
)
async def test_true_ha_observer_evidence_without_private_owner_access(
    hass, entry, peers, loss, caplog
):
    peers.wire(
        DEVICE_GUID,
        [[RESPONSE]] * 6 if loss is None else [[RESPONSE], [RESPONSE], loss],
    )
    if loss is not None:
        peers.wire(DEVICE_GUID, [[RESPONSE]] * 3)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = 0.0

    async def sleep(delay):
        nonlocal now
        now += delay
        await asyncio.sleep(0)
        if loss is not None and now == 150:
            await peers.backoff.entered.get()
            peers.backoff.release.put_nowait(None)

    data = await observe(coordinator, clock=lambda: now, sleep=sleep)
    r = build_report(PROVENANCE, receipt(), data)
    assert r["criteria"]["tls_reuse"] == "SUCCESS"
    assert r["criteria"]["reconnection"] == (
        "INCONCLUSIVE" if loss is None else "SUCCESS"
    )
    assert r["criteria"]["cleanup"] == "SUCCESS"
    encoded = encode_report(r)
    assert node_accepts(encoded)
    assert_private_values_absent(encoded + caplog.text)
    assert "synthetic-private" not in encoded + caplog.text
    assert_stopped(peers)


async def test_cancel_preserves_only_attested_partial_evidence(hass, entry, peers):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    evidence = empty_evidence()
    now = 0.0

    async def sleep(delay):
        nonlocal now
        now += delay
        await asyncio.sleep(0)

    task = asyncio.create_task(
        observe(coordinator, clock=lambda: now, sleep=sleep, evidence=evidence)
    )
    while wire.write.await_count < 3:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    r = build_report(PROVENANCE, receipt(reason="cancelled"), evidence)
    assert r["criteria"]["collection"] == "FAILURE"
    assert r["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert r["outcome"] == "FAILURE"
    assert_stopped(peers)


class SteppedClock:
    """Let the test stop on either side of the exact observation boundary."""

    def __init__(self):
        self.now = 0.0
        self.waiting = asyncio.Queue()
        self.advance = asyncio.Queue()

    async def sleep(self, delay):
        self.waiting.put_nowait(delay)
        delta = await self.advance.get()
        self.now += delta
        await asyncio.sleep(0)

    async def tail(self):
        for _ in range(5):
            assert await self.waiting.get() == 50
            self.advance.put_nowait(50)
        assert await self.waiting.get() == 50
        assert self.now == 250


def start_window(hass, entry, peers):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    clock, evidence = SteppedClock(), empty_evidence()
    task = asyncio.create_task(
        observe(
            coordinator, clock=lambda: clock.now, sleep=clock.sleep, evidence=evidence
        )
    )
    return wire, client, clock, evidence, task


async def test_250_and_299999_are_not_300_second_completion(hass, entry, peers):
    wire, client, clock, evidence, task = start_window(hass, entry, peers)
    await asyncio.wait_for(clock.tail(), 2)
    assert len(evidence["samples"]) == 6 and client.session_observation.active
    assert not evidence["completed"] and not task.done()
    # An early wakeup at 299.999 must require another wait and fresh clock read.
    clock.advance.put_nowait(49.999)
    assert await clock.waiting.get() == pytest.approx(0.001)
    assert clock.now == 299.999 and not evidence["completed"]
    with pytest.raises(ValueError):
        build_report(PROVENANCE, receipt(reason="cancelled"), evidence)
    clock.advance.put_nowait(0.001)
    data = await asyncio.wait_for(task, 2)
    assert clock.now == 300 and data["completed"]
    assert data["window"]["clock"] == "synthetic"
    assert data["window"]["elapsed_ms"] == 300000
    assert data["window"]["active"] and not client.session_observation.active
    assert wire.write.await_count == 7  # opening + six reads, no seventh read
    r = build_report(PROVENANCE, receipt(), data)
    assert r["criteria"]["continuous_300s"] == "SUCCESS"
    assert r["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert node_accepts(encode_report(r))
    assert_stopped(peers)


@pytest.mark.parametrize("loss", [TransportEOF("private-late"), b"\x05\x03", b"\xff"])
async def test_loss_or_terminal_failure_after_last_read_invalidates_continuity(
    hass, entry, peers, loss
):
    wire, client, clock, evidence, task = start_window(hass, entry, peers)
    await asyncio.wait_for(clock.tail(), 2)
    clock.now = 275
    wire.queue.put_nowait(loss)
    # The real RX owner, not observer polling, records the failure.
    for _ in range(100):
        if not client.session_observation.active:
            break
        await asyncio.sleep(0)
    assert not client.session_observation.active
    if loss != b"\xff":
        await asyncio.wait_for(peers.backoff.entered.get(), 2)
    clock.advance.put_nowait(25)
    data = await asyncio.wait_for(task, 2)
    assert data["completed"] and data["window"]["elapsed_ms"] == 300000
    assert not data["window"]["active"]
    assert data["window"]["observation"]["loss_kind"] == (
        None
        if loss == b"\xff"
        else "close_client"
        if loss == b"\x05\x03"
        else "transport"
    )
    r = build_report(PROVENANCE, receipt(), data)
    assert r["criteria"]["continuous_300s"] == "FAILURE"
    assert r["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert r["outcome"] == "FAILURE" and node_accepts(encode_report(r))
    assert_stopped(peers)


@pytest.mark.parametrize("at", [250, 299.999, 300, 360])
async def test_cancel_at_boundary_never_fabricates_final_witness(
    hass, entry, peers, at
):
    _wire, _client, clock, evidence, task = start_window(hass, entry, peers)
    await asyncio.wait_for(clock.tail(), 2)
    clock.now = at
    task.cancel()  # cancellation before the final checkpoint is attested
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not evidence["completed"] and evidence["cleanup"]["completed"]
    r = build_report(PROVENANCE, receipt(reason="cancelled"), evidence)
    assert r["criteria"]["continuous_300s"] == "FAILURE"
    assert r["outcome"] == "FAILURE" and node_accepts(encode_report(r))
    assert_stopped(peers)


async def test_backward_clock_cannot_attest_completion(hass, entry, peers):
    _wire, _client, clock, evidence, task = start_window(hass, entry, peers)
    await asyncio.wait_for(clock.tail(), 2)
    clock.advance.put_nowait(-1)
    data = await asyncio.wait_for(task, 2)
    assert not data["completed"] and data["window"]["elapsed_ms"] == 250000
    assert data["cleanup"]["completed"]
    assert_stopped(peers)


async def test_cleanup_after_300_is_separate_and_does_not_extend_window(
    hass, entry, peers, monkeypatch
):
    _wire, client, clock, evidence, task = start_window(hass, entry, peers)
    await asyncio.wait_for(clock.tail(), 2)
    close = client.async_close

    async def delayed_close():
        assert evidence["completed"] and clock.now == 300
        clock.now += 9
        await close()

    monkeypatch.setattr(client, "async_close", delayed_close)
    clock.advance.put_nowait(50)
    data = await asyncio.wait_for(task, 2)
    assert clock.now == 309 and data["window"]["elapsed_ms"] == 300000
    assert data["cleanup"]["completed"]
    assert_stopped(peers)


@pytest.mark.parametrize("at", [300, 360])
async def test_cancel_during_cleanup_keeps_window_but_refuses_overall_success(
    hass, entry, peers, monkeypatch, at
):
    _wire, client, clock, evidence, task = start_window(hass, entry, peers)
    await asyncio.wait_for(clock.tail(), 2)
    close, entered = client.async_close, asyncio.Event()

    async def pending_close():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await close()

    monkeypatch.setattr(client, "async_close", pending_close)
    clock.advance.put_nowait(50)
    await asyncio.wait_for(entered.wait(), 2)
    assert evidence["completed"] and evidence["window"]["elapsed_ms"] == 300000
    clock.now = at
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not evidence["cleanup"]["completed"]
    r = build_report(
        PROVENANCE, receipt(reason="cancelled", elapsed_ms=at * 1000), evidence
    )
    assert r["criteria"]["cleanup"] == "FAILURE"
    assert r["criteria"]["continuous_300s"] == "FAILURE"
    assert r["outcome"] == "FAILURE" and node_accepts(encode_report(r))
    assert_stopped(peers)


async def test_native_clock_is_monotonic_and_cancelled_without_live_wait(
    hass, entry, peers
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    evidence = empty_evidence()
    task = asyncio.create_task(observe(coordinator, evidence=evidence))
    for _ in range(100):
        if len(evidence["samples"]) == 1:
            break
        await asyncio.sleep(0)
    assert wire.write.await_count == 2 and len(evidence["samples"]) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert evidence["window"]["clock"] == "monotonic"
    assert not evidence["completed"]
    r = build_report(PROVENANCE, receipt(reason="cancelled"), evidence)
    assert r["criteria"]["continuous_300s"] == "FAILURE"
    assert node_accepts(encode_report(r))
    assert_stopped(peers)
