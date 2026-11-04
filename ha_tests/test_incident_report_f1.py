"""HA-F1 observes real owners through synthetic transports and a virtual clock."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTlsError,
)
from ha_tests.test_dual_session_033 import Clock
from ha_tests.test_manual_campaign_observer import detail
from ha_tests.test_persistent_client import RESPONSE
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.campaign_runtime_contract import stage, validate_report
from scripts.ha_campaign_evidence import empty, project, validate_detail
from scripts.ha_campaign_observer import observe
from tests.test_campaign_runtime import envelope, node_accepts


@pytest.mark.parametrize("case", ["early_race", "observer_cleanup_timeout"])
async def test_frozen_failure_report_survives_worker_close_or_constructor_refusal(
    hass, entry, peers, monkeypatch, case
):
    from unittest.mock import Mock

    from ha_tests.test_ha_controlled_reconnect import exercise

    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", Mock())
    e, elapsed, _, _, _ = await exercise(hass, entry, peers, case, worker=True)
    d = e["diagnostic"]
    assert d["first"][3] == ("protocol" if case == "early_race" else "eof")
    if case == "early_race":
        row = d["owners"][-1]
        assert row["stage"] == "construction_failed" and not row["accepted"]
        assert row["pending"] is None and row["close"] == [None] * 4
    else:
        assert d["terminal"][3:6] == ["timeout", "cleanup", "observer"]
        assert d["cleanup"][3:6] == ["timeout", "cleanup", "observer"]
        # Worker shutdown actually closed this transport, after collection.
        assert peers.wires[1].close.await_count == 1
        assert d["owners"][1]["close"] == [None] * 4
    value = detail("session-reconnect", e, int(elapsed * 1000))
    metrics = project("session-reconnect", value)
    result = envelope(
        "ha",
        "session-reconnect",
        [
            stage(
                "ha",
                "session-reconnect",
                started=True,
                reason="observed",
                elapsed_ms=value["supervisor"]["elapsed_ms"],
                metrics=metrics,
                detail=value,
            )
        ],
    )
    assert validate_report(result) and node_accepts(result)
    assert result["stages"][0]["status"] == "FAILURE"


@pytest.mark.parametrize("failed_close", [False, True])
@pytest.mark.parametrize("ha_policy", [False, True])
async def test_first_timeout_is_not_replaced_by_cleanup_or_later_poll(
    hass, entry, peers, freezer, failed_close, caplog, ha_policy
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    if failed_close:
        wire.close.side_effect = TransportError("PRIVATE_PAYLOAD")
    client = HobenClient(
        entry.data["user_guid"], DEVICE_GUID, max_attempts=1, ha_reconnect=ha_policy
    )
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    clock = Clock(freezer)
    task = asyncio.create_task(
        observe(
            coordinator, "session-reuse", clock=lambda: clock.now, sleep=clock.sleep
        )
    )
    e = await clock.drive(task)
    assert e["diagnostic_schema"] == 1
    d = e["diagnostic"]
    assert d["first"][0:2] == ["a", 1]
    assert d["first"][3:5] == ["timeout", "request_correlation"]
    if ha_policy and not failed_close:
        assert d["terminal"] is None  # Backoff followed by deliberate observer stop.
    else:
        assert d["terminal"][3] == (
            "cleanup_failed"
            if ha_policy
            else "timeout"
            if failed_close
            else "exhausted"
        )
    assert (d["cleanup"] is not None) == failed_close
    assert (
        d["owners"][0]["close"][3] is None
        if failed_close
        else d["owners"][0]["close"][3] is not None
    )
    assert d["owners"][0]["last_read"][0] == 1
    assert d["owners"][0]["last_read"][2] >= 120000
    assert_valid_report(e, clock)
    assert_private_values_absent(str(e) + caplog.text)


def assert_valid_report(e, clock):
    value = detail("session-reuse", e, int((clock.now - 1000) * 1000))
    assert validate_detail("session-reuse", value)
    metrics = project("session-reuse", value)
    result = envelope(
        "ha",
        "session-reuse",
        [
            stage(
                "ha",
                "session-reuse",
                started=True,
                elapsed_ms=value["supervisor"]["elapsed_ms"],
                reason="observed",
                metrics=metrics,
                detail=value,
            )
        ],
    )
    assert validate_report(result) and node_accepts(result)
    assert result["stages"][0]["status"] == "FAILURE"


@pytest.mark.parametrize(
    "fault,expected,phase",
    [
        ([TransportEOF("PRIVATE_PAYLOAD")], "eof", "tls_read"),
        ([b"\x05", b"\x03"], "close_client", "post_open"),
        ([TransportTlsError("PRIVATE_PAYLOAD")], "tls", "tls_read"),
        ([RuntimeError("PRIVATE_PAYLOAD")], "internal", "tls_read"),
        ([b"\xfePRIVATE_PAYLOAD"], "protocol", "message_classification"),
    ],
)
async def test_owner_origin_is_typed_without_inventing_a_server_cause(
    hass, entry, peers, freezer, fault, expected, phase, caplog
):
    peers.wire(DEVICE_GUID, [[RESPONSE], fault])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, max_attempts=1)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    clock = Clock(freezer)
    task = asyncio.create_task(
        observe(
            coordinator, "session-reuse", clock=lambda: clock.now, sleep=clock.sleep
        )
    )
    e = await clock.drive(task)
    first = e["diagnostic"]["first"]
    assert first[3:5] == [expected, phase]
    assert first[6] == (3 if expected == "close_client" else None)
    assert e["diagnostic"]["owners"][0]["last_read"][0] == 1
    assert_valid_report(e, clock)
    assert "message_type_byte" not in str(e)
    assert_private_values_absent(str(e) + caplog.text)


@pytest.mark.parametrize("during_close", [False, True])
async def test_cancel_is_local_and_does_not_replace_an_earlier_timeout(
    hass, entry, peers, freezer, caplog, during_close
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    closing = asyncio.Event()

    async def close():
        closing.set()
        await asyncio.Future()

    if during_close:
        wire.close.side_effect = close
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, max_attempts=1)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    clock, e = Clock(freezer), empty("hoben-live")
    task = asyncio.create_task(
        observe(
            coordinator,
            "session-reuse",
            evidence=e,
            clock=lambda: clock.now,
            sleep=clock.sleep,
        )
    )
    driver = asyncio.create_task(clock.drive(task))
    try:
        if during_close:
            await closing.wait()
        else:
            while wire.write.await_count < 3:
                await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await driver
        d = e["diagnostic"]
        assert d["first"][3] == ("timeout" if during_close else "cancelled")
        assert (d["cleanup"] is not None) == during_close
        if during_close:
            assert d["cleanup"][3:6] == ["cancelled", "cleanup", "transport_close"]
            assert d["owners"][0]["close"][3] is None
        assert d["owners"][0]["last_read"][0] == 1
        assert_valid_report(e, clock)
        assert len(peers.lifecycles) == 1 and peers.factory.call_count == 1
        assert not any(
            t.get_name() == "hoben-v4-rx" and not t.done() for t in asyncio.all_tasks()
        )
        assert_private_values_absent(str(e) + caplog.text)
    finally:
        if not driver.done():
            task.cancel()
            driver.cancel()
            await asyncio.gather(task, driver, return_exceptions=True)
        await client.async_close()


async def test_failed_initial_open_keeps_attempt_separate_from_accepted_generation(
    hass, entry, peers, freezer
):
    first = peers.wire(DEVICE_GUID, [])
    first.connect.side_effect = TransportError("PRIVATE_PAYLOAD")
    peers.wire(DEVICE_GUID, [[RESPONSE]] * 3)
    peers.backoff.release.put_nowait(None)
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    clock = Clock(freezer)
    task = asyncio.create_task(
        observe(
            coordinator, "session-reuse", clock=lambda: clock.now, sleep=clock.sleep
        )
    )
    e = await clock.drive(task)
    a, b = e["diagnostic"]["owners"]
    assert (a["generation"], a["accepted"], a["accepted_generation"]) == (
        1,
        False,
        None,
    )
    assert (b["generation"], b["accepted"], b["accepted_generation"]) == (2, True, 1)
    assert a["last_read"] is None and b["last_read"][0] == 3
    assert e["diagnostic"]["first"][3:5] == ["transport", "opening"]
    assert_valid_report(e, clock)
