"""R2: real HA objects over synthetic TLS/clock, never a live connection."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import TransportEOF, TransportTimeout
from ha_tests.test_manual_campaign_observer import detail
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.campaign_runtime_contract import observed_status
from scripts.ha_campaign_evidence import project
from scripts.ha_campaign_observer import observe
from tests.test_data_updated_silence import pump


@pytest.mark.parametrize(
    "fault", [TransportEOF(), b"\x05\x03", TransportTimeout("read")]
)
@pytest.mark.parametrize("idle", [False, True])
async def test_300s_recovery_keeps_six_scheduled_calls_and_first_incident(
    hass, entry, peers, fault, freezer, caplog, idle
):
    first = peers.wire(
        DEVICE_GUID, [[RESPONSE], [RESPONSE], [RESPONSE if idle else fault]]
    )
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]] * 3)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        freezer.tick(seconds)
        await pump()
        if idle and now[0] == 150:
            first.queue.put_nowait(fault)
            await peers.backoff.entered.get()
            peers.backoff.release.put_nowait(None)
            await pump()
        if not peers.backoff.entered.empty():
            peers.backoff.entered.get_nowait()
            peers.backoff.release.put_nowait(None)
            await pump()

    try:
        e = await observe(coordinator, "hoben-live", clock=lambda: now[0], sleep=sleep)
        m = project("hoben-live", detail("hoben-live", e, int(now[0] * 1000) + 1))
        assert [s["decoded"] for s in e["samples"]] == [
            True,
            True,
            idle,
            True,
            True,
            True,
        ]
        assert [s["at_ms"] for s in e["samples"]] == [
            0,
            50000,
            100000,
            150000,
            200000,
            250000,
        ]
        assert (
            m["reads"] == 6 and m["reads_ok"] == (6 if idle else 5) and m["opens"] == 2
        )
        assert m["useful_ms"] == 300000 and m["cleanup"] and m["recovered"]
        assert not m["continuous"] and not m["completed"]
        assert (
            observed_status("ha", "hoben-live", {**m, "completed": True}) == "SUCCESS"
        )
        assert e["diagnostic"]["first"] is not None
        assert e["diagnostic"]["cleanup"] is None
        assert first.write.await_count + fresh.write.await_count == 8
        assert_private_values_absent(str(e) + caplog.text)
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize(
    "fault", [RuntimeError("PRIVATE_PAYLOAD"), b"\x05\x02", b"\xff"]
)
async def test_terminal_or_unproven_framing_never_becomes_recovered_success(
    hass, entry, peers, fault, freezer, caplog
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], [fault]])
    peers.wire(DEVICE_GUID, [[RESPONSE]] * 4)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        freezer.tick(seconds)
        await pump()
        if not peers.backoff.entered.empty():
            peers.backoff.entered.get_nowait()
            peers.backoff.release.put_nowait(None)
            await pump()

    try:
        e = await observe(coordinator, "hoben-live", clock=lambda: now[0], sleep=sleep)
        m = project("hoben-live", detail("hoben-live", e, int(now[0] * 1000) + 1))
        assert not m["recovered"] and not m["continuous"]
        assert (
            observed_status("ha", "hoben-live", {**m, "completed": True}) == "FAILURE"
        )
        assert e["diagnostic"]["first"] is not None
        if isinstance(fault, RuntimeError) or fault == b"\x05\x02":
            assert peers.factory.call_count == 1 and first.write.await_count == 3
        assert_private_values_absent(str(e) + caplog.text)
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize("copy_data", [False, True])
async def test_ha_success_or_copied_b7_cache_does_not_count_as_fresh(
    hass, entry, peers, monkeypatch, copy_data
):
    from dataclasses import replace

    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    original = coordinator.async_refresh
    now = [0.0]
    calls = [0]

    async def refresh():
        calls[0] += 1
        if calls[0] == 1:
            await original()
        else:
            coordinator.last_update_success = True
            if copy_data:
                coordinator.data = replace(coordinator.data)

    async def sleep(seconds):
        now[0] += seconds
        await pump()

    monkeypatch.setattr(coordinator, "async_refresh", refresh)
    try:
        e = await observe(coordinator, "hoben-live", clock=lambda: now[0], sleep=sleep)
        assert [s["decoded"] for s in e["samples"]] == [True] + [False] * 5
        # Forged success without any real error produces inconsistent F1:
        # no first incident can attest these five failed acquisition claims.
        # The closed report validator must reject it, never publish success.
        with pytest.raises(ValueError):
            project("hoben-live", detail("hoben-live", e, 300001))
        assert wire.write.await_count == 2
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize("close_fault", ["error", "cancel"])
async def test_old_cleanup_failure_preserves_eof_and_forbids_second_session(
    hass, entry, peers, close_fault, caplog
):
    from custom_components.hoben.exceptions import HobenError
    from custom_components.hoben.transport import TransportError
    from scripts.ha_campaign_evidence import empty

    first = peers.wire(DEVICE_GUID, [[RESPONSE], [TransportEOF()]])
    first.close.side_effect = (
        TransportError("PRIVATE_PAYLOAD")
        if close_fault == "error"
        else asyncio.CancelledError()
    )
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now, e = [0.0], empty("hoben-live")

    async def sleep(seconds):
        now[0] += seconds
        await pump()

    try:
        await observe(
            coordinator, "hoben-live", evidence=e, clock=lambda: now[0], sleep=sleep
        )
        m = project("hoben-live", detail("hoben-live", e, 300001))
        assert not m["cleanup"] and not m["recovered"]
        assert e["diagnostic"]["first"][3] == "eof"
        assert e["diagnostic"]["cleanup"] is not None
        assert peers.factory.call_count == 1
        assert_private_values_absent(str(e) + caplog.text)
    finally:
        try:
            await coordinator.async_shutdown()
        except (HobenError, asyncio.CancelledError):
            pass
        try:
            await client.async_close()
        except (HobenError, asyncio.CancelledError):
            pass
    assert_stopped(peers)


async def test_cancelled_pending_read_retains_partial_evidence_and_no_success(
    hass, entry, peers
):
    from scripts.ha_campaign_evidence import empty

    wire = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now, e = [0.0], empty("hoben-live")

    async def sleep(seconds):
        now[0] += seconds
        await pump()

    task = asyncio.create_task(
        observe(
            coordinator, "hoben-live", evidence=e, clock=lambda: now[0], sleep=sleep
        )
    )
    try:
        while wire.write.await_count < 3:
            await pump()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        m = project("hoben-live", detail("hoben-live", e, 50001))
        assert not m["completed"] and not m["recovered"]
        assert observed_status("ha", "hoben-live", m) == "FAILURE"
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)


async def test_real_b7_hold_expires_at_300_without_becoming_a_new_read(
    hass, entry, peers, monkeypatch, freezer
):
    from ha_tests.test_snapshot_hold_b7 import LocalClock

    clock = LocalClock(monkeypatch, freezer)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    initial = [None]

    async def sleep(seconds):
        if initial[0] is None:
            initial[0] = coordinator.last_successful_read_at
            wire.queue.put_nowait(TransportEOF())
            await peers.backoff.entered.get()
            assert coordinator.snapshot_available
        await clock.advance(seconds)
        assert coordinator.snapshot_available is (clock.now < 300)

    try:
        e = await observe(
            coordinator, "hoben-live", clock=lambda: clock.now, sleep=sleep
        )
        m = project("hoben-live", detail("hoben-live", e, 300001))
        assert [s["decoded"] for s in e["samples"]] == [True] + [False] * 5
        assert coordinator.last_successful_read_at == initial[0]
        assert e["window"]["elapsed_ms"] == 300000
        assert not m["recovered"] and m["reads_ok"] == 1
        assert (
            observed_status("ha", "hoben-live", {**m, "completed": True}) == "FAILURE"
        )
        assert peers.factory.call_count == 1 and wire.write.await_count == 2
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)
