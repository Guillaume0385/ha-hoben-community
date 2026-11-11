"""D1 actual RX policy: synthetic completions, no live transport or identities."""

import asyncio
import logging

import pytest

from custom_components.hoben.exceptions import (
    HobenInvalidInputError,
    HobenProtocolError,
)
from custom_components.hoben.v4_experiment import (
    POST_OPEN_AUTH_TYPES,
    POST_OPEN_SUPPORTED_TYPES,
)
from custom_components.hoben.v4_session import SessionState, V4Session, V4SessionMode
from tests.test_data_updated_silence import pump
from tests.test_info_delivery_drop_186 import clean, owner
from tests.tls_read_candidate_186 import PING, RESPONSE


def policy(chunks=(), **options):
    return owner(chunks, enabled=False, discard_unsupported_deliveries=True, **options)


@pytest.mark.parametrize("head", sorted(set(range(256)) - {5, 7, 10, 14, 27, 47, 48}))
def test_every_unhandled_head_is_dropped_on_same_rx_without_acquisition(head):
    async def run():
        session, wire, factory = policy()
        await session.connect()
        rx = session._rx_task
        try:
            wire.queue.put_nowait(bytes((head,)) + PING + RESPONSE)
            wire.queue.put_nowait(PING)
            await pump()
            assert session.state is SessionState.CONNECTED and session._rx_task is rx
            assert not rx.done() and not wire.close_count
            assert session.verified_read_sequence == 0
            assert [p[0] for p in wire.writes] == [3, 11]
            wire.chunks = [RESPONSE]
            await session.request_v4_data()
            assert session.verified_read_sequence == 1
            assert session._unsupported_delivery_drops == 1
            assert (
                session._info_delivery_drop is None
                and not session.snapshot.boundary_proven
            )
        finally:
            await clean(session, wire, factory)

    asyncio.run(run())


@pytest.mark.parametrize(
    "suffix", [b"", PING, RESPONSE, b"\x1b" + b"\x00" * 4 + RESPONSE[1:]]
)
def test_more_than_sixteen_drops_are_not_a_local_failure(suffix, caplog):
    async def run():
        session, wire, factory = policy([b"\x0c" + suffix] * 100 + [PING, RESPONSE])
        await session.connect()
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1 and not wire.close_count
            assert session._unsupported_delivery_drops == 100
            assert [p[0] for p in wire.writes] == [3, 13, 11]
            logs = [
                r.getMessage()
                for r in caplog.records
                if "unsupported_delivery_discarded" in r.getMessage()
            ]
            assert len(logs) == 8  # 1..4, 8, 16, 32, 64.
            assert all(
                "boundary_proven=false" in r and "length_scope=tls_delivery" in r
                for r in logs
            )
            assert not any("message_type_byte" in r or "payload" in r for r in logs)
            session._unsupported_delivery_drops = 65534
            wire.chunks = [b"\x0cPRIVATE_PAYLOAD"] * 3 + [RESPONSE]
            await session.request_v4_data()
            assert session._unsupported_delivery_drops == 65535
            assert (
                session.verified_read_sequence == 2
                and "PRIVATE_PAYLOAD" not in caplog.text
            )
        finally:
            await clean(session, wire, factory)

    with caplog.at_level(logging.DEBUG, logger="custom_components.hoben.v4_session"):
        asyncio.run(run())


@pytest.mark.parametrize("kind", [14, 27])
@pytest.mark.parametrize("split", range(1, 50))
def test_known_partial_frame_never_discards_its_following_fragment(kind, split):
    async def run():
        frame = RESPONSE if kind == 14 else b"\x1b" + b"\x0c" * 4 + RESPONSE[1:]
        chunks = [frame[:split], frame[split:]] + ([] if kind == 14 else [RESPONSE])
        session, wire, factory = policy(chunks)
        await session.connect()
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1
            assert (
                session._unsupported_delivery_drops == 0 and not session._framer.partial
            )
        finally:
            await clean(session, wire, factory)

    asyncio.run(run())


@pytest.mark.parametrize("suffix", [b"\x0c", PING + b"\x0c", RESPONSE])
def test_opening_suffix_is_not_a_new_delivery(suffix):
    async def run():
        session, wire, factory = policy(suffix=suffix)
        await session.connect()
        try:
            with pytest.raises(HobenProtocolError):
                await session.request_v4_data()
            assert (
                session._unsupported_delivery_drops == 0
                and session.verified_read_sequence == 0
            )
        finally:
            await clean(session, wire, factory)

    asyncio.run(run())


def test_policy_requires_explicit_persistent_owner_and_preserves_prototype():
    assert POST_OPEN_SUPPORTED_TYPES == {5, 7, 10, 14, 27}
    assert POST_OPEN_AUTH_TYPES == {47, 48}
    assert V4Session()._discard_unsupported_deliveries is False
    assert (
        V4Session(mode=V4SessionMode.PERSISTENT)._discard_unsupported_deliveries
        is False
    )
    for value in (True, 1, None, "true"):
        with pytest.raises(HobenInvalidInputError):
            V4Session(discard_unsupported_deliveries=value)


@pytest.mark.parametrize(
    "fault",
    [
        b"\x05\x02",
        b"\x2f",
        b"\x30",
        b"\x0e\xff\xff\x00\x00\xff\xff",
        RESPONSE[:1] + b"\x00\x01" + RESPONSE[3:],
    ],
)
def test_supported_faults_auth_and_bad_correlation_are_not_drops(fault):
    from custom_components.hoben.exceptions import HobenError

    async def run():
        session, wire, factory = policy([b"\x0c", fault])
        await session.connect()
        try:
            with pytest.raises(HobenError):
                await session.request_v4_data()
            assert session.verified_read_sequence == 0
            assert session._unsupported_delivery_drops == 1
        finally:
            await clean(session, wire, factory)

    asyncio.run(run())


def test_unsolicited_response_after_drop_is_still_rejected():
    async def run():
        session, wire, factory = policy()
        await session.connect()
        try:
            wire.queue.put_nowait(b"\x0c")
            wire.queue.put_nowait(RESPONSE)
            with pytest.raises(HobenProtocolError):
                await session.wait_rx_stopped()
            assert session.verified_read_sequence == 0
        finally:
            await clean(session, wire, factory)

    asyncio.run(run())


def test_continuously_ready_unknown_reads_yield_to_cancel_and_reap():
    async def run():
        session, wire, factory = policy()
        receive = wire.read

        async def ready(*args, **kwargs):
            if kwargs.get("bounded", True):
                return await receive(*args, **kwargs)
            return b"\x0c"

        wire.read = ready
        await session.connect()
        rx = session._rx_task
        await pump()
        assert session._unsupported_delivery_drops > 16
        assert not rx.done() and not wire.close_count
        await clean(session, wire, factory)
        assert session.verified_read_sequence == 0

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["eof", "tls", "certificate", "internal"])
def test_real_terminal_errors_after_production_drop_are_preserved(fault):
    from custom_components.hoben.exceptions import (
        HobenInternalError,
        HobenTlsVerificationError,
        HobenTransportError,
    )
    from custom_components.hoben.transport import (
        TransportCertificateError,
        TransportEOF,
        TransportTlsError,
    )

    async def run():
        error, expected = {
            "eof": (TransportEOF(), HobenTransportError),
            "tls": (TransportTlsError(), HobenTransportError),
            "certificate": (TransportCertificateError(), HobenTlsVerificationError),
            "internal": (RuntimeError("PRIVATE_LOCAL_FAILURE"), HobenInternalError),
        }[fault]
        session, wire, factory = policy([b"\x0c", error])
        await session.connect()
        try:
            with pytest.raises(expected):
                await session.request_v4_data()
            assert session.verified_read_sequence == 0
            assert session._unsupported_delivery_drops == 1
        finally:
            await clean(session, wire, factory)

    asyncio.run(run())


def test_single_info_then_ping_and_fresh_response_on_original_rx():
    async def run():
        session, wire, factory = policy([b"\x0c", PING, RESPONSE])
        await session.connect()
        rx = session._rx_task
        try:
            await session.request_v4_data()
            assert session.verified_read_sequence == 1
            assert session._unsupported_delivery_drops == 1
            assert session._rx_task is rx and not rx.done()
            assert not wire.close_count and factory.call_count == 1
            assert [p[0] for p in wire.writes] == [3, 13, 11]
        finally:
            await clean(session, wire, factory)

    asyncio.run(run())
