"""Verified TLS behavior with fake streams only; no test certificates required."""

import asyncio
import ssl
import traceback

import pytest

from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportEOF,
    TransportError,
    TransportTimeout,
    TransportTlsError,
)


@pytest.mark.parametrize("endpoint", [{}, {"host": "synthetic.example", "port": 1234}])
def test_verified_connection(streams, endpoint) -> None:
    """Defaults and overrides retain certificate checks and hostname/SNI binding."""

    async def run():
        transport = AsyncTlsTransport(**endpoint)
        await transport.connect()
        await transport.close()

    asyncio.run(run())
    args, kwargs = streams.connect.call_args
    host = endpoint.get("host", "myhoben.fr")
    assert args == (host, endpoint.get("port", 465))
    context = kwargs["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert kwargs["server_hostname"] == host
    assert kwargs["ssl_handshake_timeout"] == 10.0
    assert kwargs["ssl_shutdown_timeout"] == 5.0
    streams.connect.assert_awaited_once()
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()


def test_exact_bytes_and_drain(streams) -> None:
    """Opaque payloads are neither framed nor interpreted in either direction."""
    payload = b"\x00\x04\x0a\xffSYNTHETIC"
    streams.reader.read.return_value = payload

    async def run():
        transport = AsyncTlsTransport()
        await transport.connect()
        await transport.write(payload)
        assert await transport.read(17) == payload
        await transport.close()

    asyncio.run(run())
    streams.writer.write.assert_called_once_with(payload)
    streams.writer.drain.assert_awaited_once_with()
    streams.reader.read.assert_awaited_once_with(17)


def test_eof(streams) -> None:
    """EOF is distinct from a timeout or a valid nonempty read."""

    async def run():
        transport = AsyncTlsTransport()
        await transport.connect()
        with pytest.raises(TransportEOF, match="peer closed"):
            await transport.read()
        await transport.close()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["connect", "read", "write", "close"])
def test_operation_timeout(streams, deadlines, operation) -> None:
    """The configured deadline cancels a stalled await and reports its operation."""
    target = {
        "connect": streams.connect,
        "read": streams.reader.read,
        "write": streams.writer.drain,
        "close": streams.writer.wait_closed,
    }[operation]
    target.side_effect = deadlines.expire

    async def run():
        transport = AsyncTlsTransport(**{f"{operation}_timeout": 7.0})
        if operation != "connect":
            await transport.connect()
        with pytest.raises(TransportTimeout) as caught:
            if operation == "write":
                await transport.write(b"SYNTHETIC")
            else:
                await getattr(transport, operation)()
        assert caught.value.operation == operation
        assert deadlines.contexts[-1][0] == 7.0
        await transport.close()

    asyncio.run(run())
    if operation == "close":
        streams.writer.transport.abort.assert_called_once_with()
    if operation != "connect":
        streams.writer.close.assert_called_once_with()
        streams.writer.wait_closed.assert_awaited_once_with()


@pytest.mark.parametrize("operation", ["connect", "read", "write", "close"])
def test_stream_errors_are_sanitized(streams, operation) -> None:
    """Even lower-level errors containing payload data are not chained or logged."""
    secret = "SYNTHETIC-IDENTIFIER-AND-PAYLOAD"
    target = {
        "connect": streams.connect,
        "read": streams.reader.read,
        "write": streams.writer.drain,
        "close": streams.writer.wait_closed,
    }[operation]
    target.side_effect = OSError(secret)

    async def run():
        transport = AsyncTlsTransport()
        if operation != "connect":
            await transport.connect()
        with pytest.raises(TransportError) as caught:
            if operation == "write":
                await transport.write(secret.encode())
            else:
                await getattr(transport, operation)()
        assert secret not in "".join(traceback.format_exception(caught.value))
        await transport.close()

    asyncio.run(run())
    streams.connect.assert_awaited_once()


@pytest.mark.parametrize("error_type", [ssl.SSLCertVerificationError, ssl.SSLError])
def test_tls_rejection_has_no_fallback(streams, error_type) -> None:
    """Certificate/hostname/negotiation failures never trigger a second connection."""
    streams.connect.side_effect = error_type("SYNTHETIC-PRIVATE-DETAIL")

    async def run():
        transport = AsyncTlsTransport()
        with pytest.raises(TransportTlsError, match="^TLS verification or negotiation"):
            await transport.connect()
        await transport.close()

    asyncio.run(run())
    streams.connect.assert_awaited_once()
    assert streams.connect.call_args.args == ("myhoben.fr", 465)
    assert streams.connect.call_args.kwargs["ssl"].verify_mode == ssl.CERT_REQUIRED
    streams.writer.write.assert_not_called()


@pytest.mark.parametrize("wait_closed_available", [True, False])
def test_idempotent_close(streams, wait_closed_available) -> None:
    """Closing before connect, after close and with an older stream is safe."""
    if not wait_closed_available:
        del streams.writer.wait_closed

    async def run():
        transport = AsyncTlsTransport()
        await transport.close()
        await transport.connect()
        with pytest.raises(TransportError, match="already connected"):
            await transport.connect()
        await transport.close()
        await transport.close()
        with pytest.raises(TransportError, match="not connected"):
            await transport.read()
        with pytest.raises(TransportError, match="not connected"):
            await transport.write(b"data")

    asyncio.run(run())
    streams.writer.close.assert_called_once_with()
    streams.writer.transport.abort.assert_not_called()
    streams.connect.assert_awaited_once()
    if wait_closed_available:
        streams.writer.wait_closed.assert_awaited_once_with()


def test_cancelled_shutdown_aborts(streams) -> None:
    """Cancellation is preserved and the underlying socket is still released."""
    streams.writer.wait_closed.side_effect = asyncio.CancelledError

    async def run():
        transport = AsyncTlsTransport()
        await transport.connect()
        with pytest.raises(asyncio.CancelledError):
            await transport.close()
        await transport.close()

    asyncio.run(run())
    streams.writer.transport.abort.assert_called_once_with()


@pytest.mark.parametrize(
    "value", ["PRIVATE", bytearray(b"X"), memoryview(b"X"), None, 3]
)
def test_non_bytes_writes_rejected(streams, value) -> None:
    """Reject implicit encodings/conversions before any writer use."""

    async def run():
        transport = AsyncTlsTransport()
        await transport.connect()
        with pytest.raises(TypeError, match="^data must be bytes$"):
            await transport.write(value)
        await transport.close()

    asyncio.run(run())
    streams.writer.write.assert_not_called()
    streams.writer.drain.assert_not_awaited()


@pytest.mark.parametrize("value", [0, -1, True, None, 1.5])
def test_read_requires_positive_size(value) -> None:
    """Zero or unbounded reads must not masquerade as EOF or wait indefinitely."""
    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(AsyncTlsTransport().read(value))


@pytest.mark.parametrize(
    "name", ["connect_timeout", "read_timeout", "write_timeout", "close_timeout"]
)
@pytest.mark.parametrize("value", [0, -1, None, True, float("inf"), float("nan")])
def test_invalid_timeout(name, value) -> None:
    """Timeouts cannot be disabled or made unbounded by configuration."""
    with pytest.raises(ValueError, match="positive finite seconds"):
        AsyncTlsTransport(**{name: value})
