"""Real asyncio witnesses: telemetry discriminates without changing shutdown."""

import asyncio
import json
import logging
import ssl
from types import SimpleNamespace

import pytest

from custom_components.hoben.close_diagnostic import CloseTrace, close_generation
from custom_components.hoben.transport import TransportError, TransportTimeout
from tests.test_data_updated_silence import Clock, pump
from tests.test_tls_cleanup_b9 import connected, no_close_owner

LOGGER = "custom_components.hoben.close_diagnostic"
PRIVATE = "PRIVATE_PAYLOAD"


def trace(caplog):
    rows = [r.hoben_tls_close for r in caplog.records if r.name == LOGGER]
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {
        "schema",
        "generation",
        "events",
        "first_failure",
        "secondary_failure",
        "future",
        "connection_lost",
        "callback_result",
        "elapsed_ms",
        "duration_capped",
        "truncated",
        "invalid",
    }
    assert len(json.dumps(row, separators=(",", ":")).encode()) <= 4096
    assert len(row["events"]) <= 12
    assert row["generation"] == "unknown"
    assert 0 <= row["elapsed_ms"] <= 5000
    assert PRIVATE not in json.dumps(row) + caplog.text
    for event in row["events"]:
        assert event["operation"] in {"writer_close", "wait_closed", "abort", "reap"}
        assert event["result"] in {
            "returned",
            "raised_connection",
            "raised_tls",
            "raised_other",
            "timeout",
            "cancelled",
            "not_confirmed",
        }
        assert event["future"] in {
            "pending",
            "completed_ok",
            "completed_error",
            "cancelled",
            "unknown",
        }
        assert event["source"] in {"operation", "callback", "owner"}
        assert event["connection_lost"] in {"observed", "not_observed"}
    return row


@pytest.mark.parametrize("fault", ["normal", "connection", "tls", "close", "abort"])
def test_original_operation_and_error_type_are_discriminated(
    caplog, monkeypatch, fault
):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    async def run():
        clock = Clock(monkeypatch)
        transport, wire, future = connected()
        original = wire.protocol.connection_lost
        if fault in {"close", "abort"}:

            def fail():
                raise OSError(PRIVATE)

            monkeypatch.setattr(wire, fault, fail)
        task = asyncio.create_task(transport.close())
        await pump()
        if fault == "abort":
            await clock.advance(4.001)
        elif fault != "close":
            error = (
                ConnectionResetError(PRIVATE)
                if fault == "connection"
                else ssl.SSLError(PRIVATE)
                if fault == "tls"
                else None
            )
            wire.ack(error)
        try:
            if fault == "normal":
                await task
            else:
                with pytest.raises(TransportError):
                    await task
            assert wire.protocol.connection_lost == original
            assert "connection_lost" not in vars(wire.protocol)
            row = trace(caplog)
            if fault == "normal":
                assert row["first_failure"] is None
                assert row["future"] == "completed_ok"
            else:
                assert row["first_failure"]["operation"] == (
                    "writer_close"
                    if fault == "close"
                    else "abort"
                    if fault == "abort"
                    else "wait_closed"
                )
                assert (
                    row["first_failure"]["result"]
                    == {
                        "connection": "raised_connection",
                        "tls": "raised_tls",
                        "close": "raised_other",
                        "abort": "raised_other",
                    }[fault]
                )
            assert row["connection_lost"] == (
                "not_observed" if fault == "abort" else "observed"
            )
            assert not row["invalid"] and not row["truncated"]
            no_close_owner()
        finally:
            wire.ack()
            await asyncio.gather(task, return_exceptions=True)
            if future.done() and not future.cancelled():
                future.exception()

    asyncio.run(run())


def test_first_stream_error_is_not_replaced_by_secondary_abort_failure(
    caplog, monkeypatch
):
    async def run():
        transport, wire, _ = connected()

        def abort():
            raise RuntimeError(PRIVATE)

        monkeypatch.setattr(wire, "abort", abort)
        task = asyncio.create_task(transport.close())
        await pump()
        wire.ack(ConnectionResetError(PRIVATE))
        with pytest.raises(TransportError):
            await task
        row = trace(caplog)
        assert row["first_failure"]["operation"] == "wait_closed"
        assert row["first_failure"]["result"] == "raised_connection"
        assert row["secondary_failure"]["operation"] == "abort"
        assert row["secondary_failure"]["result"] == "raised_other"
        assert row["first_failure"]["order"] < row["secondary_failure"]["order"]
        no_close_owner()

    asyncio.run(run())


def test_deadline_precedes_reap_cancellation_and_never_claims_callback(
    caplog, monkeypatch
):
    async def run():
        clock = Clock(monkeypatch)
        transport, wire, _ = connected(abort_ack=False)
        task = asyncio.create_task(transport.close())
        await pump()
        await clock.advance(4.001)
        await clock.advance(1.001)
        with pytest.raises(TransportTimeout):
            await task
        row = trace(caplog)
        assert row["first_failure"]["result"] == "timeout"
        assert row["secondary_failure"]["result"] == "cancelled"
        assert row["connection_lost"] == "not_observed"
        assert row["future"] == "cancelled" and row["duration_capped"]
        assert wire.aborts == 1
        wire.ack()
        assert trace(caplog) == row  # No late success or second diagnostic.
        no_close_owner()

    asyncio.run(run())


@pytest.mark.parametrize("phase", [0, 4.1])
def test_concurrent_cancellation_retains_failure_and_restores_callback(
    caplog, monkeypatch, phase
):
    async def run():
        clock = Clock(monkeypatch)
        transport, wire, _ = connected(abort_ack=False)
        task = asyncio.create_task(transport.close())
        await pump()
        await clock.advance(phase)
        task.cancel()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert trace(caplog)["first_failure"]["result"] == "cancelled"
        assert "connection_lost" not in vars(wire.protocol)
        wire.ack()
        no_close_owner()

    asyncio.run(run())


def test_duplicate_close_does_not_emit_an_idempotent_success(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    async def run():
        transport, wire, _ = connected()
        task = asyncio.create_task(transport.close())
        await pump()
        await transport.close()
        assert not task.done() and wire.closes == 1
        assert not [r for r in caplog.records if r.name == LOGGER]
        wire.ack()
        await task
        await transport.close()
        assert trace(caplog)["first_failure"] is None
        no_close_owner()

    asyncio.run(run())


@pytest.mark.parametrize("error", [OSError, asyncio.CancelledError])
def test_broken_diagnostic_logger_cannot_change_real_cleanup(monkeypatch, error):
    async def run():
        transport, wire, _ = connected()

        def fail(*args, **kwargs):
            raise error(PRIVATE)

        monkeypatch.setattr(LOGGER + "._LOGGER.log", fail)
        task = asyncio.create_task(transport.close())
        await pump()
        wire.ack()
        await task
        assert wire.closed and "connection_lost" not in vars(wire.protocol)
        no_close_owner()

    asyncio.run(run())


def test_diagnostic_does_not_retrieve_shared_future_error_or_invent_callback(caplog):
    async def run():
        transport, wire, future = connected()
        wire.ack(ConnectionResetError(PRIVATE))
        assert future._log_traceback
        d = CloseTrace(transport._writer, 5)
        d.record("wait_closed", "not_confirmed")
        assert d.future_state() == "completed_error" and future._log_traceback
        d.finish()
        assert future._log_traceback
        caplog.clear()
        with pytest.raises(TransportError):
            await transport.close()
        assert trace(caplog)["connection_lost"] == "not_observed"

    asyncio.run(run())


def test_invalid_generation_and_trace_overflow_preserve_bounded_first_failures(caplog):
    async def run():
        with close_generation(
            SimpleNamespace(frame_log=SimpleNamespace(generation=PRIVATE))
        ):
            d = CloseTrace(None, 5)
        for _ in range(30):
            d.record("wait_closed", "not_confirmed")
        d.record("wait_closed", "raised_tls", failed=True)
        d.record("abort", "raised_other", failed=True)
        d.finish()
        row = trace(caplog)
        assert row["truncated"] and len(row["events"]) == 12
        assert row["first_failure"]["result"] == "raised_tls"
        assert row["secondary_failure"]["result"] == "raised_other"

    asyncio.run(run())


def test_non_allowlisted_fields_are_discarded_without_rendering_them(caplog):
    async def run():
        d = CloseTrace(None, 5)
        d.record(PRIVATE, "returned")
        d.record("abort", PRIVATE)
        d.record("abort", "returned", source=PRIVATE)
        d.finish()
        row = trace(caplog)
        assert row["invalid"] and row["events"] == []

    caplog.set_level(logging.DEBUG, logger=LOGGER)
    asyncio.run(run())


def test_previously_captured_callback_cannot_mutate_a_finished_record(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    async def run():
        transport, wire, _ = connected()
        task = asyncio.create_task(transport.close())
        await pump()
        captured = wire.protocol.connection_lost
        wire.ack()
        await task
        before = json.dumps(trace(caplog), sort_keys=True)
        captured(None)
        assert json.dumps(trace(caplog), sort_keys=True) == before
        no_close_owner()

    asyncio.run(run())
