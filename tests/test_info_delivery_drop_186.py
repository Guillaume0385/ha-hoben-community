"""#186-B private hypothesis over the real RX and synthetic transports only."""

import ast
import asyncio
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from custom_components.hoben.exceptions import (
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenInternalError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTlsVerificationError,
    HobenTransportError,
)
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportTlsError,
)
from custom_components.hoben.v4_session import (
    V4Session,
    V4SessionMode,
    _InfoDeliveryDropExperiment,
)
from tests.test_data_updated_silence import Clock, pump
from tests.test_session_300_runtime import Stream
from tests.test_session_ignored_rx import ignored_frame
from tests.tls_read_candidate_186 import INVALID_UPDATED, PING, RESPONSE


def owner(chunks=(), *, enabled=True, limit=3, suffix=b"", **options):
    wire = Stream(chunks, suffix=suffix)
    factory = Mock(return_value=wire)
    if enabled:
        options["_info_delivery_drop"] = _InfoDeliveryDropExperiment(limit=limit)
    session = V4Session(
        user_guid="b" * 32,
        transport_factory=factory,
        mode=V4SessionMode.PERSISTENT,
        classify_frame_boundary=True,
        **options,
    )
    return session, wire, factory


async def clean(session, wire, factory):
    await session.abort()
    assert session.cleanup_succeeded and wire.close_count == 1
    assert wire.active_reads == wire.active_tx == 0
    assert not session._operations and not session._tx_operations
    assert session._rx_task.done() and factory.call_count == 1


@pytest.mark.parametrize("code", [None, *range(8), 255])
@pytest.mark.parametrize(
    "suffix", [b"", PING, RESPONSE], ids=["isolated", "ping", "response"]
)
def test_optin_discards_whole_info_delivery_then_requires_fresh_response(
    code, suffix, caplog
):
    async def scenario():
        info = b"\x0c" + (b"" if code is None else bytes((code,))) + suffix
        session, wire, factory = owner([info, RESPONSE])
        caplog.set_level(logging.DEBUG, logger="custom_components.hoben.v4_session")
        await session.connect()
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1 and wire.close_count == 0
            assert session._info_delivery_drop._count == 1
            assert [item[0] for item in wire.writes] == [
                3,
                13,
            ]  # No Pong for dropped suffix.
            assert not session.snapshot.boundary_proven
            assert not session._framer.partial
            logs = [
                r.getMessage()
                for r in caplog.records
                if "info_delivery_discarded" in r.getMessage()
            ]
            assert len(logs) == 1 and f"delivery_bytes={len(info)} " in logs[0]
            assert "experimental_hypothesis=true boundary_proven=false" in logs[0]
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


@pytest.mark.parametrize("split", range(1, len(RESPONSE)))
def test_optin_keeps_incremental_mbap_and_real_ping_routing(split):
    async def scenario():
        session, wire, factory = owner(
            [b"\x0c", PING, RESPONSE[:split], RESPONSE[split:]]
        )
        await session.connect()
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1
            assert [item[0] for item in wire.writes] == [3, 13, 11]
            assert session._info_delivery_drop._count == 1
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_default_off_keeps_info_rejection():
    async def scenario():
        session, wire, factory = owner([b"\x0c", RESPONSE], enabled=False)
        await session.connect()
        try:
            with pytest.raises(HobenProtocolError):
                await session.request_v4_data()
            assert session.verified_read_sequence == 0
            assert wire.queue.qsize() == 1
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


@pytest.mark.parametrize("limit", [1, 3, 16])
def test_total_drop_limit_is_exact_bounded_and_stops_idle_rx(limit, caplog):
    async def scenario():
        session, wire, factory = owner(limit=limit)
        caplog.set_level(logging.DEBUG, logger="custom_components.hoben.v4_session")
        await session.connect()
        try:
            for _ in range(limit + 1):
                wire.queue.put_nowait(b"\x0c")
            with pytest.raises(HobenProtocolError):
                await session.wait_rx_stopped()
            assert session._info_delivery_drop._count == limit
            assert session._framer.boundary_failure is None  # Not a proven wire fault.
            assert session.verified_read_sequence == 0 and wire.writes[0][0] == 3
            assert len(wire.writes) == 1
            assert (
                sum("info_delivery_discarded" in r.getMessage() for r in caplog.records)
                == limit
            )
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_good_read_does_not_reload_the_total_drop_budget():
    async def scenario():
        session, wire, factory = owner([b"\x0c", RESPONSE], limit=2)
        await session.connect()
        try:
            await session.request_v4_data()
            await session.request_v4_data()
            with pytest.raises(HobenProtocolError):
                await session.request_v4_data()
            assert session.verified_read_sequence == 2
            assert session._info_delivery_drop._count == 2
            assert [packet[0] for packet in wire.writes] == [3, 13, 13, 13]
            assert wire.queue.qsize() == 1  # Third response was not consumed.
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_drops_preserve_pending_identity_and_original_acquisition_deadline(monkeypatch):
    async def scenario():
        clock = Clock(monkeypatch)
        session, wire, factory = owner([b"\x0c" + RESPONSE], limit=4)
        await session.connect()
        task = asyncio.create_task(session.request_v4_data(timeout=10))
        try:
            await pump()
            pending, deadline = session._pending_read, session._read_timeout
            when = deadline.when()
            assert not task.done() and session.verified_read_sequence == 0
            await clock.advance(5)
            wire.queue.put_nowait(b"\x0c")
            await pump()
            assert (
                session._pending_read is pending and session._read_timeout is deadline
            )
            assert deadline.when() == when
            await clock.advance(4.999)
            assert not task.done()
            await clock.advance(0.002)
            with pytest.raises(HobenTimeoutError):
                await task
            assert session.verified_read_sequence == 0 and wire.close_count == 1
        finally:
            await session.abort()
            await asyncio.gather(task, return_exceptions=True)
        assert session.cleanup_succeeded and factory.call_count == 1
        assert wire.active_reads == 0 and session._rx_task.done()

    asyncio.run(scenario())


@pytest.mark.parametrize("code", [*range(8), 255])
def test_info_fragment_does_not_authorize_dropping_the_following_subcode(code):
    async def scenario():
        session, wire, factory = owner([b"\x0c", bytes((code,)), TransportEOF()])
        await session.connect()
        try:
            with pytest.raises((HobenProtocolError, HobenTransportError)):
                await session.request_v4_data()
            assert session.verified_read_sequence == 0
            assert session._info_delivery_drop._count == 1
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault",
    [
        PING + b"\x0c",
        b"\xff",
        b"\x05\x03",
        TransportEOF(),
        TransportTlsError(),
        TransportCertificateError(),
        None,
    ],
    ids=[
        "ping-info",
        "unknown",
        "close-client",
        "eof",
        "tls",
        "certificate",
        "local-contract",
    ],
)
def test_all_other_failures_keep_existing_terminal_cleanup(fault):
    async def scenario():
        session, wire, factory = owner([fault])
        await session.connect()
        try:
            with pytest.raises(
                (
                    HobenProtocolError,
                    HobenTransportError,
                    HobenClosedError,
                    HobenTlsVerificationError,
                )
            ):
                await session.request_v4_data()
            assert session.verified_read_sequence == 0
            assert session._info_delivery_drop._count == 0
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_auth_and_internal_exceptions_after_drop_are_not_ignored():
    async def scenario(fault, error_type):
        session, wire, factory = owner([b"\x0c", fault])
        await session.connect()
        try:
            with pytest.raises(error_type):
                await session.request_v4_data()
            assert session.verified_read_sequence == 0
            assert session._info_delivery_drop._count == 1
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario(b"\x2f", HobenAuthorizationRequiredError))
    asyncio.run(scenario(RuntimeError("PRIVATE_186"), HobenInternalError))


def test_drop_cannot_accept_wrong_correlation_or_an_unsolicited_response():
    async def scenario():
        wrong_transaction = RESPONSE[:1] + b"\x00\x01" + RESPONSE[3:]
        session, wire, factory = owner([b"\x0c", wrong_transaction])
        await session.connect()
        try:
            with pytest.raises(HobenProtocolError):
                await session.request_v4_data()
            assert session.verified_read_sequence == 0
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())

    async def unsolicited():
        session, wire, factory = owner()
        await session.connect()
        try:
            wire.queue.put_nowait(b"\x0c")
            wire.queue.put_nowait(RESPONSE)
            with pytest.raises(HobenProtocolError):
                await session.wait_rx_stopped()
            assert session.verified_read_sequence == 0 and len(wire.writes) == 1
        finally:
            await clean(session, wire, factory)

    asyncio.run(unsolicited())


def test_non_owner_cannot_discard_and_retained_terminal_tail_is_not_skipped():
    async def scenario():
        session, wire, factory = owner([RESPONSE])
        await session.connect()
        try:
            assert not session._discard_info_delivery(b"\x0c", wire)
            assert session._info_delivery_drop._count == 0
            await session.request_v4_data()
            wire.queue.put_nowait(b"\x05\x03\x0c")
            with pytest.raises(HobenClosedError):
                await session.wait_rx_stopped()
            assert session._info_delivery_drop._count == 0
            assert session._framer._tail is not None  # Never drained after terminal RX.
        finally:
            await clean(session, wire, factory)
        assert session._framer._tail is None

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", [14, 7, 27])
def test_info_byte_inside_a_partial_frame_is_never_a_drop_candidate(kind):
    async def scenario():
        frame = RESPONSE if kind == 14 else ignored_frame(kind)
        cut = 10 if kind == 14 else len(frame) - 2
        frame = frame[:cut] + b"\x0c" + frame[cut + 1 :]
        deliveries = [frame[:cut], frame[cut:]] + ([] if kind == 14 else [RESPONSE])
        session, wire, factory = owner(deliveries)
        await session.connect()
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1
            assert session._info_delivery_drop._count == 0
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "suffix",
    [b"\x0c", PING + b"\x0c", RESPONSE],
    ids=["info", "ping-info", "unsolicited-response"],
)
def test_opening_suffix_has_no_new_delivery_provenance(suffix):
    async def scenario():
        session, wire, factory = owner(suffix=suffix)
        await session.connect()
        try:
            with pytest.raises(HobenProtocolError):
                await session.request_v4_data()
            assert session._info_delivery_drop._count == 0
            assert session.verified_read_sequence == 0
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_opening_ping_suffix_does_not_prevent_later_genuine_delivery_drop():
    async def scenario():
        session, wire, factory = owner([b"\x0c", RESPONSE], suffix=PING)
        await session.connect()
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1
            assert session._info_delivery_drop._count == 1
            assert sorted(p[0] for p in wire.writes) == [3, 11, 13]
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_dataupdated_recovery_keeps_rolling_silence_and_one_probe(monkeypatch):
    async def scenario():
        clock = Clock(monkeypatch)
        session, wire, factory = owner([RESPONSE], recover_data_updated=True)
        await session.connect()
        try:
            wire.queue.put_nowait(INVALID_UPDATED)
            await pump()
            assert session.data_updated_recovering
            await clock.advance(29)
            wire.queue.put_nowait(b"\x0c" + PING + RESPONSE)
            await pump()
            await clock.advance(29)
            assert len(wire.writes) == 1 and session.verified_read_sequence == 0
            assert session._info_delivery_drop._count == 0
            await clock.advance(1.001)
            assert session.verified_read_sequence == 1
            assert not session.data_updated_recovering and wire.close_count == 0
            assert [p[0] for p in wire.writes] == [3, 13]
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_dataupdated_probe_info_uses_recovery_guard_not_drop(monkeypatch):
    async def scenario():
        clock = Clock(monkeypatch)
        session, wire, factory = owner([b"\x0c"], recover_data_updated=True)
        await session.connect()
        try:
            wire.queue.put_nowait(INVALID_UPDATED)
            await pump()
            await clock.advance(30.001)
            assert session.data_updated_recovering and not session._data_updated.probing
            assert session._info_delivery_drop._count == 0
            assert session.verified_read_sequence == 0 and wire.close_count == 0
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())


def test_pending_cancel_and_concurrent_abort_reap_the_one_reader():
    async def scenario():
        session, wire, factory = owner([b"\x0c"])
        await session.connect()
        task = asyncio.create_task(session.request_v4_data())
        await pump()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(session.abort(), session.abort())
        assert session.cleanup_succeeded and wire.close_count == factory.call_count == 1
        assert wire.active_reads == 0 and session._rx_task.done()
        assert not session._operations and session.verified_read_sequence == 0

    asyncio.run(scenario())


def test_failed_cleanup_remains_unproven_after_a_drop():
    async def scenario():
        session, wire, factory = owner([b"\x0c", TransportEOF()])

        async def fail_close():
            wire.close_count += 1
            raise TransportTlsError("PRIVATE_186_CLOSE")

        wire.close = fail_close
        await session.connect()
        with pytest.raises(HobenTransportError):
            await session.request_v4_data()
        await session.abort()
        assert not session.cleanup_succeeded and wire.close_count == 1
        assert factory.call_count == 1 and session.verified_read_sequence == 0
        assert session._rx_task.done() and wire.active_reads == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("limit", [None, True, False, 0, -1, 17, 1.0, "3"])
def test_private_capability_rejects_invalid_bounds_before_transport(limit):
    with pytest.raises(HobenInvalidInputError):
        _InfoDeliveryDropExperiment(limit=limit)


def test_capability_is_one_use_and_persistent_only():
    cap = _InfoDeliveryDropExperiment(limit=1)
    factory = Mock()
    with pytest.raises(HobenInvalidInputError):
        V4Session(transport_factory=factory, _info_delivery_drop=cap)
    V4Session(
        mode=V4SessionMode.PERSISTENT,
        transport_factory=factory,
        _info_delivery_drop=cap,
    )
    with pytest.raises(HobenInvalidInputError):
        V4Session(
            mode=V4SessionMode.PERSISTENT,
            transport_factory=factory,
            _info_delivery_drop=cap,
        )
    factory.assert_not_called()
    assert repr(cap) == "_InfoDeliveryDropExperiment()"


def test_optin_has_no_ha_lifecycle_campaign_or_environment_supplier():
    for root in (Path("custom_components"), Path("scripts")):
        for path in root.rglob("*.py"):
            if path.as_posix() == "custom_components/hoben/v4_session.py":
                continue
            source = path.read_text()
            if path.as_posix() == "scripts/info_manual_worker.py":
                # D7 explicitly authorizes this dedicated private supplier only.
                # No environment/HA switch; exactly one bounded capability.
                tree = ast.parse(source)
                factories = [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "_InfoDeliveryDropExperiment"
                ]
                assert len(factories) == 1
                assert not factories[0].args
                assert [
                    (k.arg, ast.literal_eval(k.value)) for k in factories[0].keywords
                ] == [("limit", 1)]
                consumers = [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.keyword) and n.arg == "_info_delivery_drop"
                ]
                assert len(consumers) == 1 and consumers[0].value is factories[0]
                assert "os.environ" not in source and "getenv" not in source
                assert "type(port) is PassiveTlsPort" in source
                continue
            assert "_InfoDeliveryDropExperiment" not in source
            tree = ast.parse(source)
            assert not any(
                isinstance(node, ast.keyword) and node.arg == "_info_delivery_drop"
                for node in ast.walk(tree)
            )


def test_private_payload_is_never_inspected_or_logged(caplog):
    async def scenario():
        caplog.set_level(logging.DEBUG, logger="custom_components.hoben.v4_session")
        private = b"PRIVATE_186_PAYLOAD" * 100
        session, wire, factory = owner([b"\x0c" + private, RESPONSE])
        await session.connect()
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1
            assert private.decode() not in caplog.text
            assert "PRIVATE_186" not in caplog.text
            assert "frame_bytes=" not in "".join(
                r.getMessage()
                for r in caplog.records
                if "info_delivery_discarded" in r.getMessage()
            )
        finally:
            await clean(session, wire, factory)

    asyncio.run(scenario())
