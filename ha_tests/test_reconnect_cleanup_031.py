"""#126/031: real owners and suspended synthetic closes, never live sockets."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import TransportError, TransportTimeout
from ha_tests.test_ha_controlled_reconnect import exercise
from ha_tests.test_manual_campaign_observer import detail
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.campaign_runtime_contract import stage, validate_report
from scripts.ha_campaign_evidence import empty, project
from scripts.ha_campaign_observer import observe
from scripts.run_campaign import run
from tests.test_campaign_runtime import PROVENANCE, envelope, node_accepts, observed


def suspend_close(peers, monkeypatch, *, generation=1):
    original = peers.wire
    events = []

    def wire(*args):
        transport = original(*args)
        if len(peers.wires) == generation:

            async def close():
                events.append(("started", asyncio.current_task().get_name()))
                try:
                    await asyncio.sleep(0)
                    await asyncio.sleep(0)
                except asyncio.CancelledError:
                    events.append(("cancelled", asyncio.current_task().get_name()))
                    raise
                events.append(("completed", asyncio.current_task().get_name()))

            transport.close.side_effect = close
        return transport

    monkeypatch.setattr(peers, "wire", wire)
    return events


async def test_controlled_reconnect_waits_for_original_transport_close(
    hass, entry, peers, monkeypatch
):
    events = suspend_close(peers, monkeypatch)
    e, _, _, _, _ = await exercise(hass, entry, peers, "close_client")
    assert [event for event, _ in events] == ["started", "completed"]
    assert e["recovery"]["outcome"] == "verified"
    assert e["recovery"]["diagnostic"]["cleanup"] is None
    assert not e["cleanup"]["observation"]["cleanup_failed"]


async def test_same_close_race_without_test_instrumentation(entry, peers, monkeypatch):
    events = suspend_close(peers, monkeypatch)
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    try:
        await client.async_refresh()
        first.queue.put_nowait(b"\x05\x03")
        await peers.backoff.entered.get()
        assert [event for event, _ in events] == ["started", "completed"]
    finally:
        await client.async_close()
        assert_stopped(peers)


async def test_cancellation_queued_before_close_is_still_delivered(entry, peers):
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    await client.async_refresh()
    session = client._lifecycle._session

    async def stop():
        asyncio.current_task().cancel()
        await session.close()

    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(stop())
    finally:
        await client.async_close()
        assert_stopped(peers)


async def timeline(
    hass, entry, peers, *, fault=None, generation=1, cancel=None, hold_first=False
):
    """Match the five-read run with real owners, two suppressed Pong and a gate.

    Every close has a real suspension. The controller observes completion of
    the original call, not a second idempotent close or a patched final verdict.
    """
    wires = [peers.wire(DEVICE_GUID, [[RESPONSE]] * 6) for _ in range(2)]
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now, finished, cancelled, started = [0.0], set(), set(), set()
    close_tasks, phases = [], []
    evidence = empty("hoben-live")
    task = None
    close_release = asyncio.Event()

    for number, wire in enumerate(wires, 1):
        read = wire.read.side_effect

        async def receive(*args, read=read, **kwargs):
            data = await read(*args, **kwargs)
            if data[:1] == b"\x0e":
                now[0] += 0.25  # A completed refresh schedules the next at +60 s.
            return data

        wire.read.side_effect = receive

        async def close(number=number):
            started.add(number)
            close_tasks.append(asyncio.current_task())
            phases.append((number, "start"))
            try:
                if number == generation and fault == "before":
                    raise asyncio.CancelledError
                if number == generation and cancel in {"during", "concurrent"}:
                    task.cancel()
                    if cancel == "concurrent":
                        asyncio.get_running_loop().call_soon(task.cancel)
                    await asyncio.Future()
                if number == 1 and hold_first:
                    await close_release.wait()
                await asyncio.sleep(0)
                if number == generation:
                    if fault == "during":
                        raise asyncio.CancelledError
                    if fault == "transport":
                        raise TransportError("PRIVATE_PAYLOAD")
                    if fault == "timeout":
                        raise TransportTimeout("PRIVATE_PAYLOAD")
                await asyncio.sleep(0)
                finished.add(number)
                phases.append((number, "finished"))
                if number == generation and fault == "after":
                    raise asyncio.CancelledError
                if number == generation and cancel == "after":
                    asyncio.get_running_loop().call_soon(task.cancel)
            except asyncio.CancelledError:
                cancelled.add(number)
                phases.append((number, "cancelled"))
                raise

        wire.close.side_effect = close

    async def connect_second():
        assert 1 in finished and 1 not in cancelled

    wires[1].connect.side_effect = connect_second
    fired = set()
    marks = (30, 60, 90, 120, 150, 180.55, 183.534)

    async def sleep(delay):
        target = now[0] + delay
        now[0] = next((m for m in marks if now[0] < m <= target), target)
        for _ in range(15):
            await asyncio.sleep(0)
        if now[0] in (30, 60, 90, 120, 150) and now[0] not in fired:
            wires[0].queue.put_nowait(b"\x0a")
            fired.add(now[0])
        if now[0] >= 180.55 and "loss" not in fired:
            wires[0].queue.put_nowait(b"\x05\x03")
            fired.add("loss")
        if now[0] >= 183.534 and peers.backoff.delays and "reopen" not in fired:
            peers.backoff.release.put_nowait(None)
            fired.add("reopen")
        if now[0] >= 183.534:
            close_release.set()
        if peers.factory.call_count == 2:
            wires[1].queue.put_nowait(b"\x0a")
        if cancel == "before" and generation not in started:
            if generation == 1 or peers.factory.call_count == 2:
                task.cancel()
        for _ in range(15):
            await asyncio.sleep(0)

    task = asyncio.create_task(
        observe(
            coordinator,
            "session-reconnect",
            evidence=evidence,
            clock=lambda: now[0],
            sleep=sleep,
        )
    )
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert_stopped(peers)
    assert all(t.done() for t in close_tasks)
    assert peers.factory.call_count <= 2
    return evidence, now[0], finished, cancelled, phases, client


def validated(evidence, elapsed, *, reason="completed"):
    d = detail("session-reconnect", evidence, max(1000, int(elapsed * 1000)))
    d["supervisor"]["reason"] = reason
    m = project("session-reconnect", d)
    value = stage(
        "ha",
        "session-reconnect",
        started=True,
        reason="observed",
        elapsed_ms=d["supervisor"]["elapsed_ms"],
        metrics=m,
        detail=d,
    )
    report = envelope("ha", "session-reconnect", [value])
    assert validate_report(report) and node_accepts(report)
    clock = [0.0]

    def execute(campaign, name, *args, **kwargs):
        result = value if name == "session-reconnect" else observed("ha", name)
        # One millisecond of parent bookkeeping is outside the worker receipt;
        # don't manufacture exact floating-point equality of summed durations.
        clock[0] += (result["elapsed_ms"] + 1) / 1000
        return result

    # Feed the actual owner evidence into the all gate; other isolated workers
    # supply closed fixtures. A recovered read never overrides unsafe cleanup.
    report = run(
        "ha", "all", PROVENANCE, b"synthetic", executor=execute, clock=lambda: clock[0]
    )
    assert validate_report(report) and node_accepts(report)
    assert report["actions_result"] == "FAILURE"  # no synthetic live completion
    for result in report["stages"][-2:]:
        if m["cleanup"] and reason == "completed":
            assert result["started"] and result["status"] == "SUCCESS"
        else:
            assert not result["started"] and result["status"] == "NOT RUN"
            assert result["reason"] == (
                "cleanup_failed" if not m["cleanup"] else reason
            )
    return m


async def test_five_reads_two_generations_and_both_original_closes_complete(
    hass, entry, peers, caplog
):
    e, elapsed, finished, cancelled, phases, _ = await timeline(hass, entry, peers)
    m = validated(e, elapsed)
    assert m["recovered"] and m["cleanup"] and m["reads"] == m["reads_ok"] == 5
    assert finished == {1, 2} and not cancelled
    assert phases == [(1, "start"), (1, "finished"), (2, "start"), (2, "finished")]
    assert e["recovery"]["suppressed_pongs"] == 2
    assert e["recovery"]["loss_after_ms"] == 180550
    assert e["recovery"]["reopened_after_ms"] == 183534
    assert e["recovery"]["stable_ms"] == 120000
    assert e["cleanup"]["observation"]["cleaned_generation"] == 2
    assert e["recovery"]["diagnostic"] == dict(interruption=None, cleanup=None)
    assert_private_values_absent(str(e) + caplog.text)


@pytest.mark.parametrize("generation", [1, 2])
@pytest.mark.parametrize("fault", ["before", "during", "after", "transport", "timeout"])
async def test_actual_close_failure_is_sticky_and_never_certifies_cleanup(
    hass, entry, peers, generation, fault, caplog
):
    e, elapsed, finished, cancelled, _, client = await timeline(
        hass, entry, peers, generation=generation, fault=fault
    )
    m = validated(e, elapsed)
    assert not m["cleanup"] and e["cleanup"]["observation"]["cleanup_failed"]
    assert m["recovered"] is (generation == 2)
    assert peers.factory.call_count == generation
    assert e["recovery"]["diagnostic"]["cleanup"] == dict(
        category="cancelled" if fault in {"before", "during", "after"} else fault,
        owner="transport_close",
        generation=generation,
        inhibition_exercised=True,
        subcode=None,
    )
    await client.async_close()
    assert client.session_observation.cleanup_failed
    assert_stopped(peers)
    assert_private_values_absent(str(e) + caplog.text)


@pytest.mark.parametrize("generation", [1, 2])
@pytest.mark.parametrize("cancel", ["before", "during", "after", "concurrent"])
async def test_observer_cancellation_does_not_erase_close_evidence(
    hass, entry, peers, generation, cancel, caplog
):
    e, elapsed, finished, cancelled, _, _ = await timeline(
        hass, entry, peers, generation=generation, cancel=cancel
    )
    m = validated(e, elapsed, reason="cancelled")
    if cancel in {"during", "concurrent"}:
        assert generation in cancelled and generation not in finished
        assert not m["cleanup"] and e["cleanup"]["observation"]["cleanup_failed"]
    else:
        assert generation in finished and generation not in cancelled
    assert e["cleanup"]["observation"]["stopped"]
    assert_private_values_absent(str(e) + caplog.text)


async def test_reopening_waits_for_the_existing_close_without_extending_budgets(
    hass, entry, peers
):
    e, elapsed, finished, cancelled, _, _ = await timeline(
        hass, entry, peers, hold_first=True
    )
    m = validated(e, elapsed)
    assert m["recovered"] and m["cleanup"]
    assert finished == {1, 2} and not cancelled
    assert e["recovery"]["reopened_after_ms"] > 183534
    assert e["recovery"]["reopened_after_ms"] < 240000 and elapsed < 570
