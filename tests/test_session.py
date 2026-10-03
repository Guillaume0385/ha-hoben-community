"""One-shot handshake exercised over real transport code and fake TLS streams."""

import asyncio
import traceback
from unittest.mock import AsyncMock, Mock, call

import pytest

from custom_components.hoben import session
from custom_components.hoben.myhoben import decode_opened_client, encode_open_client
from custom_components.hoben.profiles import StoveProfile, select_stove_profile
from custom_components.hoben.session import (
    SessionProtocolError,
    SessionTimeout,
    UnexpectedMessageType,
    open_session_once,
)
from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportEOF,
    TransportError,
    TransportTimeout,
)

# Independent synthetic prefix; 0A/0B inside the payload are not keepalive frames.
OPENED = (
    b"\x04\xa1\x0a\x0b\xd4\xe5\xf6\x00\x02\x05\x00\xab\xbc\xcd"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd\x34\x12"
)
FIELDS = {
    "user_guid": " Synthetic-Usér\t",
    "device_guid": "Synthetic-device ",
    "device_info": "Synthetic/模型/Android",
    "build": 0x1234,
}


def open_once(**overrides):
    """Supply synthetic caller values unchanged to the public session API."""
    return open_session_once(AsyncTlsTransport(), **(FIELDS | overrides))


@pytest.mark.parametrize(
    "chunks",
    [
        [OPENED],
        [bytes([value]) for value in OPENED],
        [OPENED[:1], OPENED[1:8], OPENED[8:47], OPENED[47:]],
    ],
    ids=["one-read", "byte-at-a-time", "several-fragments"],
)
def test_opened_client_fragments(streams, chunks, monkeypatch) -> None:
    """Compose the existing encoder, prefix decoder and profile selector exactly."""
    streams.reader.read.side_effect = chunks
    decoder = Mock(wraps=decode_opened_client)
    selector = Mock(wraps=select_stove_profile)
    monkeypatch.setattr(session, "decode_opened_client", decoder)
    monkeypatch.setattr(session, "select_stove_profile", selector)
    result = asyncio.run(open_once())
    streams.writer.write.assert_called_once_with(encode_open_client(**FIELDS))
    assert result.opened_client == decode_opened_client(OPENED)
    assert result.profile is StoveProfile.V6
    decoder.assert_called_once_with(OPENED)
    selector.assert_called_once_with(result.opened_client)
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()
    assert streams.reader.read.await_count == len(chunks)


@pytest.mark.parametrize("split", range(1, 48))
def test_every_prefix_split(streams, split) -> None:
    """Every two-part fragmentation boundary returns the same response."""
    streams.reader.read.side_effect = [OPENED[:split], OPENED[split:]]
    assert asyncio.run(open_once()).opened_client == decode_opened_client(OPENED)


@pytest.mark.parametrize(
    ("chunks", "pongs"),
    [
        ([b"\x0a", OPENED], 1),
        ([b"\x0a" + OPENED[:9], OPENED[9:]], 1),
        ([b"\x0a\x0a", b"\x0a" + OPENED], 3),
    ],
    ids=["ping-alone", "coalesced-ping-and-prefix", "multiple-pings"],
)
def test_ping_pong_before_opened(streams, chunks, pongs) -> None:
    """Each leading Ping gets an immediate one-byte Pong, before another read."""
    events = Mock()
    events.attach_mock(streams.reader.read, "read")
    events.attach_mock(streams.writer.write, "write")
    streams.reader.read.side_effect = chunks
    assert asyncio.run(open_once()).profile is StoveProfile.V6
    expected = [call.write(encode_open_client(**FIELDS))]
    for chunk in chunks:
        expected.append(call.read(4096))
        for value in chunk:
            if value != 0x0A:
                break
            expected.append(call.write(b"\x0b"))
    assert events.mock_calls == expected
    assert streams.writer.drain.await_count == 1 + pongs


@pytest.mark.parametrize(
    ("product_type", "revision", "major", "profile"),
    [
        (5, 0, 0, StoveProfile.V4),
        (2, 2, 0, StoveProfile.BOILER_V6_230),
        (3, 0, 1, StoveProfile.V6),
        (3, 1, 0, StoveProfile.UNKNOWN),
        (255, 255, 255, StoveProfile.UNKNOWN),
    ],
)
def test_profile_outcomes(streams, product_type, revision, major, profile) -> None:
    """Both ambiguous V6/V6v16 and unsupported profiles remain successful opens."""
    message = bytearray(OPENED)
    message[7], message[8], message[10] = revision, product_type, major
    streams.reader.read.return_value = bytes(message)
    result = asyncio.run(open_once())
    assert result.profile is profile
    assert result.safe_report()["product_type"] == product_type
    streams.writer.close.assert_called_once_with()


@pytest.mark.parametrize("message_type", [0, 3, 11, 14, 27, 47, 255])
def test_unexpected_type_is_numeric_only(streams, message_type, caplog) -> None:
    """Unknown/pairing types stop before reading or interpreting their payload."""
    streams.reader.read.side_effect = [
        bytes([message_type]) + b"SYNTHETIC-AUTH-CODE-AND-GUID",
        OPENED,
    ]
    with caplog.at_level("DEBUG"):
        with pytest.raises(UnexpectedMessageType) as caught:
            asyncio.run(open_once())
    assert caught.value.message_type == message_type
    assert str(caught.value) == f"Unexpected MyHOBEN message type: {message_type}"
    assert "SYNTHETIC-AUTH" not in "".join(traceback.format_exception(caught.value))
    assert "SYNTHETIC-AUTH" not in caplog.text
    streams.reader.read.assert_awaited_once()
    streams.writer.write.assert_called_once_with(encode_open_client(**FIELDS))
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("size", [0, 1, 14, 47])
def test_eof_before_prefix_complete(streams, size) -> None:
    """An empty read never becomes a partial or successful handshake."""
    streams.reader.read.side_effect = [OPENED[:size], b""]
    with pytest.raises(TransportEOF):
        asyncio.run(open_once())
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("operation", ["connect", "write", "read"])
def test_transport_timeout_closes(streams, deadlines, operation) -> None:
    """Every transport timeout, including after a partial prefix, closes once."""

    async def partial_then_timeout(max_bytes):
        if streams.reader.read.await_count == 1:
            return OPENED[:47]
        return await deadlines.expire()

    target = {
        "connect": streams.connect,
        "write": streams.writer.drain,
        "read": streams.reader.read,
    }[operation]
    target.side_effect = (
        partial_then_timeout if operation == "read" else deadlines.expire
    )
    with pytest.raises(TransportTimeout) as caught:
        asyncio.run(open_once())
    assert caught.value.operation == operation
    if operation != "connect":
        streams.writer.close.assert_called_once_with()
        streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("pending_data", [b"\x0a", OPENED[:1]])
def test_overall_handshake_deadline(streams, deadlines, pending_data) -> None:
    """Neither endless Ping nor a stalled partial response can extend the deadline."""

    async def receive(max_bytes):
        if streams.reader.read.await_count == 1:
            return pending_data
        handshake = next(ctx for seconds, ctx in deadlines.contexts if seconds == 23.0)
        handshake.reschedule(asyncio.get_running_loop().time())
        if pending_data == b"\x0a":
            return pending_data
        await asyncio.Future()

    streams.reader.read.side_effect = receive
    with pytest.raises(SessionTimeout, match="handshake timed out"):
        asyncio.run(open_once(handshake_timeout=23.0))
    assert streams.reader.read.await_count <= 3
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()


def test_cancellation_closes(streams) -> None:
    """An interrupted manual probe closes the writer and propagates cancellation."""

    async def run():
        reading = asyncio.Event()

        async def receive(max_bytes):
            reading.set()
            await asyncio.Future()

        streams.reader.read.side_effect = receive
        task = asyncio.create_task(open_once())
        await reading.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()


def test_suffix_unclassified_and_report_redacted(streams, monkeypatch, caplog) -> None:
    """A suffix resembling Ping/OpenedClient stays opaque; only its count survives."""
    suffix = b"\x0a" + OPENED + b"SYNTHETIC-AUTH-CODE"
    streams.reader.read.return_value = OPENED + suffix
    decoder = Mock(wraps=decode_opened_client)
    monkeypatch.setattr(session, "decode_opened_client", decoder)
    with caplog.at_level("DEBUG"):
        result = asyncio.run(open_once())
    decoder.assert_called_once_with(OPENED)
    streams.writer.write.assert_called_once_with(encode_open_client(**FIELDS))
    assert result.safe_report() == {
        "message_type": 4,
        "product_type": 2,
        "product_revision": 0,
        "software_major": 0,
        "software_minor": 5,
        "application_version": 0x1234,
        "profile": "v6",
        "unclassified_bytes": len(suffix),
    }
    public = repr(result) + repr(result.opened_client) + str(result.safe_report())
    public += caplog.text
    for sensitive in (*FIELDS.values(), OPENED[14:46].decode(), "SYNTHETIC-AUTH-CODE"):
        if isinstance(sensitive, str):
            assert sensitive not in public


def test_invalid_prefix_closes_safely(streams) -> None:
    """The existing ASCII check remains enforced, with a static protocol error."""
    streams.reader.read.return_value = OPENED[:14] + b"\xff" + OPENED[15:]
    with pytest.raises(SessionProtocolError, match="^Invalid OpenedClient prefix$"):
        asyncio.run(open_once())
    streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("response", [OPENED, b"\x2fSYNTHETIC-PRIVATE"])
def test_close_error_does_not_hide_protocol_outcome(streams, response) -> None:
    """Report shutdown failure on success; preserve an earlier protocol failure."""
    streams.reader.read.return_value = response
    streams.writer.wait_closed.side_effect = OSError("SYNTHETIC-PRIVATE")
    error = TransportError if response == OPENED else UnexpectedMessageType
    with pytest.raises(error):
        asyncio.run(open_once())
    streams.writer.transport.abort.assert_called_once_with()


@pytest.mark.parametrize(
    "fields",
    [
        {"build": -1},
        {"user_guid": b"SYNTHETIC-PRIVATE"},
        {"device_guid": "SYNTHETIC-PRIVATE\ud800"},
        {"handshake_timeout": 0},
        {"handshake_timeout": float("inf")},
    ],
)
def test_invalid_inputs_do_not_connect(streams, fields) -> None:
    """Invalid inputs also close, and encoding errors never echo identifier data."""
    # Use a real transport to verify the lifecycle without replacing async methods.
    transport = AsyncTlsTransport()
    transport.close = AsyncMock(wraps=transport.close)
    with pytest.raises(ValueError) as caught:
        asyncio.run(open_session_once(transport, **(FIELDS | fields)))
    assert "SYNTHETIC-PRIVATE" not in "".join(traceback.format_exception(caught.value))
    streams.connect.assert_not_awaited()
    transport.close.assert_awaited_once_with()
