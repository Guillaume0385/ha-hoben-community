"""D3 scalar evidence from real sessions over synthetic streams only."""

import asyncio
import json
import logging

import pytest

from custom_components.hoben.exceptions import HobenError, HobenTimeoutError
from custom_components.hoben.session_diagnostics import (
    CAP,
    SessionDiagnostics,
    project_report,
)
from custom_components.hoben.transport import (
    TransportEOF,
    TransportTimeout,
    TransportTlsError,
)
from tests.test_data_updated_silence import Clock, pump
from tests.test_session_300_runtime import response
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory


def test_dropped_delivery_then_real_ping_and_correlated_response_are_distinct():
    async def run():
        factory = Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        try:
            await life.connect()
            wire = factory.streams[0]
            wire.chunks = [
                b"\x0c\x0a" + response(),
                b"\x0a",
                response()[:7],
                response()[7:],
            ]
            await life.request_v4_data()
            report = getattr(life, "session_diagnostics", None)
            assert report is not None  # RED: no reusable HA scalar projection.
            assert report["unsupported_deliveries"] == 1
            assert report["last_delivery_bytes"] == 52
            assert report["pings"] == report["pongs"] == 1
            assert report["v4_requests"] == report["v4_responses_correlated"] == 1
            assert report["responses_after_drop"] == 1
            assert report["boundary_proven"] is False
        finally:
            await life.close()
            factory.assert_clean()
        assert life.session_diagnostics["cleanup_succeeded"] is True

    asyncio.run(run())


@pytest.mark.parametrize("head", [b"\x0c", b"\x16", b"\xfe"])
@pytest.mark.parametrize(
    "tail", [b"\x0a", response(), b"\x1bXXXX\xff\xff\x00\x00\x00\x02\x01\x04"]
)
def test_coalesced_events_are_not_counted_and_known_fragments_bypass_drop(head, tail):
    async def run():
        factory = Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        try:
            await life.connect()
            wire = factory.streams[0]
            wire.chunks = [head + tail, response()[:10], response()[10:]]
            await life.request_v4_data()
            r = life.session_diagnostics
            assert r["unsupported_deliveries"] == 1
            assert r["unsupported_delivery_bytes"] == len(head + tail)
            assert r["pings"] == r["pongs"] == 0
            assert r["v4_responses_correlated"] == r["v4_requests"] == 1
            assert r["info_candidate_deliveries"] == (head == b"\x0c")
            assert r["responses_after_info_candidate"] == (head == b"\x0c")
            assert r["tls_connected"] and r["v4_accepted"]
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_counters_saturate_and_logs_are_bounded_closed_scalars(caplog):
    caplog.set_level(
        logging.DEBUG, logger="custom_components.hoben.session_diagnostics"
    )
    d = SessionDiagnostics(1)
    for _ in range(CAP + 10):
        d.drop(4096, info_candidate=True)
    r = d.safe_report()
    assert r["unsupported_deliveries"] == r["info_candidate_deliveries"] == CAP
    assert r["unsupported_delivery_bytes"] == CAP and r["counters_capped"]
    assert r["last_delivery_bytes"] == 4096 and r["boundary_proven"] is False
    assert r["info_framing"] == "INCONCLUSIVE"
    assert len(caplog.records) <= 40
    assert len(json.dumps(r)) < 2048 and project_report(r) == r
    for value in ("PRIVATE_PAYLOAD", b"RAW_PRIVATE", True, None, -1, 4097):
        d.drop(value)
        d.note(value)
    assert d.safe_report() == r
    d._counts["PRIVATE_PAYLOAD"] = "PRIVATE_VALUE"
    d._generation = "PRIVATE_GUID"
    d._last_size = "PRIVATE_RX"
    assert "PRIVATE" not in json.dumps(d.safe_report()) + caplog.text
    assert all(
        type(v) in (int, bool, str, type(None)) for v in d.safe_report().values()
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("extra", "PRIVATE"),
        ("v4_requests", True),
        ("pongs", -1),
        ("tls_generation", "PRIVATE"),
        ("last_delivery_bytes", 4097),
        ("info_framing", "PROVEN"),
        ("boundary_proven", True),
    ],
)
def test_projection_rejects_extra_keys_wrong_types_and_false_proof(name, value):
    r = SessionDiagnostics(1).safe_report()
    r[name] = value
    assert project_report(r) is None


@pytest.mark.parametrize(
    "fault",
    [TransportEOF(), TransportTlsError(), b"\x05\x02", b"\x0e\xff\xff\x00\x00\xff\xff"],
)
def test_only_genuine_eof_sets_eof_and_terminal_errors_remain_strict(fault):
    async def run():
        factory = Factory()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=Backoff()
        )
        try:
            await life.connect()
            stream, session = factory.streams[0], factory.sessions[0]
            stream.queue.put_nowait(fault)
            with pytest.raises(HobenError):
                await session.wait_rx_stopped()
            await pump()
            r = life.session_diagnostics
            assert r["eof_received"] is (type(fault) is TransportEOF)
            assert r["terminal_error"] and r["transport_closed"]
            assert not r["v4_responses_correlated"]
            assert r["cleanup_succeeded"]
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_silence_and_late_reply_are_uncredited_and_do_not_claim_eof(monkeypatch):
    async def run():
        clock, factory = Clock(monkeypatch), Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        try:
            await life.connect()
            wire = factory.streams[0]
            wire.chunks = []
            task = asyncio.create_task(life.request_v4_data(timeout=5))
            await pump()
            await clock.advance(5.01)
            with pytest.raises(HobenTimeoutError):
                await task
            wire.queue.put_nowait(b"\x0c")
            wire.queue.put_nowait(response() + b"\x0a")
            await pump()
            r = life.session_diagnostics
            assert r["v4_requests"] == r["v4_responses_uncredited"] == 1
            assert (
                r["v4_responses_correlated"] == r["responses_after_info_candidate"] == 0
            )
            assert r["acquisition_uncertain"] and not r["eof_received"]
            assert not r["transport_close_requested"] and not r["cleanup_succeeded"]
            assert r["pings"] == r["pongs"] == 1 and not wire.close_count
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", [TransportTimeout("cleanup"), asyncio.CancelledError()]
)
def test_close_failed_or_interrupted_cannot_attest_cleanup(failure):
    async def run():
        factory = Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        await life.connect()
        wire = factory.streams[0]

        async def close():
            wire.close_count += 1
            raise failure

        wire.close = close
        try:
            await life.close()
        except (HobenError, asyncio.CancelledError):
            pass
        r = life.session_diagnostics
        assert r["transport_close_requested"] and r["transport_close_failed"]
        assert not r["transport_closed"] and not r["cleanup_succeeded"]
        assert r["cleanup_failed"] or r["cleanup_interrupted"]
        assert len(factory.sessions) == 1

    asyncio.run(run())


def test_no_policy_activation_in_conservative_or_experimental_owner():
    async def run():
        factory = Factory()
        life = factory.lifecycle()
        try:
            await life.connect()
            await life.request_v4_data()
            assert life.session_diagnostics is None
            assert factory.sessions[0]._diagnostics is None
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_logger_failure_cannot_change_read_or_cleanup(monkeypatch):
    def bad_log(*args, **kwargs):
        raise RuntimeError("PRIVATE_LOGGER")

    monkeypatch.setattr(
        "custom_components.hoben.session_diagnostics._LOGGER.debug", bad_log
    )

    async def run():
        factory = Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        try:
            await life.connect()
            await life.request_v4_data()
            assert life.session_diagnostics["v4_responses_correlated"] == 1
        finally:
            await life.close()
            factory.assert_clean()
        assert life.session_diagnostics["cleanup_succeeded"]

    asyncio.run(run())


def test_generation_reset_and_cleanup_pending_do_not_borrow_previous_counters():
    async def run():
        factory, backoff = Factory(), Backoff()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=backoff
        )
        release, entered = asyncio.Event(), asyncio.Event()
        try:
            await life.connect()
            first = factory.streams[0]
            first.chunks = [b"\x0c", response()]
            await life.request_v4_data()
            saved = life.session_diagnostics
            first.queue.put_nowait(TransportEOF())
            assert await backoff.entered.get() == 60
            assert life.session_diagnostics["cleanup_succeeded"]
            backoff.release.put_nowait(None)
            await life.wait_connected()
            assert life.session_diagnostics["tls_generation"] == 2
            assert life.session_diagnostics["unsupported_deliveries"] == 0
            assert life.session_diagnostics["v4_responses_correlated"] == 0
            assert saved["unsupported_deliveries"] == 1 and saved["tls_generation"] == 1
            second = factory.streams[1]
            original_close = second.close

            async def delayed_close():
                entered.set()
                await release.wait()
                await original_close()

            second.close = delayed_close
            closing = asyncio.create_task(life.close())
            await entered.wait()
            r = life.session_diagnostics
            assert r["transport_close_requested"] and r["cleanup_requested"]
            assert not r["transport_closed"] and not r["cleanup_succeeded"]
            release.set()
            await closing
            assert life.session_diagnostics["cleanup_succeeded"]
        finally:
            release.set()
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


def test_unsolicited_response_is_never_counted_as_correlated():
    async def run():
        factory = Factory()
        life = factory.lifecycle(
            ha_reconnect=True, recover_acquisition=True, sleep=Backoff()
        )
        try:
            await life.connect()
            factory.streams[0].queue.put_nowait(response())
            with pytest.raises(HobenError):
                await factory.sessions[0].wait_rx_stopped()
            r = life.session_diagnostics
            assert r["v4_requests"] == r["v4_responses_correlated"] == 0
            assert r["terminal_error"] and not r["eof_received"]
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())


@pytest.mark.parametrize("split", [1, 2, 5, 7, 12])
def test_valid_dataupdated_fragments_never_count_as_delivery_drops(split):
    from tests.test_session_ignored_rx import ignored_frame

    async def run():
        factory = Factory()
        life = factory.lifecycle(ha_reconnect=True, recover_acquisition=True)
        try:
            await life.connect()
            frame = ignored_frame(27)
            factory.streams[0].chunks = [frame[:split], frame[split:], response()]
            await life.request_v4_data()
            r = life.session_diagnostics
            assert r["unsupported_deliveries"] == r["info_candidate_deliveries"] == 0
            assert r["v4_responses_correlated"] == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(run())
