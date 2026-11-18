"""Bounded, verified TLS byte streams, independent of MyHOBEN and Home Assistant."""

import asyncio
import math
import ssl
import sys
from asyncio import selector_events, sslproto, trsock

from .close_diagnostic import CloseTrace, emit_termination

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


class _TlsCloseProof:
    """Bind real CPython owners before close; unknown implementations stay refused.

    A TLS close Future can finish with an error although the OS descriptor and
    both SDK transports have been released. Neither that Future nor a callback
    or abort flag proves release: check the captured descriptor, detached owners,
    cancelled SDK timers and the separately reaped close task together.
    """

    @classmethod
    def capture(cls, writer):
        try:
            if sys.implementation.name != "cpython" or sys.version_info[:2] not in {
                (3, 12),
                (3, 14),
            }:
                return None
            if type(writer) is not asyncio.StreamWriter:
                return None
            app, protocol = writer.transport, writer._protocol
            if (
                type(app) is not sslproto._SSLProtocolTransport
                or type(protocol) is not asyncio.StreamReaderProtocol
            ):
                return None
            tls = app._ssl_protocol
            if type(tls) is not sslproto.SSLProtocol:
                return None
            raw = tls._transport
            if type(raw) is not selector_events._SelectorSocketTransport:
                return None
            sock = raw.get_extra_info("socket")
            future = asyncio.StreamReaderProtocol._get_close_waiter(protocol, writer)
            if (
                type(sock) is not trsock.TransportSocket
                or sock.fileno() < 0
                or sock._sock is not raw._sock
                or raw.get_protocol() is not tls
                or app.get_protocol() is not protocol
                or protocol._transport is not app
                or future.done()
            ):
                return None
            proof = cls()
            proof.writer, proof.app, proof.protocol = writer, app, protocol
            proof.tls, proof.raw, proof.socket, proof.future = tls, raw, sock, future
            return proof
        except Exception:
            return None

    def check(self, waiter, error, reaped):
        checks = dict.fromkeys(
            ("socket_closed", "tls_released", "stream_released", "waiter_reaped"), False
        )
        try:
            checks["socket_closed"] = (
                self.socket.fileno() == -1
                and self.raw._sock is None
                and self.raw._loop is None
                and self.raw.get_protocol() is None
                and self.raw._server is None
                and self.raw.is_closing() is True
                and self.raw.get_write_buffer_size() == 0
            )
            checks["tls_released"] = (
                self.tls._transport is None
                and self.tls._app_transport is None
                and self.tls._app_protocol is None
                and self.app.get_protocol() is None
                and self.app.is_closing() is True
                and self.tls._state is sslproto.SSLProtocolState.UNWRAPPED
                and self.tls._handshake_timeout_handle is None
                and self.tls._shutdown_timeout_handle is None
                and not self.tls._write_backlog
                and self.tls._outgoing.pending == 0
            )
            checks["stream_released"] = (
                self.writer.transport is self.app
                and self.writer._protocol is self.protocol
                and asyncio.StreamReaderProtocol._get_close_waiter(
                    self.protocol, self.writer
                )
                is self.future
                and self.protocol._transport is None
                and self.protocol._stream_reader_wr is None
                and self.protocol._stream_writer is None
                and self.protocol._task is None
            )
            checks["waiter_reaped"] = (
                reaped is True
                and isinstance(waiter, asyncio.Task)
                and waiter.done()
                and not waiter.cancelled()
                and waiter.exception() is error
                and self.future.done()
                and not self.future.cancelled()
                and self.future.exception() is error
            )
        except Exception:
            return dict.fromkeys(checks, False)
        return checks


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
        proof = _TlsCloseProof.capture(writer)
        waiter = None
        aborted = False
        tls_error = None
        abort_ok = reaped = False
        deadline = None

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
            deadline = asyncio.get_running_loop().time() + self.close_timeout
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
        except ssl.SSLError as error:
            trace.owner_failure(error)
            abort_ok = abort()
            tls_error = error  # Preserve the error; decide only AFTER real reap.
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
                        reaped = True
            finally:
                trace.finish()
        if tls_error is not None:
            checks = proof.check(waiter, tls_error, reaped) if proof else {}
            verified = (
                proof is not None
                and abort_ok
                and len(checks) == 4
                and all(value is True for value in checks.values())
                and deadline is not None
                and asyncio.get_running_loop().time() < deadline
            )
            emit_termination(trace.generation, checks, verified)
            if not verified:
                raise TransportError("TLS close failed") from None
