"""Offline stream doubles and deterministic asyncio deadline control."""

import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any accidental live DNS lookup or socket connection fails the normal suite."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Network access is forbidden in automated tests")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def streams(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace only the stream connection; real verified SSL contexts stay enabled."""
    reader = SimpleNamespace(read=AsyncMock(return_value=b""))
    writer = SimpleNamespace(
        write=Mock(),
        drain=AsyncMock(),
        close=Mock(),
        wait_closed=AsyncMock(),
        transport=SimpleNamespace(abort=Mock()),
    )
    connect = AsyncMock(return_value=(reader, writer))
    monkeypatch.setattr(asyncio, "open_connection", connect)
    return SimpleNamespace(reader=reader, writer=writer, connect=connect)


@pytest.fixture
def deadlines(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Expire a real asyncio timeout at a chosen await, without wall-clock sleeps."""
    original_timeout = asyncio.timeout
    contexts = []

    def capture_timeout(delay):
        context = original_timeout(delay)
        contexts.append((delay, context))
        return context

    async def expire(*args, **kwargs):
        contexts[-1][1].reschedule(asyncio.get_running_loop().time())
        await asyncio.Future()

    monkeypatch.setattr(asyncio, "timeout", capture_timeout)
    return SimpleNamespace(contexts=contexts, expire=expire)
