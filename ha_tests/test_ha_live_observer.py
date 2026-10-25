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
    task = asyncio.create_task(
        observe(coordinator, sleep=lambda _: asyncio.sleep(0), evidence=evidence)
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
