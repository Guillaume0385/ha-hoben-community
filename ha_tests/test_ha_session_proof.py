"""C1 evidence over actual client/coordinator; all TLS peers are synthetic."""

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.session_observation import SessionObservation
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTlsError,
)
from ha_tests.ha_session_collector import OfflineHaSessionCollector
from ha_tests.test_persistent_client import RESPONSE, assert_stopped
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.ha_session_proof import encode_report, parse_report
from tests.test_ha_session_proof import node_accepts

PROVENANCE = {"merge_sha": "a" * 40, "pr_number": 1, "run_id": 2, "run_attempt": 1}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        self.now += delay
        await asyncio.sleep(0)


def collector(hass, entry, *, clock=None, sleep=None, read_timeout=30):
    clock = clock or Clock()
    client = HobenClient(
        entry.data["user_guid"], DEVICE_GUID, read_timeout=read_timeout
    )
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    return OfflineHaSessionCollector(
        coordinator, provenance=PROVENANCE, clock=clock, sleep=sleep or clock.sleep
    )


def assert_private(report, caplog):
    text = encode_report(report)
    assert parse_report(text) == report and len(text.encode()) <= 8192
    assert node_accepts(text)
    assert_private_values_absent(text + caplog.text)
    assert "synthetic-private" not in text + caplog.text
    assert report["execution"] == "offline"
    assert report["system_enforcement"] == "NOT RUN"
    assert report["boundary_proven"] is False


async def test_healthy_real_ha_path_one_tls_no_reconnection_claim(
    hass, entry, peers, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    run = collector(hass, entry)
    client = run.coordinator.client
    for _ in range(5):
        assert client.session_observation == SessionObservation()
    assert peers.factory.call_count == 0
    report = await run.collect()
    assert report["criteria"] == {
        "collection": "SUCCESS",
        "tls_reuse": "SUCCESS",
        "reconnection": "INCONCLUSIVE",
        "cleanup": "SUCCESS",
    }
    assert [s["observation"]["read_sequence"] for s in report["samples"]] == list(
        range(1, 7)
    )
    assert report["elapsed_ms"] == 250000
    assert peers.factory.call_count == 1
    assert [c.args[0][0] for c in wire.write.await_args_list] == [3] + [13] * 6
    assert run.coordinator.data.state is not None  # Actual HA semantic decode.
    before = client.session_observation
    for _ in range(5):
        assert client.session_observation == before
    with pytest.raises(FrozenInstanceError):
        before.attempts = 100
    assert_private(report, caplog)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "loss",
    [
        [b"\x05", b"\x03\x0a" + RESPONSE],
        [TransportEOF("synthetic-private")],
        [TransportTlsError("synthetic-private")],
    ],
)
async def test_observed_loss_cleanup_new_generation_and_correlated_ha_read(
    hass, entry, peers, loss, caplog
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE], loss])
    peers.wire(DEVICE_GUID, [[RESPONSE]] * 3)
    clock = Clock()

    async def sleep(delay):
        await clock.sleep(delay)
        if clock.now == 150:
            await peers.backoff.entered.get()
            peers.backoff.release.put_nowait(None)

    run = collector(hass, entry, clock=clock, sleep=sleep)
    report = await run.collect()
    assert all(v == "SUCCESS" for v in report["criteria"].values())
    samples = report["samples"]
    assert not samples[2]["decoded"]
    assert samples[3]["decoded"]
    o = samples[3]["observation"]
    assert (o["generation"], o["read_generation"], o["read_sequence"]) == (2, 2, 1)
    assert o["cleaned_generation"] == o["loss_generation"] == 1
    assert o["loss_kind"] == (
        "close_client" if isinstance(loss[0], bytes) else "transport"
    )
    assert o["close_client_subcode"] == (3 if isinstance(loss[0], bytes) else None)
    assert report["cleanup"]["observation"]["cleaned_generation"] == 2
    assert peers.factory.call_count == 2
    assert all(
        c.args[0][0] in {3, 11, 13}
        for w in peers.wires
        for c in w.write.await_args_list
    )
    assert_private(report, caplog)
    assert_stopped(peers)


@pytest.mark.parametrize("phase", ["opening", "tx", "rx", "backoff"])
async def test_cancel_propagates_after_cleanup_with_partial_failure_proof(
    hass, entry, peers, phase, caplog
):
    wire = peers.wire(
        DEVICE_GUID, [[RESPONSE], [b"\x05\x03"] if phase == "backoff" else []]
    )
    clock, entered = Clock(), asyncio.Event()
    previous = wire.write.side_effect

    async def write(packet):
        previous(packet)
        if packet[0] == 13 and wire.write.await_count == 3 and phase != "backoff":
            entered.set()
            if phase == "tx":
                await asyncio.Future()

    wire.write.side_effect = write
    if phase == "opening":

        async def connect():
            entered.set()
            await asyncio.Future()

        wire.connect.side_effect = connect

    async def sleep(delay):
        await clock.sleep(delay)
        if phase == "backoff" and clock.now == 100:
            await peers.backoff.entered.get()
            entered.set()
            await asyncio.Future()

    run = collector(hass, entry, clock=clock, sleep=sleep)
    task = asyncio.create_task(run.collect())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.report["criteria"]["collection"] == "FAILURE"
    assert run.report["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert run.report["criteria"]["cleanup"] == "SUCCESS"
    assert peers.factory.call_count == 1
    assert_private(run.report, caplog)
    assert_stopped(peers)


async def test_read_timeout_is_not_natural_loss_or_recovery(hass, entry, peers, caplog):
    peers.wire(DEVICE_GUID, [[]])
    run = collector(hass, entry, read_timeout=0.001)
    report = await run.collect()
    assert report["criteria"]["tls_reuse"] == "FAILURE"
    assert report["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert all(not s["decoded"] for s in report["samples"])
    assert all(s["observation"]["loss_kind"] is None for s in report["samples"])
    assert peers.factory.call_count == 1
    assert_private(report, caplog)
    assert_stopped(peers)


async def test_cleanup_error_cannot_be_reported_success(hass, entry, peers, caplog):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)
    wire.close.side_effect = TransportError("synthetic-private")
    run = collector(hass, entry)
    report = await run.collect()
    assert report["cleanup"]["observation"]["cleanup_failed"]
    assert report["criteria"]["cleanup"] == "FAILURE"
    assert_private(report, caplog)
    assert_stopped(peers)


async def test_correlated_wire_read_without_ha_decode_is_not_success(
    hass, entry, peers, caplog, monkeypatch
):
    peers.wire(DEVICE_GUID, [[RESPONSE]] * 6)

    def rejected_decode(snapshot):
        raise ValueError("synthetic-private")

    monkeypatch.setattr(
        "custom_components.hoben.coordinator.decode_v4_snapshot", rejected_decode
    )
    run = collector(hass, entry)
    report = await run.collect()
    assert all(not s["decoded"] for s in report["samples"])
    assert report["samples"][-1]["observation"]["read_sequence"] == 6
    assert run.coordinator.data is None
    assert report["criteria"]["tls_reuse"] == report["outcome"] == "FAILURE"
    assert_private(report, caplog)
    assert_stopped(peers)


async def test_absolute_window_cuts_off_before_next_slot_without_more_io(
    hass, entry, peers, caplog
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE]])
    clock = Clock()

    async def sleep(delay):
        await clock.sleep(0 if clock.now == 0 and delay == 0 else 300)

    run = collector(hass, entry, clock=clock, sleep=sleep)
    report = await run.collect()
    assert len(report["samples"]) == 1 and report["elapsed_ms"] == 300000
    assert report["criteria"]["collection"] == "FAILURE"
    assert wire.write.await_count == 2
    assert_private(report, caplog)
    assert_stopped(peers)
