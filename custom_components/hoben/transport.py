"""Bounded, verified TLS byte streams, independent of MyHOBEN and Home Assistant."""

import asyncio
import math
import ssl

from .close_diagnostic import CloseTrace

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


class TransportCertificateError(TransportTlsError):
    """Certificate or hostname verification failed, distinct from negotiation."""


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
        except ssl.SSLCertVerificationError:
            raise TransportCertificateError(
                "TLS verification or negotiation failed"
            ) from None
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

    async def read(self, max_bytes: int = 4096, *, bounded: bool = True) -> bytes:
        """Return unaltered bytes, or raise TransportEOF on an empty stream read.

        One-shot reads retain their deadline by default. A persistent RX owner
        can wait without an application idle deadline using bounded=False;
        silence alone establishes neither connection loss nor message framing.
        Cancellation and TLS/stream errors remain effective in either mode.
        """
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes <= 0
        ):
            raise ValueError("max_bytes must be a positive integer")
        if self._reader is None:
            raise TransportError("TLS transport is not connected")
        if not isinstance(bounded, bool):
            raise ValueError("bounded must be bool")
        try:
            async with asyncio.timeout(self.read_timeout if bounded else None):
                data = await self._reader.read(max_bytes)
        except TimeoutError:
            raise TransportTimeout("read") from None
        except OSError:
            raise TransportError("TLS read failed") from None
        if not data:
            raise TransportEOF("TLS peer closed the stream")
        return data

    async def close(self) -> None:
        """Close once, proving shutdown even when graceful TLS close stalls.

        State is detached first, so repeated close calls are harmless even after
        a failed shutdown. Reserve the last fifth (at most one second) of the
        existing deadline for abort and its connection_lost acknowledgement.
        An abort request alone never proves closure. Errors remain sanitized.
        """
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is None:
            return
        trace = CloseTrace(writer, self.close_timeout)
        waiter = None
        aborted = False

        def abort() -> bool:
            nonlocal aborted
            if not aborted:
                aborted = True
                try:
                    with trace.operation("abort"):
                        writer.transport.abort()
                except Exception:
                    return False
            return True

        try:
            with trace.operation("writer_close"):
                writer.close()
            async with asyncio.timeout(self.close_timeout):
                # Cancelling StreamWriter.wait_closed cancels its shared close
                # future. Own one waiter and leave it intact at the graceful
                # deadline, so a subsequent abort can still prove completion.
                async def wait_closed():
                    with trace.operation("wait_closed"):
                        await writer.wait_closed()

                waiter = asyncio.create_task(wait_closed(), name="hoben-tls-close")
                reserve = min(1.0, self.close_timeout / 5)
                done, _ = await asyncio.wait(
                    {waiter}, timeout=self.close_timeout - reserve
                )
                if not done and not abort():
                    raise TransportError("TLS close failed")
                await asyncio.shield(waiter)
        except TimeoutError as error:
            trace.owner_failure(error)
            abort()
            raise TransportTimeout("close") from None
        except Exception as error:
            trace.owner_failure(error)
            abort()
            raise TransportError("TLS close failed") from None
        except asyncio.CancelledError as error:
            trace.owner_failure(error)
            abort()
            raise
        finally:
            try:
                if waiter is not None:
                    with trace.operation("reap"):
                        if not waiter.done():
                            waiter.cancel()
                        await asyncio.gather(waiter, return_exceptions=True)
            finally:
                trace.finish()
