"""Real HA owners, synthetic TLS/monotonic time; no live service access."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import TransportEOF
from ha_tests.test_manual_campaign_observer import detail
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.campaign_runtime_contract import observed_status, stage, validate_report
from scripts.ha_campaign_evidence import project
from scripts.ha_campaign_observer import observe
from scripts.ha_pong_injection import PongInjection
from tests.test_campaign_runtime import envelope, node_accepts


async def exercise(hass, entry, peers, case):
    first = peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    second = peers.wire(
        DEVICE_GUID, [[b"\xff" if case == "bad_read" else RESPONSE]] * 6
    )
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    original = v4_lifecycle.V4Lifecycle
    now = [0.0]
    loss_sent = released = second_loss = False
    pongs = {}

    async def sleep(delay):
        nonlocal loss_sent, released, second_loss
        now[0] += delay
        for _ in range(15):
            await asyncio.sleep(0)
        if (
            peers.backoff.delays
            and not released
            and now[0] >= (241 if case == "late_reopen" else 132)
        ):
            peers.backoff.release.put_nowait(None)
            released = True
        active = peers.wires[peers.factory.call_count - 1]
        if case != "no_ping" and not (active is second and case == "no_recovery_pong"):
            active.queue.put_nowait(b"\x0a")
        for _ in range(15):
            await asyncio.sleep(0)
        pongs[int(now[0])] = sum(
            c.args[0] == b"\x0b" for c in first.write.await_args_list
        )
        if (
            case not in {"no_ping", "no_loss"}
            and not loss_sent
            and now[0] >= (60 if case == "early_loss" else 130)
        ):
            first.queue.put_nowait(
                b"\x05\x07"
                if case == "close_client"
                else TransportEOF("PRIVATE_PAYLOAD")
            )
            loss_sent = True
        if (
            case == "second_loss"
            and active is second
            and now[0] >= 220
            and not second_loss
        ):
            second.queue.put_nowait(TransportEOF("PRIVATE_PAYLOAD"))
            second_loss = True
        for _ in range(15):
            await asyncio.sleep(0)

    evidence = await observe(
        coordinator, "session-reconnect", clock=lambda: now[0], sleep=sleep
    )
    assert v4_lifecycle.V4Lifecycle is original
    assert_stopped(peers)
    assert not any(
        t.get_name() == "hoben-dataupdated-probe" and not t.done()
        for t in asyncio.all_tasks()
    )
    return evidence, now[0], pongs, first, second


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "close_client",
        "no_ping",
        "no_loss",
        "early_loss",
        "late_reopen",
        "bad_read",
        "second_loss",
        "no_recovery_pong",
    ],
)
async def test_controlled_ha_reconnect_requires_each_causal_witness(
    hass, entry, peers, case, caplog
):
    e, elapsed, pongs, first, second = await exercise(hass, entry, peers, case)
    d = detail("session-reconnect", e, int(elapsed * 1000))
    m = project("session-reconnect", d)
    r = e["recovery"]
    success = case in {"success", "close_client"}
    assert m["recovered"] is success
    assert m["cleanup"] and m["reads"] <= 6 and m["opens"] <= 2
    assert elapsed <= 570
    assert not m["completed"]  # injected time can never become real proof
    s = stage(
        "ha",
        "session-reconnect",
        started=True,
        reason="observed",
        elapsed_ms=int(elapsed * 1000),
        metrics=m,
        detail=d,
    )
    report = envelope("ha", "session-reconnect", [s])
    assert validate_report(report) and node_accepts(report)
    if success:
        assert r["outcome"] == "verified" and r["stable_ms"] == 120000
        assert r["suppressed_pongs"] > 0 and r["recovery_pongs"] > 0
        assert r["loss_generation"] == 1 and r["read_generation"] == 2
        assert pongs[119] == 119 and pongs[120] == 119 and pongs[130] == 119
        assert all(
            c.args[0][0] in {3, 11, 13}
            for w in (first, second)
            for c in w.write.await_args_list
        )
        assert (
            observed_status("ha", "session-reconnect", {**m, "completed": True})
            == "SUCCESS"
        )
    else:
        assert r["outcome"] != "verified"
        assert (
            observed_status("ha", "session-reconnect", {**m, "completed": True})
            != "SUCCESS"
        )
        if case in {"early_loss", "late_reopen", "bad_read", "second_loss"}:
            assert not m["available"]
    assert_private_values_absent(str(d) + caplog.text)


async def test_cancel_restores_factory_and_stops_the_only_real_owner(
    hass, entry, peers
):
    wire = peers.wire(DEVICE_GUID, [[]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    original = v4_lifecycle.V4Lifecycle
    task = asyncio.create_task(observe(coordinator, "session-reconnect"))
    while wire.write.await_count < 2:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert v4_lifecycle.V4Lifecycle is original
    assert_stopped(peers)


@pytest.mark.parametrize("case", ["deadline", "clock_rollback"])
async def test_clock_and_original_deadline_bound_injection_and_cleanup(
    hass, entry, peers, case
):
    peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    original = v4_lifecycle.V4Lifecycle
    now = [0.0]

    async def sleep(delay):
        now[0] = now[0] + delay if case == "deadline" else -1
        await asyncio.sleep(0)

    e = await observe(
        coordinator,
        "session-reconnect",
        clock=lambda: now[0],
        sleep=sleep,
        absolute_end=100,
    )
    assert not e["completed"]
    assert e["terminal"] == ("timeout" if case == "deadline" else "unexpected")
    assert e["recovery"]["suppressed_pongs"] == 0
    assert v4_lifecycle.V4Lifecycle is original
    assert now[0] <= 60
    assert_stopped(peers)


async def test_production_policy_and_overlapping_injector_are_refused(entry, peers):
    original = v4_lifecycle.V4Lifecycle
    production = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    with pytest.raises(ValueError, match="campaign_contract_refused"):
        with PongInjection(lambda: 0, 600).install(production):
            pytest.fail("production HA policy must never be instrumented")
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    with PongInjection(lambda: 0, 600).install(client):
        other = HobenClient(entry.data["user_guid"], DEVICE_GUID)
        with pytest.raises(ValueError, match="campaign_contract_refused"):
            await other.async_refresh()
        with pytest.raises(ValueError, match="campaign_contract_refused"):
            with PongInjection(lambda: 0, 600).install(client):
                pytest.fail("overlap must be refused")
    assert v4_lifecycle.V4Lifecycle is original
    peers.factory.assert_not_called()
