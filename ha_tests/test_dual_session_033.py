"""#033: actual timeout ownership over synthetic transports and clocks only."""

import asyncio

import pytest
from conftest import DEVICE_GUID, assert_private_values_absent
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.exceptions import HobenTimeoutError
from custom_components.hoben.safe_reports import safe_error_report, wrap_error
from custom_components.hoben.transport import TransportEOF, TransportError
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, opening
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from scripts.ha_dual_evidence import continuous, empty, recovered, validate_detail
from scripts.ha_dual_instrumentation import category
from scripts.ha_dual_observer import observe
from tests.test_data_updated_silence import pump
from tests.test_ha_live_proof import receipt
from tests.tls_script import script_transport


class Clock:
    """Advance the same monotonic clock as asyncio's real deadline handles."""

    def __init__(self, freezer):
        self.now = 1000.0
        self.freezer = freezer
        self.pending = []

    async def sleep(self, seconds):
        future = asyncio.get_running_loop().create_future()
        self.pending.append((self.now + seconds, future))
        try:
            await future
        finally:
            self.pending = [(at, f) for at, f in self.pending if f is not future]

    async def drive(self, task):
        for _ in range(901):
            await pump()
            if task.done():
                return await task
            self.now += 1
            self.freezer.tick(1)
            for at, future in self.pending:
                if at <= self.now and not future.done():
                    future.set_result(None)
        raise AssertionError("synthetic global budget exceeded")


async def exercise033(
    hass,
    entry,
    peers,
    freezer,
    monkeypatch,
    *,
    kind="silence",
    cleanup=None,
    b_offset=0,
    write_delay=0,
    absolute_end=None,
):
    clock = Clock(freezer)

    def owner(**options):
        options["sleep"] = clock.sleep
        result = V4Lifecycle(**options)
        peers.lifecycles.append(result)
        return result

    monkeypatch.setattr("custom_components.hoben.v4_lifecycle.V4Lifecycle", owner)
    intact = kind in {"b_only", "delimited"}
    first = peers.wire(
        DEVICE_GUID,
        [[RESPONSE]] * 6
        + (
            [[b"\x07\xff\xff\x00\x00\x00\x02\x01\x04" + RESPONSE]] + [[RESPONSE]] * 7
            if kind == "delimited"
            else [[RESPONSE]] * 8
            if intact
            else [[]] + [[RESPONSE]] * 7
        ),
    )
    b = peers.wire(DEVICE_GUID, [[RESPONSE]])
    fresh = peers.wire(DEVICE_GUID, [[RESPONSE[:10] + b"\x00\x22" * 20]] * 10)
    if kind == "fresh_auth":
        fresh.queue = script_transport(fresh, openings=[[b"\x2f"]])
    if kind == "fresh_internal":
        fresh.queue = script_transport(
            fresh,
            openings=[[opening(DEVICE_GUID)]],
            reads=[[RuntimeError("PRIVATE_PAYLOAD")]],
        )
    monkeypatch.setattr("scripts.ha_dual_observer.AsyncTlsTransport", peers.factory)
    deliveries = []
    if kind in {"late", "fragmented", "stale"} or write_delay:
        original = first.write.side_effect
        requests = 0

        async def write(data):
            nonlocal requests
            if data[0] == 13:
                requests += 1
                if requests == 7 and write_delay:
                    await clock.sleep(write_delay)
            original(data)
            if data[0] == 13:
                if requests == 7 and kind in {"late", "fragmented", "stale"}:

                    async def deliver():
                        await clock.sleep(31 if kind == "stale" else 29)
                        chunks = (
                            [RESPONSE[:5], RESPONSE[5:]]
                            if kind == "fragmented"
                            else [RESPONSE]
                        )
                        for chunk in chunks:
                            first.queue.put_nowait(chunk)
                            await asyncio.sleep(0)

                    deliveries.append(asyncio.create_task(deliver()))

        first.write.side_effect = write

    if cleanup is not None:

        async def close_a():
            if cleanup == "slow":
                await clock.sleep(2)
            elif cleanup == "timeout":
                await clock.sleep(1000)
            elif cleanup == "cancelled":
                raise asyncio.CancelledError()
            else:
                raise TransportError("PRIVATE_PAYLOAD")

        first.close.side_effect = close_a

    async def close_b():
        if b_offset:
            await clock.sleep(b_offset)
        faults = {
            "close_client": [b"\x05", b"\x03"],
            "eof": [TransportEOF("PRIVATE_PAYLOAD")],
            "auth": [b"\x05\x04"],
            "internal": [RuntimeError("PRIVATE_PAYLOAD")],
            "unknown": [b"\xff"],
            "partial": [b"\x05", TransportEOF("PRIVATE_PAYLOAD")],
        }
        for fault in faults.get(kind, []):
            first.queue.put_nowait(fault)
            await asyncio.sleep(0)
        await clock.sleep(2)

    b.close.side_effect = close_b
    client = HobenClient(
        entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True, max_attempts=1
    )
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    e = empty()
    task = asyncio.create_task(
        observe(
            coordinator,
            evidence=e,
            clock=lambda: clock.now,
            sleep=clock.sleep,
            absolute_end=absolute_end,
        )
    )
    if kind == "b_only":

        async def close_from_server_b():
            await clock.sleep(359)
            b.queue.put_nowait(b"\x05\x03")

        deliveries.append(asyncio.create_task(close_from_server_b()))
    if kind in {"idle_close", "idle_eof"}:

        async def idle_loss():
            await clock.sleep(359)
            first.queue.put_nowait(
                b"\x05\x03" if kind == "idle_close" else TransportEOF("PRIVATE_PAYLOAD")
            )

        deliveries.append(asyncio.create_task(idle_loss()))
    if kind == "stop":

        async def stop():
            await clock.sleep(370)
            task.cancel()

        deliveries.append(asyncio.create_task(stop()))
    try:
        try:
            await clock.drive(task)
        except asyncio.CancelledError:
            assert kind == "stop"
        validate_detail(
            {
                "supervisor": receipt(
                    process_ms=900000,
                    useful_ms=None,
                    elapsed_ms=900000,
                    network="fixed_tls",
                ),
                "evidence": e,
            }
        )
        if recovered(e):
            assert coordinator.data.raw.registers == (34,) * 20
        return e, first, b, fresh
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for child in deliveries:
            child.cancel()
        await asyncio.gather(*deliveries, return_exceptions=True)
        coordinator._async_unsub_refresh()
        await client.async_close()
        assert_stopped(peers)


@pytest.mark.parametrize("kind", ["silence", "close_client", "eof", "stale"])
@pytest.mark.parametrize("b_offset", [0, 1])
async def test_seventh_read_interruption_has_role_and_safe_recovery(
    hass, entry, peers, freezer, monkeypatch, caplog, kind, b_offset
):
    e, first, _, _ = await exercise033(
        hass, entry, peers, freezer, monkeypatch, kind=kind, b_offset=b_offset
    )
    assert e["completed"] and recovered(e) and not continuous(e), (
        e["incident"],
        e["failure"],
        e["terminal"],
        [(r["scheduled_ms"], r["decoded"], r["error"]) for r in e["reads"]],
    )
    assert not e["reads"][6]["decoded"] and e["reads"][6]["attempted"]
    f = e["incident"]
    assert f["role"] == "a" and f["generation"] == 1
    assert f["kind"] == ("timeout" if kind in {"silence", "stale"} else kind)
    assert f["subcode"] == (3 if kind == "close_client" else None)
    assert sum(p["a"]["eof"] for p in e["phases"]) == (kind == "eof")
    assert e["reads"][-1]["generation"] == 2
    assert first.close.await_count == 1 and len(peers.lifecycles) == 1
    assert_private_values_absent(caplog.text)


@pytest.mark.parametrize("kind", ["late", "fragmented", "delimited"])
async def test_in_time_response_and_delimited_ignored_message_keep_continuity(
    hass, entry, peers, freezer, monkeypatch, kind
):
    e, _, _, fresh = await exercise033(
        hass, entry, peers, freezer, monkeypatch, kind=kind
    )
    assert continuous(e) and not recovered(e) and e["completed"]
    fresh.connect.assert_not_awaited()
    assert e["incident"] is None


@pytest.mark.parametrize(
    "kind", ["auth", "internal", "unknown", "partial", "b_only", "stop"]
)
async def test_refused_incident_or_stop_never_opens_another_a(
    hass, entry, peers, freezer, monkeypatch, kind, caplog
):
    e, _, _, fresh = await exercise033(
        hass, entry, peers, freezer, monkeypatch, kind=kind
    )
    assert not e["completed"] and not recovered(e)
    fresh.connect.assert_not_awaited()
    if kind == "b_only":
        assert e["incident"]["role"] == "b" and e["incident"]["subcode"] == 3
    if kind == "partial":
        assert e["incident"]["subcode"] is None
    assert_private_values_absent(caplog.text)


@pytest.mark.parametrize("cleanup", ["slow", "error", "cancelled", "timeout"])
async def test_read_timeout_remains_first_even_when_original_close_fails(
    hass, entry, peers, freezer, monkeypatch, cleanup
):
    e, _, _, fresh = await exercise033(
        hass, entry, peers, freezer, monkeypatch, cleanup=cleanup
    )
    assert e["incident"]["kind"] == "timeout"
    if cleanup == "slow":
        assert recovered(e)
        a = [o for o in e["owners"] if o["role"] == "a"]
        assert a[1]["open_ms"] >= a[0]["cleaned_ms"] + 60000
    else:
        assert not e["completed"] and not recovered(e)
        assert e["failure"]["category"] == "timeout"
        assert e["failure"]["phase"] != "cleanup"
        assert e["cleanup_errors"] and not e["resources"]["a"]["cleanup"]
        fresh.connect.assert_not_awaited()


async def test_recovery_cannot_shorten_stability_or_spend_teardown_reserve(
    hass, entry, peers, freezer, monkeypatch
):
    e, _, _, _ = await exercise033(
        hass, entry, peers, freezer, monkeypatch, absolute_end=1800
    )
    assert not e["completed"] and e["end_ms"] <= 740000


@pytest.mark.parametrize("kind", ["fresh_auth", "fresh_internal"])
async def test_independent_failure_of_new_generation_is_terminal(
    hass, entry, peers, freezer, monkeypatch, kind
):
    e, _, _, _ = await exercise033(hass, entry, peers, freezer, monkeypatch, kind=kind)
    assert not e["completed"] and e["incident"]["kind"] == "timeout"
    assert e["failure"]["category"] == "timeout"
    assert e["terminal"]["category"] == (
        "authorization" if kind == "fresh_auth" else "unexpected"
    )
    assert e["resources"]["a"]["opens"] == 2 and peers.factory.call_count == 3


async def test_b_close_can_precede_actual_a_write_completion_without_cross_routing(
    hass, entry, peers, freezer, monkeypatch
):
    e, _, _, fresh = await exercise033(
        hass, entry, peers, freezer, monkeypatch, kind="close_client", write_delay=1
    )
    # Cancelling an unfinished TX is not a genuine response deadline. Keep the
    # existing stop policy rather than extending production retry for this case.
    assert not e["completed"] and not recovered(e)
    assert e["incident"]["role"] == "a"
    assert e["incident"]["subcode"] == 3
    fresh.connect.assert_not_awaited()


@pytest.mark.parametrize("kind", ["idle_close", "idle_eof"])
async def test_idle_a_loss_before_seventh_poll_recovers_without_inventing_tx(
    hass, entry, peers, freezer, monkeypatch, kind
):
    e, _, _, _ = await exercise033(hass, entry, peers, freezer, monkeypatch, kind=kind)
    assert recovered(e) and not continuous(e)
    assert e["incident"]["read_ms"] is None
    assert not e["reads"][6]["attempted"] and not e["reads"][6]["decoded"]


def test_dual_classifier_keeps_structured_timeout_through_ha_wrapper():
    error = wrap_error(UpdateFailed, "read failed", HobenTimeoutError())
    assert category(error) == "timeout"


async def test_actual_silent_read_deadline_recovers_without_production_change(
    hass, entry, peers, freezer, caplog
):
    first = peers.wire(DEVICE_GUID, [[RESPONSE], []])
    second = peers.wire(DEVICE_GUID, [[RESPONSE]])
    client = HobenClient(entry.data["user_guid"], DEVICE_GUID, ha_reconnect=True)
    coordinator = HobenDataUpdateCoordinator(hass, entry, client)
    refresh = None
    try:
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        previous, stamp = coordinator.data, coordinator.last_successful_read_at
        owner = client._lifecycle
        refresh = asyncio.create_task(coordinator.async_refresh())
        await pump()
        freezer.tick(29.99)
        await pump()
        assert not refresh.done() and not peers.backoff.delays
        freezer.tick(0.02)
        await pump()
        assert refresh.done()
        await refresh
        coordinator._async_unsub_refresh()
        assert safe_error_report(coordinator.last_exception)["error"] == "timeout"
        assert (
            coordinator.data is previous
            and coordinator.last_successful_read_at == stamp
        )
        assert await peers.backoff.entered.get() == 60
        first.close.assert_awaited_once_with()
        assert peers.factory.call_count == 1
        peers.backoff.release.put_nowait(None)
        await owner.wait_connected()
        await coordinator.async_refresh()
        coordinator._async_unsub_refresh()
        assert coordinator.last_update_success and coordinator.data is not previous
        assert client._lifecycle is owner and len(peers.lifecycles) == 1
        assert client.session_observation.read_generation == 2
        assert client.session_observation.read_sequence == 1
        second.connect.assert_awaited_once_with()
        assert_private_values_absent(caplog.text)
    finally:
        if refresh is not None and not refresh.done():
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        coordinator._async_unsub_refresh()
        await client.async_close()
        assert_stopped(peers)
