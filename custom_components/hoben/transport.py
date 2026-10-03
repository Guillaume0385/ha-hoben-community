"""Bounded, verified TLS byte streams, independent of MyHOBEN and Home Assistant."""

import asyncio
import math
import ssl

DEFAULT_HOST = "myhoben.fr"
DEFAULT_PORT = 465


class TransportError(Exception):
    """A transport failure with a payload-free message."""


class TransportTimeout(TransportError, TimeoutError):
    """A bounded operation expired; only its name is retained."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"TLS {operation} timed out")


class TransportEOF(TransportError, EOFError):
    """The peer closed its byte stream."""


class TransportTlsError(TransportError):
    """TLS certificate verification or negotiation failed."""


class AsyncTlsTransport:
    """One TLS connection with raw reads and exact writes, without retries.

    Timeouts are positive finite seconds. TLS uses the system trust store and
    the requested hostname, including SNI. There is no plaintext or unverified
    mode. Tests replace asyncio streams, never the certificate-verification rules.
    A caller owns the lifecycle and must close after success, error or cancellation.
    Operations on one instance must be serialized by the caller.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        connect_timeout: float = 10.0,
        read_timeout: float = 10.0,
        write_timeout: float = 10.0,
        close_timeout: float = 5.0,
    ) -> None:
        if not isinstance(host, str) or not host:
            raise ValueError("host must be a nonempty string")
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
        ):
            raise ValueError("port must be an integer between 1 and 65535")
        for name, value in (
            ("connect_timeout", connect_timeout),
            ("read_timeout", read_timeout),
            ("write_timeout", write_timeout),
            ("close_timeout", close_timeout),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive finite seconds")
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self.close_timeout = close_timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        """Connect once with certificate/hostname verification and bounded TLS I/O."""
        if self._writer is not None:
            raise TransportError("TLS transport is already connected")
        try:
            async with asyncio.timeout(self.connect_timeout):
                # Loading the system CA store performs filesystem I/O.
                context = await asyncio.to_thread(ssl.create_default_context)
                self._reader, self._writer = await asyncio.open_connection(
                    self.host,
                    self.port,
                    ssl=context,
                    server_hostname=self.host,
                    ssl_handshake_timeout=self.connect_timeout,
                    ssl_shutdown_timeout=self.close_timeout,
                )
        except TimeoutError:
            raise TransportTimeout("connect") from None
        except ssl.SSLError:
            raise TransportTlsError("TLS verification or negotiation failed") from None
        except OSError:
            raise TransportError("TLS connect failed") from None

    async def write(self, data: bytes) -> None:
        """Write exactly data and drain; never include data in an error or log."""
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        if self._writer is None:
            raise TransportError("TLS transport is not connected")
        try:
            async with asyncio.timeout(self.write_timeout):
                self._writer.write(data)
                await self._writer.drain()
        except TimeoutError:
            raise TransportTimeout("write") from None
        except OSError:
            raise TransportError("TLS write failed") from None

    async def read(self, max_bytes: int = 4096) -> bytes:
        """Return unaltered bytes, or raise TransportEOF on an empty stream read."""
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes <= 0
        ):
            raise ValueError("max_bytes must be a positive integer")
        if self._reader is None:
            raise TransportError("TLS transport is not connected")
        try:
            async with asyncio.timeout(self.read_timeout):
                data = await self._reader.read(max_bytes)
        except TimeoutError:
            raise TransportTimeout("read") from None
        except OSError:
            raise TransportError("TLS read failed") from None
        if not data:
            raise TransportEOF("TLS peer closed the stream")
        return data

    async def close(self) -> None:
        """Close once and await shutdown; abort if shutdown fails or is cancelled.

        State is detached first, so repeated close calls are harmless even after
        a failed shutdown. Errors are sanitized just like read/write failures.
        """
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is None:
            return
        try:
            writer.close()
            if (wait_closed := getattr(writer, "wait_closed", None)) is not None:
                async with asyncio.timeout(self.close_timeout):
                    await wait_closed()
        except TimeoutError:
            writer.transport.abort()
            raise TransportTimeout("close") from None
        except OSError:
            writer.transport.abort()
            raise TransportError("TLS close failed") from None
        except asyncio.CancelledError:
            writer.transport.abort()
            raise
