"""Real asyncio ownership/OS-descriptor cleanup; no network connection or TLS I/O.

A local socketpair supplies disposable descriptors only. Hoben bytes and close
faults are injected in memory. The SDK's SSLProtocol.connection_lost and selector
finalizer run unmodified, so a callback flag cannot fake descriptor release.
"""

import asyncio
import socket
import ssl
from asyncio import selector_events, sslproto
from types import SimpleNamespace

import pytest

from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportError,
    TransportTimeout,
    _TlsCloseProof,
)
from tests.test_data_updated_silence import Clock, pump
from tests.test_tls_cleanup_b9 import no_close_owner


class TlsStack:
    """Fault injection surrounds genuine CPython protocols and a local fd."""

    def __init__(self, *, mode="tls", delay=0.049, context=None):
        loop = asyncio.get_running_loop()
        self.reader = asyncio.StreamReader()
        self.protocol = asyncio.StreamReaderProtocol(self.reader)
        context = context or ssl.create_default_context()
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        self.tls = sslproto.SSLProtocol(
            loop,
            self.protocol,
            context,
            None,
            server_hostname="myhoben.fr",
            call_connection_made=False,
        )
        self.app = self.tls._get_app_transport()
        left, self.peer = socket.socketpair()
        left.setblocking(False)
        self.raw = selector_events._SelectorSocketTransport(
            loop, left, asyncio.Protocol()
        )
        self.raw.set_protocol(self.tls)
        self.tls._transport = self.raw
        # The accepted opening is outside this fixture. No SSL handshake or
        # socket data is sent: inject only its already-established state.
        self.tls._state = sslproto.SSLProtocolState.WRAPPED
        self.protocol.connection_made(self.app)
        self.writer = asyncio.StreamWriter(self.app, self.protocol, self.reader, loop)
        self.socket = self.raw.get_extra_info("socket")
        self.future = self.protocol._get_close_waiter(self.writer)
        self.mode, self.delay = mode, delay
        self.close_count = 0
        self.error = (
            ssl.SSLError("SYNTHETIC_PRIVATE")
            if mode not in {"other", "ok"}
            else None
            if mode == "ok"
            else OSError("SYNTHETIC_PRIVATE")
        )
        self.timer = None

        def start_shutdown():
            self.close_count += 1
            if mode != "timeout":
                self.timer = loop.call_later(delay, self.finish)

        self.tls._start_shutdown = start_shutdown
        if mode == "timeout":
            self.tls._abort = lambda error: None
        self.transport = AsyncTlsTransport()
        self.transport._reader, self.transport._writer = self.reader, self.writer

    def finish(self):
        if self.mode == "callback_only":
            # All TLS/app callbacks happen, but the physical fd is still live.
            self.tls.connection_lost(self.error)
        elif self.mode == "missing_callback":
            # A manually completed close Future is not its owner's cleanup.
            self.raw.set_protocol(asyncio.Protocol())
            self.raw._force_close(self.error)
            self.future.set_exception(self.error)
        else:
            self.raw._force_close(self.error)

    async def cleanup(self):
        if self.timer is not None:
            self.timer.cancel()
        if self.raw._sock is not None:
            self.raw._force_close(None)
        await pump()
        if self.tls._transport is not None:
            self.tls.connection_lost(None)
            await pump()
        if not self.future.done():
            self.protocol.connection_lost(None)
        if self.future.done() and not self.future.cancelled():
            self.future.exception()
        self.peer.close()
        assert self.socket.fileno() == -1


@pytest.mark.parametrize("logger_error", [None, RuntimeError, asyncio.CancelledError])
def test_tls_error_with_independent_resource_release_is_not_false_cleanup_failure(
    monkeypatch, caplog, logger_error
):
    if logger_error is not None:

        def broken_logger(*args, **kwargs):
            raise logger_error("SYNTHETIC_PRIVATE")

        monkeypatch.setattr(
            "custom_components.hoben.close_diagnostic._TERMINATION_LOGGER.debug",
            broken_logger,
        )

    async def run():
        clock = Clock(monkeypatch)
        wire = TlsStack()
        task = asyncio.create_task(wire.transport.close())
        try:
            await pump()
            assert not task.done() and wire.socket.fileno() >= 0
            await clock.advance(0.049)
            assert wire.socket.fileno() == -1
            assert wire.raw.get_protocol() is None and wire.raw._loop is None
            assert wire.app.get_protocol() is None
            assert wire.protocol._transport is None
            assert wire.future.done() and isinstance(
                wire.future.exception(), ssl.SSLError
            )
            await task  # RED: old code reports cleanup_failed despite all proofs.
            no_close_owner()
            await wire.transport.close()
            assert wire.close_count == 1
            assert "SYNTHETIC_PRIVATE" not in caplog.text
        finally:
            await wire.cleanup()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["timeout", "cancel", "double"])
def test_deadline_cancellation_and_double_close_keep_one_original_owner(
    monkeypatch, mode
):
    async def run():
        clock = Clock(monkeypatch)
        wire = TlsStack(mode="timeout" if mode == "timeout" else "tls")
        task = asyncio.create_task(wire.transport.close())
        try:
            await pump()
            if mode == "timeout":
                await clock.advance(4.001)
                assert wire.socket.fileno() >= 0 and not task.done()
                await clock.advance(1)
                with pytest.raises(TransportTimeout):
                    await task
            elif mode == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await wire.transport.close()
                assert not task.done() and wire.socket.fileno() >= 0
                await clock.advance(0.049)
                await task
            assert wire.close_count == 1
            no_close_owner()
        finally:
            await wire.cleanup()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_reaped_task_and_callback_cannot_replace_detached_sdk_owners(monkeypatch):
    async def run():
        clock = Clock(monkeypatch)
        wire = TlsStack()
        proof = _TlsCloseProof.capture(wire.writer)
        task = asyncio.create_task(wire.transport.close())
        try:
            await pump()
            waiter = next(
                t for t in asyncio.all_tasks() if t.get_name() == "hoben-tls-close"
            )
            await clock.advance(0.049)
            await task
            assert all(proof.check(waiter, wire.error, True).values())
            assert not proof.check(waiter, wire.error, False)["waiter_reaped"]
            # A still-owned SDK timer or protocol is independent of fd closure.
            handle = asyncio.get_running_loop().call_later(60, lambda: None)
            wire.tls._shutdown_timeout_handle = handle
            assert not proof.check(waiter, wire.error, True)["tls_released"]
            handle.cancel()
            wire.tls._shutdown_timeout_handle = None
            wire.protocol._transport = wire.app
            assert not proof.check(waiter, wire.error, True)["stream_released"]
            wire.protocol._transport = None
        finally:
            await wire.cleanup()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_termination_diagnostic_is_bounded_and_does_not_rewrite_tls_failure(
    monkeypatch, caplog
):
    caplog.set_level("DEBUG", logger="custom_components.hoben.close_diagnostic")

    async def run():
        clock = Clock(monkeypatch)
        wire = TlsStack()
        task = asyncio.create_task(wire.transport.close())
        try:
            await pump()
            await clock.advance(0.049)
            await task
            traces = [
                r.hoben_tls_close
                for r in caplog.records
                if hasattr(r, "hoben_tls_close")
            ]
            assert traces[0]["first_failure"]["result"] == "raised_tls"
            assert traces[0]["future"] == "completed_error"
            records = [r for r in caplog.records if hasattr(r, "hoben_tls_termination")]
            assert len(records) == 1
            assert records[0].hoben_tls_termination["result"] == "verified"
            assert len(records[0].getMessage()) < 1024
            assert "SYNTHETIC_PRIVATE" not in caplog.text
        finally:
            await wire.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["callback_only", "missing_callback", "other"])
def test_partial_witness_or_non_tls_error_never_authorizes_cleanup(monkeypatch, mode):
    async def run():
        clock = Clock(monkeypatch)
        wire = TlsStack(mode=mode)
        task = asyncio.create_task(wire.transport.close())
        try:
            await pump()
            await clock.advance(0.049)
            with pytest.raises(TransportError, match="TLS close failed"):
                await task
            if mode == "callback_only":
                assert wire.socket.fileno() >= 0
            no_close_owner()
        finally:
            await wire.cleanup()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    ["unknown_writer", "changed_future", "unsupported_python", "unsupported_sdk"],
)
def test_unknown_sdk_or_changed_close_future_is_never_a_release_permission(
    monkeypatch, fault
):
    async def run():
        clock = Clock(monkeypatch)
        wire = TlsStack()
        original = wire.future
        if fault.startswith("unsupported_"):
            monkeypatch.setattr(
                "custom_components.hoben.transport.sys",
                SimpleNamespace(
                    implementation=SimpleNamespace(
                        name="other" if fault == "unsupported_sdk" else "cpython"
                    ),
                    version_info=(3, 99) if fault == "unsupported_python" else (3, 12),
                ),
            )
        if fault == "unknown_writer":

            class OtherWriter(asyncio.StreamWriter):
                pass

            wire.transport._writer = OtherWriter(
                wire.app, wire.protocol, wire.reader, asyncio.get_running_loop()
            )
        task = asyncio.create_task(wire.transport.close())
        try:
            await pump()
            if fault == "changed_future":
                wire.protocol._closed = asyncio.get_running_loop().create_future()
            await clock.advance(0.049)
            if fault == "changed_future":
                original.set_exception(wire.error)
                await pump()
            with pytest.raises(TransportError):
                await task
            assert wire.socket.fileno() == -1
            if wire.protocol._closed.done() and not wire.protocol._closed.cancelled():
                wire.protocol._closed.exception()
            no_close_owner()
        finally:
            await wire.cleanup()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
