"""R1 uses the unchanged real HA client, owner and coordinator over fake TLS."""

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


@pytest.mark.parametrize("scenario,count", [("session-reuse", 3), ("availability", 2)])
@pytest.mark.parametrize(
    "fault", [TransportEOF(), b"\x05\x03", TransportTimeout("read"), b"\xff"]
)
async def test_existing_scenario_accepts_proven_recovery_without_an_extra_read(
    hass, entry, peers, scenario, count, fault, freezer, caplog
):
    first = peers.wire(DEVICE_GUID, [[fault]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]] * (count - 1))
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]
    released = False

    async def sleep(seconds):
        nonlocal released
        now[0] += seconds
        freezer.tick(seconds)
        if not released:
            await peers.backoff.entered.get()
            peers.backoff.release.put_nowait(None)
            released = True
        await pump()

    try:
        e = await observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
        d = detail(scenario, e, int(now[0] * 1000) + 1)
        m = project(scenario, d)
        assert [s["decoded"] for s in e["samples"]] == [False] + [True] * (count - 1)
        assert m["reads"] == count and m["reads_ok"] == count - 1
        assert m["opens"] == 2 and m["cleanup"] and m["recovered"]
        assert m["reused"] is (scenario == "session-reuse")
        assert not m["completed"]  # A synthetic clock cannot attest a live run.
        assert observed_status("ha", scenario, {**m, "completed": True}) == "SUCCESS"
        assert first.write.await_count + fresh.write.await_count == count + 2
        assert e["diagnostic"]["first"] is not None
        assert e["diagnostic"]["cleanup"] is None
        assert_private_values_absent(str(d) + caplog.text)
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize("scenario,count", [("session-reuse", 3), ("availability", 2)])
@pytest.mark.parametrize("fault", [RuntimeError("PRIVATE_PAYLOAD"), b"\x05\x02"])
async def test_terminal_error_cannot_be_recovered_by_a_retained_value(
    hass, entry, peers, scenario, count, fault, freezer, caplog
):
    wire = peers.wire(DEVICE_GUID, [[fault]])
    peers.wire(DEVICE_GUID, [[RESPONSE]] * (count - 1))
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
        e = await observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
        m = project(scenario, detail(scenario, e, int(now[0] * 1000) + 1))
        assert not m["recovered"]
        assert observed_status("ha", scenario, {**m, "completed": True}) == "FAILURE"
        assert wire.write.await_count == 2
        assert peers.factory.call_count == 1 and m["reads_ok"] == 0
        assert e["diagnostic"]["first"] is not None
        assert_private_values_absent(str(e) + caplog.text)
    finally:
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize("scenario,count", [("session-reuse", 3), ("availability", 2)])
async def test_nominal_counts_and_reuse_are_unchanged(
    hass, entry, peers, scenario, count, freezer
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * count)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        freezer.tick(seconds)
        await pump()

    e = await observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
    m = project(scenario, detail(scenario, e, int(now[0] * 1000) + 1))
    assert m["reads"] == m["reads_ok"] == count and m["opens"] == 1
    assert m["reused"] and not m["recovered"] and m["cleanup"]
    assert observed_status("ha", scenario, {**m, "completed": True}) == "SUCCESS"
    assert wire.write.await_count == count + 1
    await coordinator.async_shutdown()
    assert_stopped(peers)


async def test_b7_retention_and_expiry_are_never_credited_as_new_reads(
    hass, entry, peers, monkeypatch, freezer
):
    from ha_tests.test_snapshot_hold_b7 import LocalClock
    from scripts.ha_campaign_evidence import empty
    from scripts.ha_campaign_observer import take_sample

    clock = LocalClock(monkeypatch, freezer)
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    e = empty("session-reuse")
    await take_sample(coordinator, e, lambda: clock.now, 0, require_fresh=True)
    stamp = coordinator.last_successful_read_at
    wire.queue.put_nowait(TransportEOF())
    await peers.backoff.entered.get()
    await clock.advance(299)
    await take_sample(coordinator, e, lambda: clock.now, 0, require_fresh=True)
    assert not e["samples"][-1]["decoded"] and e["samples"][-1]["available"]
    await clock.advance(1)
    await take_sample(coordinator, e, lambda: clock.now, 0, require_fresh=True)
    assert not e["samples"][-1]["decoded"] and not e["samples"][-1]["available"]
    assert coordinator.last_successful_read_at == stamp
    assert wire.write.await_count == 2 and peers.factory.call_count == 1
    # These UI-only checks beyond 120/180 s do not extend any live budget.
    await coordinator.async_shutdown()
    await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize("copy_data", [False, True])
async def test_success_flag_or_copied_snapshot_cannot_fake_freshness(
    hass, entry, peers, monkeypatch, copy_data
):
    from dataclasses import replace

    from scripts.ha_campaign_evidence import empty
    from scripts.ha_campaign_observer import take_sample

    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    e = empty("availability")
    await take_sample(coordinator, e, lambda: 0.0, 0, require_fresh=True)
    stamp = coordinator.last_successful_read_at

    async def stale():
        coordinator.last_update_success = True
        if copy_data:
            coordinator.data = replace(coordinator.data)

    monkeypatch.setattr(coordinator, "async_refresh", stale)
    await take_sample(coordinator, e, lambda: 60.0, 0, require_fresh=True)
    assert e["samples"][-1]["available"] and not e["samples"][-1]["decoded"]
    assert coordinator.last_successful_read_at == stamp and wire.write.await_count == 2
    await coordinator.async_shutdown()
    await client.async_close()
    assert_stopped(peers)


async def test_cancelled_collection_is_not_success_even_when_close_finishes(
    hass, entry, peers
):
    from scripts.ha_campaign_evidence import empty

    wire = peers.wire(DEVICE_GUID, [[]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    e = empty("hoben-live")
    task = asyncio.create_task(observe(coordinator, "availability", evidence=e))
    await pump()
    assert wire.write.await_count == 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    m = project("availability", detail("availability", e, 1000))
    assert not m["recovered"] and not m["completed"]
    assert observed_status("ha", "availability", m) == "FAILURE"
    await coordinator.async_shutdown()
    await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize("close_fault", ["error", "cancelled"])
async def test_failed_old_tls_cleanup_never_qualifies_as_recovered(
    hass, entry, peers, close_fault, caplog
):
    from custom_components.hoben.exceptions import HobenError
    from custom_components.hoben.transport import TransportError
    from scripts.ha_campaign_evidence import empty

    first = peers.wire(DEVICE_GUID, [[TransportEOF()]])
    first.close.side_effect = (
        TransportError("PRIVATE_PAYLOAD")
        if close_fault == "error"
        else asyncio.CancelledError()
    )
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    e = empty("hoben-live")
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        await pump()

    try:
        try:
            await observe(
                coordinator,
                "availability",
                evidence=e,
                clock=lambda: now[0],
                sleep=sleep,
            )
        except (HobenError, asyncio.CancelledError):
            pass
        assert peers.factory.call_count == 1
        assert e["diagnostic"]["cleanup"] is not None
        d = detail("availability", e, max(1, int(now[0] * 1000)))
        try:
            m = project("availability", d)
        except ValueError:
            pass  # An incomplete proof can only be refused.
        else:
            assert not m["cleanup"] and not m["recovered"]
            assert (
                observed_status("ha", "availability", {**m, "completed": True})
                == "FAILURE"
            )
        assert_private_values_absent(str(e) + caplog.text)
    finally:
        await coordinator.async_shutdown()
        try:
            await client.async_close()
        except (HobenError, asyncio.CancelledError):
            pass
    assert not any(
        t.get_name() in {"hoben-v4-rx", "hoben-v4-lifecycle"} and not t.done()
        for t in asyncio.all_tasks()
    )


async def test_utc_rollback_cannot_erase_a_proven_new_read(hass, entry, peers, freezer):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        freezer.tick(-600)
        await pump()

    e = await observe(coordinator, "availability", clock=lambda: now[0], sleep=sleep)
    assert all(s["decoded"] for s in e["samples"])
    m = project("availability", detail("availability", e, 60001))
    assert observed_status("ha", "availability", {**m, "completed": True}) == "SUCCESS"
    assert wire.write.await_count == 3
    await coordinator.async_shutdown()
    assert_stopped(peers)


@pytest.mark.parametrize("scenario,count", [("session-reuse", 3), ("availability", 2)])
async def test_idle_disconnect_between_successful_polls_is_explicit_recovery(
    hass, entry, peers, scenario, count, freezer
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]] * (count - 1))
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]
    lost = False

    async def sleep(seconds):
        nonlocal lost
        if not lost:
            now[0] += seconds / 2
            freezer.tick(seconds / 2)
            first.queue.put_nowait(TransportEOF())
            await peers.backoff.entered.get()
            now[0] += seconds / 2
            freezer.tick(seconds / 2)
            peers.backoff.release.put_nowait(None)
            lost = True
        else:
            now[0] += seconds
            freezer.tick(seconds)
        await pump()

    e = await observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
    m = project(scenario, detail(scenario, e, int(now[0] * 1000) + 1))
    assert all(s["decoded"] for s in e["samples"])
    assert [s["at_ms"] for s in e["samples"]] == list(range(0, count * 60000, 60000))
    assert m["recovered"] and m["reads"] == m["reads_ok"] == count
    assert m["reused"] is (scenario == "session-reuse")
    assert observed_status("ha", scenario, {**m, "completed": True}) == "SUCCESS"
    assert first.write.await_count + fresh.write.await_count == count + 2
    await coordinator.async_shutdown()
    assert_stopped(peers)


@pytest.mark.parametrize("scenario,count", [("session-reuse", 3), ("availability", 2)])
async def test_unsupported_protocol_opening_is_permanent_not_a_recovery(
    hass, entry, peers, scenario, count, freezer
):
    from ha_tests.test_persistent_client import opening
    from tests.tls_script import script_transport

    wire = peers.wire(DEVICE_GUID, [])
    prefix = bytearray(opening(DEVICE_GUID))
    prefix[8] = 99  # Unsupported product, synthetic.
    wire.queue = script_transport(wire, openings=[[bytes(prefix)]], reads=[])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        freezer.tick(seconds)
        await pump()

    e = await observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
    m = project(scenario, detail(scenario, e, int(now[0] * 1000) + 1))
    assert not m["recovered"] and m["reads_ok"] == 0
    assert observed_status("ha", scenario, {**m, "completed": True}) == "FAILURE"
    assert peers.factory.call_count == 1 and wire.write.await_count == 1
    await coordinator.async_shutdown()
    await client.async_close()
    assert_stopped(peers)


@pytest.mark.parametrize("scenario,count", [("session-reuse", 3), ("availability", 2)])
async def test_real_initial_tls_retry_preserves_all_successful_nominal_reads(
    hass, entry, peers, scenario, count, freezer
):
    from custom_components.hoben.transport import TransportTlsError

    first = peers.wire(DEVICE_GUID, [])
    first.connect.side_effect = TransportTlsError("PRIVATE_PAYLOAD")
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE]] * count)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        freezer.tick(seconds)
        await pump()

    task = asyncio.create_task(
        observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
    )
    try:
        delay = await peers.backoff.entered.get()
        now[0] += delay
        freezer.tick(delay)
        peers.backoff.release.put_nowait(None)
        e = await task
        m = project(scenario, detail(scenario, e, int(now[0] * 1000) + 1))
        assert all(s["decoded"] for s in e["samples"])
        assert m["reads"] == m["reads_ok"] == count and m["opens"] == 2
        assert not m["recovered"] and m["error"] == "none"
        assert observed_status("ha", scenario, {**m, "completed": True}) == "SUCCESS"
        assert e["diagnostic"]["first"] is not None
        assert [o["accepted"] for o in e["diagnostic"]["owners"]] == [False, True]
        assert first.write.await_count == 0 and fresh.write.await_count == count + 1
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await coordinator.async_shutdown()
        await client.async_close()
    assert_stopped(peers)
