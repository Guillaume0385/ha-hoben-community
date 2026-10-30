"""Real HA/client/coordinator over deterministic in-memory TLS peers only."""

import asyncio
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID
from custom_components.hoben.transport import TransportEOF
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.campaign_runtime_contract import (
    HA_CHOICES,
    ha_limits,
    observed_status,
    stage,
    validate_report,
)
from scripts.ha_campaign_evidence import project, validate_detail
from scripts.ha_campaign_observer import SCHEDULES, observe
from scripts.ha_session_live_worker import collect
from scripts.run_campaign import identity
from tests.test_campaign_runtime import envelope, node_accepts
from tests.test_ha_live_proof import receipt
from tests.tls_script import script_transport


def detail(scenario, evidence, elapsed):
    limits = ha_limits(scenario)
    return {
        "supervisor": receipt(
            memory_bytes=limits.memory_bytes,
            pids=limits.pids,
            useful_ms=limits.useful_ms,
            process_ms=limits.process_ms,
            elapsed_ms=elapsed,
            network="fixed_tls",
        ),
        "evidence": evidence,
    }


@pytest.mark.parametrize("scenario", HA_CHOICES[:-1])
async def test_every_scenario_uses_actual_persistent_client_and_coordinator(
    hass, entry, peers, scenario, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(delay):
        now[0] += delay
        for _ in range(10):
            await asyncio.sleep(0)

    evidence = await observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
    expected = (
        6
        if scenario == "hoben-live"
        else 4
        if scenario == "session-reconnect"
        else len(SCHEDULES[scenario])
    )
    assert len(evidence["samples"]) == expected and all(
        s["decoded"] for s in evidence["samples"]
    )
    assert evidence["completed"] and evidence["cleanup"]["completed"]
    d = detail(scenario, evidence, max(1000, int(now[0] * 1000)))
    validate_detail(scenario, d)
    m = project(scenario, d)
    assert m["reads_ok"] == expected and m["opens"] == 1 and m["cleanup"]
    assert not m["completed"]  # synthetic timing cannot be published as live proof
    assert not m["recovered"]
    if scenario in {"hoben-live", "session-reuse"}:
        assert m["reused"]
    if scenario == "hoben-live":
        assert evidence["window"]["elapsed_ms"] == 300000
    assert wire.write.await_count == expected + 1  # one OpenClient, read-only reads
    value = stage(
        "ha",
        scenario,
        started=True,
        reason="observed",
        elapsed_ms=d["supervisor"]["elapsed_ms"],
        metrics=m,
        detail=d,
    )
    report = envelope("ha", scenario, [value])
    assert validate_report(report) and node_accepts(report)
    assert_private_values_absent(str(d) + caplog.text)
    assert_stopped(peers)


@pytest.mark.parametrize("loss", [TransportEOF("PRIVATE_PAYLOAD"), b"\x05\x07"])
async def test_loss_before_test_inhibition_cannot_attest_controlled_reconnection(
    hass, entry, peers, loss, caplog
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [loss]])
    peers.wire(DEVICE_GUID, [[RESPONSE]] * 4)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]
    released = False

    async def sleep(delay):
        nonlocal released
        now[0] += delay
        if now[0] >= 200 and not released:
            await peers.backoff.entered.get()
            peers.backoff.release.put_nowait(None)
            released = True
        for _ in range(20):
            await asyncio.sleep(0)

    evidence = await observe(
        coordinator, "session-reconnect", clock=lambda: now[0], sleep=sleep
    )
    d = detail("session-reconnect", evidence, int(now[0] * 1000))
    m = project("session-reconnect", d)
    assert not m["recovered"] and m["cleanup"]
    assert evidence["recovery"]["outcome"] == "not_exercised"
    assert evidence["recovery"]["suppressed_pongs"] == 0
    assert evidence["samples"][1]["decoded"] is False
    assert evidence["samples"][-1]["decoded"] is False
    assert m["loss_kind"] == (
        "transport" if isinstance(loss, Exception) else "close_client"
    )
    assert m["close_client_subcode"] == (None if isinstance(loss, Exception) else 7)
    assert_private_values_absent(str(d) + caplog.text)
    assert_stopped(peers)


async def test_late_loss_without_another_read_is_not_recovery(hass, entry, peers):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(delay):
        now[0] += delay
        if now[0] >= 239:
            wire.queue.put_nowait(TransportEOF("PRIVATE_PAYLOAD"))
        for _ in range(20):
            await asyncio.sleep(0)

    evidence = await observe(
        coordinator, "session-reconnect", clock=lambda: now[0], sleep=sleep
    )
    m = project(
        "session-reconnect", detail("session-reconnect", evidence, int(now[0] * 1000))
    )
    assert m["loss_kind"] == "transport" and not m["recovered"] and m["cleanup"]
    assert_stopped(peers)


@pytest.mark.parametrize("scenario", ["refresh-v4", "availability"])
async def test_earlier_real_read_error_is_not_erased_by_later_coordinator_success(
    hass, entry, peers, scenario, caplog
):
    peers.wire(DEVICE_GUID, [[TransportEOF("PRIVATE_PAYLOAD")]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(delay):
        now[0] += delay
        if now[0] >= 60:
            await peers.backoff.entered.get()
            peers.backoff.release.put_nowait(None)
        for _ in range(20):
            await asyncio.sleep(0)

    e = await observe(coordinator, scenario, clock=lambda: now[0], sleep=sleep)
    assert [s["decoded"] for s in e["samples"]] == [False, True]
    d = detail(scenario, e, int(now[0] * 1000))
    m = project(scenario, d)
    assert m["error"] == "none" and m["available"] and m["cleanup"]
    # Even with completion separately attested, these samples cannot validate
    # an ordinary two-refresh scenario. Synthetic timing itself stays non-live.
    assert not m["completed"]
    assert observed_status("ha", scenario, {**m, "completed": True}) == "FAILURE"
    assert_private_values_absent(str(d) + caplog.text)
    assert_stopped(peers)


async def test_clock_rollback_refuses_proof_and_still_closes_client(hass, entry, peers):
    peers.wire(DEVICE_GUID, [[RESPONSE]] * 3)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now = [0.0]

    async def sleep(_):
        now[0] = -1.0
        await asyncio.sleep(0)

    evidence = await observe(
        coordinator, "session-reuse", clock=lambda: now[0], sleep=sleep
    )
    assert not evidence["completed"] and evidence["terminal"] == "unexpected"
    assert evidence["cleanup"]["completed"]
    assert_stopped(peers)


async def test_legitimate_open_read_error_is_categorical_without_invalid_credentials(
    hass, entry, peers, caplog
):
    wire = peers.wire(DEVICE_GUID, [[TransportEOF("PRIVATE_PAYLOAD")]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    evidence = await observe(
        coordinator, "open-errors", clock=lambda: 0.0, sleep=asyncio.sleep
    )
    d = detail("open-errors", evidence, 1000)
    m = project("open-errors", d)
    assert m["reads_ok"] == 0 and m["error"] == "transport" and m["cleanup"]
    assert evidence["samples"][0]["error"] == "transport"
    assert wire.write.await_count == 2
    assert_private_values_absent(str(d) + caplog.text)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "scenario", ["refresh-v4", "session-reuse", "cleanup", "availability"]
)
async def test_cancel_during_actual_read_cleans_up_without_completed_proof(
    hass, entry, peers, scenario
):
    wire = peers.wire(DEVICE_GUID, [[]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    task = asyncio.create_task(
        observe(coordinator, scenario, clock=lambda: 0.0, sleep=asyncio.sleep)
    )
    while wire.write.await_count < 2:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_stopped(peers)


@pytest.mark.parametrize("scenario", HA_CHOICES[:-1])
@pytest.mark.parametrize("device", [INITIAL_DEVICE_GUID, DEVICE_GUID])
async def test_campaign_adapter_reuses_bare_ha_bootstrap(
    peers, monkeypatch, scenario, device, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", Mock())
    now = [0.0]

    async def sleep(delay):
        now[0] += delay
        await asyncio.sleep(0)

    async def observer(coordinator, **kwargs):
        evidence = await observe(
            coordinator, scenario, clock=lambda: now[0], sleep=sleep, **kwargs
        )
        assert coordinator.client.device_guid_for_persistence == DEVICE_GUID
        assert coordinator.config_entry.data["device_guid"] == DEVICE_GUID
        return evidence

    evidence = await collect(
        {"user_guid": "a" * 32, "device_guid": device},
        allow_initial_identity=True,
        observer=observer,
    )
    assert evidence["completed"] and evidence["cleanup"]["completed"]
    assert wire.write.await_args_list[0].args[0][37:69] == device.encode()
    assert [c.args[0][0] for c in wire.write.await_args_list] == [3] + [13] * len(
        evidence["samples"]
    )
    assert_private_values_absent(str(evidence) + caplog.text)
    assert_stopped(peers)


async def test_legacy_worker_keeps_its_persisted_identity_requirement(peers):
    with pytest.raises(ValueError, match="persisted identity required"):
        await collect({"user_guid": "a" * 32, "device_guid": INITIAL_DEVICE_GUID})
    peers.factory.assert_not_called()


async def test_initial_campaign_identity_challenge_never_sends_association(
    hass, entry, peers, caplog
):
    wire = peers.wire(DEVICE_GUID, [])
    wire.queue = script_transport(wire, openings=[[b"\x2f"]])
    client = HobenClient(**identity({"HOBEN_USER_GUID": "b" * 32}))
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    evidence = await observe(
        coordinator, "open-errors", clock=lambda: 0.0, sleep=asyncio.sleep
    )
    assert evidence["cleanup"]["completed"]
    assert evidence["samples"][0]["error"] == "authorization"
    metrics = project("open-errors", detail("open-errors", evidence, 1000))
    assert metrics["error"] == "authorization" and metrics["reads_ok"] == 0
    assert observed_status("ha", "open-errors", metrics) == "FAILURE"
    assert [c.args[0][0] for c in wire.write.await_args_list] == [3]
    assert wire.write.await_args_list[0].args[0][37:69] == b"0" * 32
    assert_private_values_absent(str(evidence) + caplog.text)
    assert "b" * 32 not in str(evidence) + caplog.text
    assert_stopped(peers)
