"""Real asyncio close waiter and synthetic connection_lost; never a socket."""

import asyncio

import pytest

from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportError,
    TransportTimeout,
)
from tests.test_data_updated_silence import Clock, pump


class Wire(asyncio.Transport):
    def __init__(self, protocol, *, abort_ack=True):
        self.protocol, self.abort_ack = protocol, abort_ack
        self.closed = self.closing = False
        self.closes = self.aborts = 0

    def get_extra_info(self, name, default=None):
        return default

    def is_closing(self):
        return self.closing

    def close(self):
        self.closing = True
        self.closes += 1

    def abort(self):
        self.aborts += 1
        if self.abort_ack:
            self.ack()

    def ack(self, error=None):
        if not self.closed:
            self.closed = True
            self.protocol.connection_lost(error)


def connected(*, abort_ack=True):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    wire = Wire(protocol, abort_ack=abort_ack)
    protocol.connection_made(wire)
    writer = asyncio.StreamWriter(wire, protocol, reader, loop)
    transport = AsyncTlsTransport()
    transport._reader, transport._writer = reader, writer
    return transport, wire, protocol._get_close_waiter(writer)


def test_confirmed_abort_can_finish_without_poisoning_the_real_close_waiter(
    monkeypatch,
):
    async def scenario():
        clock = Clock(monkeypatch)
        transport, wire, closed = connected()
        task = asyncio.create_task(transport.close())
        try:
            await pump()
            for _ in range(5):
                await clock.advance(1.001)
            assert wire.closed and wire.aborts == 1 and wire.closes == 1
            assert not closed.cancelled(), "deadline destroyed the completion proof"
            assert task.done() and task.result() is None
        finally:
            wire.ack()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def no_close_owner():
    assert not any(
        task.get_name() == "hoben-tls-close"
        for task in asyncio.all_tasks()
        if not task.done()
    )


@pytest.mark.parametrize("timeout", [0.5, 5, 7])
@pytest.mark.parametrize("ack", [False, True])
def test_abort_request_is_not_a_proof_and_never_extends_total_deadline(
    monkeypatch, timeout, ack
):
    async def scenario():
        clock = Clock(monkeypatch)
        transport, wire, closed = connected(abort_ack=False)
        transport.close_timeout = timeout
        task = asyncio.create_task(transport.close())
        try:
            await pump()
            reserve = min(1, timeout / 5)
            await clock.advance(timeout - reserve + reserve / 10)
            assert wire.aborts == 1 and not wire.closed
            assert not closed.cancelled() and not task.done()
            if ack:
                wire.ack()
                await pump()
                assert task.done() and task.result() is None
            else:
                await clock.advance(reserve)
                with pytest.raises(TransportTimeout) as error:
                    await task
                assert error.value.operation == "close"
                wire.ack()  # A late callback cannot turn failure into success.
                assert isinstance(task.exception(), TransportTimeout)
            await transport.close()
            assert wire.closes == wire.aborts == 1
            no_close_owner()
        finally:
            wire.ack()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_slow_graceful_close_keeps_its_original_witness_and_needs_no_abort(monkeypatch):
    async def scenario():
        clock = Clock(monkeypatch)
        transport, wire, closed = connected()
        task = asyncio.create_task(transport.close())
        try:
            await pump()
            await clock.advance(3.9)
            assert not task.done() and not closed.cancelled() and wire.aborts == 0
            wire.ack()
            await task
            assert wire.closes == 1 and wire.aborts == 0
            no_close_owner()
        finally:
            wire.ack()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", [0, 3, 4.1])
@pytest.mark.parametrize("double_cancel", [False, True])
def test_explicit_cancellation_during_grace_or_abort_is_never_success(
    monkeypatch, phase, double_cancel
):
    async def scenario():
        clock = Clock(monkeypatch)
        transport, wire, _ = connected(abort_ack=False)
        task = asyncio.create_task(transport.close())
        try:
            await pump()
            await clock.advance(phase)
            task.cancel()
            if double_cancel:
                task.cancel()
            await pump()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert wire.closes == wire.aborts == 1
            no_close_owner()
        finally:
            wire.ack()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("origin", ["close", "wait_closed", "abort"])
def test_shutdown_errors_are_not_accepted_even_with_a_close_callback(
    monkeypatch, origin
):
    async def scenario():
        clock = Clock(monkeypatch)
        transport, wire, _ = connected(abort_ack=False)

        def error():
            wire.ack()
            raise OSError("PRIVATE_PAYLOAD")

        if origin == "wait_closed":
            wire.ack(OSError("PRIVATE_PAYLOAD"))
        else:
            monkeypatch.setattr(wire, origin, error)
        task = asyncio.create_task(transport.close())
        await pump()
        if origin == "abort":
            await clock.advance(4.001)
        with pytest.raises(TransportError) as caught:
            await task
        assert str(caught.value) == "TLS close failed"
        assert caught.value.__suppress_context__
        await transport.close()
        no_close_owner()

    asyncio.run(scenario())
