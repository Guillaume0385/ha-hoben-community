"""R5: actual HA/client/session owners, byte peers and monotonic time only."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportError,
    TransportTimeout,
)
from ha_tests.test_manual_campaign_observer import detail
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.campaign_runtime_contract import validate_report
from scripts.ha_campaign_evidence import project
from scripts.ha_campaign_observer import observe
from tests.test_campaign_runtime import node_accepts
from tests.test_ha_controlled_evidence import report


@pytest.fixture(autouse=True)
def private_logs(caplog):
    yield
    assert_private_values_absent(caplog.text)
    assert "PRIVATE" not in caplog.text


async def exercise(
    hass,
    entry,
    peers,
    losses,
    *,
    close_failure=None,
    failed_open=False,
    absolute_end=None,
    last_reopen_delay=2,
    clock_tick=0,
    raced_retry=False,
    cancel_close=False,
):
    wires = [peers.wire(DEVICE_GUID, [[RESPONSE]] * 6) for _ in range(3)]
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    now, sent, released = [0.0], set(), set()
    if close_failure is not None:
        wires[close_failure - 1].close.side_effect = TransportError("PRIVATE")
    if failed_open:
        wires[1].connect.side_effect = TransportCertificateError("PRIVATE")
    if cancel_close:
        wires[2].close.side_effect = asyncio.CancelledError("PRIVATE")

    def clock():
        now[0] += clock_tick
        return now[0]

    async def sleep(delay):
        now[0] += delay
        for _ in range(20):
            await asyncio.sleep(0)
        for index, (at, kind) in enumerate(losses):
            if now[0] >= at and index not in sent and peers.factory.call_count > index:
                wires[index].queue.put_nowait(
                    {
                        "close_client": b"\x05\x03",
                        "auth": b"\x05\x02",
                        "internal": RuntimeError("PRIVATE"),
                        "timeout": TransportTimeout("PRIVATE"),
                        "protocol": b"\xff",
                    }.get(kind, TransportEOF("PRIVATE"))
                )
                sent.add(index)
                if raced_retry:
                    peers.backoff.release.put_nowait(None)
                    released.add(index)
            if (
                now[0] >= at + (last_reopen_delay if index else 2)
                and index in sent
                and index not in released
            ):
                peers.backoff.release.put_nowait(None)
                released.add(index)
        if peers.factory.call_count:
            wires[peers.factory.call_count - 1].queue.put_nowait(b"\x0a")
        for _ in range(20):
            await asyncio.sleep(0)

    e = await observe(
        coordinator,
        "session-reconnect",
        clock=clock,
        sleep=sleep,
        absolute_end=absolute_end,
    )
    assert_stopped(peers)
    d = detail("session-reconnect", e, int(now[0] * 1000))
    r = report(d)
    assert validate_report(r) and node_accepts(r)
    assert peers.factory.call_count <= 3 and len(e["samples"]) <= 6 and now[0] <= 570
    assert "PRIVATE" not in str(e)
    return e, now[0]


@pytest.mark.parametrize(
    "losses",
    [[(130, "close_client"), (220, "eof")], [(130, "eof"), (220, "close_client")]],
)
async def test_every_recovery_and_last_stability_are_proven(
    hass, entry, peers, losses, caplog
):
    e, elapsed = await exercise(hass, entry, peers, losses)
    m = project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )
    assert m["recovered"] and m["cleanup"] and m["opens"] == 3
    assert elapsed >= losses[-1][0] + 2 + 120
    assert e["recovery"]["schema"] == 2
    assert len(e["recovery"]["generations"]) == 3
    assert all(
        o["stage"] == "reaped" and o["pending"] == 0 for o in e["diagnostic"]["owners"]
    )
    assert_private_values_absent(str(e) + caplog.text)


@pytest.mark.parametrize(
    "losses",
    [
        [],
        [(130, "eof")],
        [(130, "close_client"), (220, "timeout")],
        [(130, "eof"), (220, "close_client"), (280, "eof")],
        [(60, "eof")],
        [(130, "eof"), (133, "eof")],
    ],
)
async def test_zero_one_three_and_unprovable_recoveries_are_distinguished(
    hass, entry, peers, losses
):
    e, elapsed = await exercise(hass, entry, peers, losses)
    m = project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )
    expected = losses in [[(130, "eof")], [(130, "close_client"), (220, "timeout")]]
    assert m["recovered"] is expected
    if len(losses) == 3:
        assert peers.factory.call_count == 3  # No fourth opening/budget extension.
    if losses == [(60, "eof")]:
        assert peers.factory.call_count == 1  # Inhibition stays first-generation-only.


@pytest.mark.parametrize("generation", [1, 2, 3])
async def test_cleanup_failure_cannot_be_recertified_or_open_another_tls(
    hass, entry, peers, generation
):
    e, elapsed = await exercise(
        hass, entry, peers, [(130, "eof"), (220, "eof")], close_failure=generation
    )
    m = project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )
    assert m["recovered"] is (generation == 3)
    assert not m["cleanup"]
    assert peers.factory.call_count == generation
    assert e["diagnostic"]["cleanup"] is not None


@pytest.mark.parametrize("case", ["auth", "internal", "protocol", "opening", "budget"])
async def test_permanent_error_and_budget_cannot_be_turned_into_recovery(
    hass, entry, peers, case
):
    e, elapsed = await exercise(
        hass,
        entry,
        peers,
        [(130, "eof")] if case == "budget" else [(130, "eof"), (220, case)],
        failed_open=case == "opening",
        absolute_end=280 if case == "budget" else None,
    )
    m = project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )
    assert not m["recovered"]
    assert peers.factory.call_count <= 2


async def test_late_final_reopening_cannot_extend_time_or_read_quota(
    hass, entry, peers
):
    e, elapsed = await exercise(
        hass, entry, peers, [(130, "eof"), (220, "eof")], last_reopen_delay=240
    )
    m = project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )
    assert not m["recovered"] and elapsed == 570 and m["reads"] == 6


async def test_fractional_clock_preserves_one_origin_and_quantized_intervals(
    hass, entry, peers
):
    e, elapsed = await exercise(
        hass, entry, peers, [(130, "eof"), (220, "close_client")], clock_tick=0.0007
    )
    assert project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )["recovered"]


async def test_raced_fatal_retry_cannot_open_an_extra_tls(hass, entry, peers):
    e, elapsed = await exercise(
        hass, entry, peers, [(130, "eof"), (220, "protocol")], raced_retry=True
    )
    m = project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )
    assert not m["recovered"] and peers.factory.call_count == 2


async def test_third_transport_cancelled_close_remains_failure(hass, entry, peers):
    e, elapsed = await exercise(
        hass, entry, peers, [(130, "eof"), (220, "eof")], cancel_close=True
    )
    m = project(
        "session-reconnect", detail("session-reconnect", e, int(elapsed * 1000))
    )
    assert m["recovered"] and not m["cleanup"]
    assert e["recovery"]["diagnostic"]["cleanup"]["category"] == "cancelled"
