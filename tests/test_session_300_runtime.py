"""Synthetic stream tests of the explicitly opted-in session-300 path."""

import asyncio

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.v4_experiment import (
    ExperimentalV4Framer,
    Session300,
    Session300BudgetError,
)
from custom_components.hoben.v4_session import HandoffState, V4Session
from tests.test_v4_session import opened_prefix


def response():
    return bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"\x00\x11" * 20


@pytest.mark.parametrize("split", range(1, 52))
def test_every_split_preserves_order_and_originating_exchange(split):
    data = b"\x0a" + response() + b"\x0a"
    framer = ExperimentalV4Framer()
    first, later = object(), object()
    events = framer.feed(data[:split], first) + framer.feed(data[split:], later)
    assert [event.payload for event in events] == [b"\x0a", response(), b"\x0a"]
    assert events[1].exchange is (first if split > 1 else later)
    assert not framer.partial
    assert repr(events[1]) == "ExperimentalFrame()"


def test_byte_by_byte_framing_and_no_resynchronization():
    framer, exchange = ExperimentalV4Framer(), object()
    events = []
    for byte in response():
        events.extend(framer.feed(bytes([byte]), exchange))
    assert len(events) == 1 and events[0].payload == response()
    for invalid in (
        b"\x1b",
        b"\xff",
        bytes.fromhex("0e000100010003"),
        bytes.fromhex("0e000100000001"),
        bytes.fromhex("0e00010000ffff"),
    ):
        with pytest.raises(HobenProtocolError):
            ExperimentalV4Framer().feed(invalid + b"\x0a", exchange)


class Stream:
    def __init__(self, chunks=(), suffix=b""):
        self.queue = asyncio.Queue()
        self.prefix = opened_prefix() + suffix
        self.chunks = chunks
        self.writes = []
        self.close_count = self.active_reads = self.active_tx = 0
        self.started = asyncio.Event()

    async def connect(self):
        pass

    async def read(self, max_bytes=4096, *, bounded=True):
        assert self.active_reads == 0
        self.active_reads += 1
        try:
            if bounded:
                prefix, self.prefix = self.prefix, b""
                return prefix
            self.started.set()
            data = await self.queue.get()
            if isinstance(data, Exception):
                raise data
            return data
        finally:
            self.active_reads -= 1

    async def write(self, payload):
        assert self.active_tx == 0
        self.active_tx += 1
        try:
            self.writes.append(payload)
            if payload[0] == 13:
                for chunk in self.chunks:
                    self.queue.put_nowait(chunk)
            await asyncio.sleep(0)
        finally:
            self.active_tx -= 1

    async def close(self):
        self.close_count += 1


@pytest.mark.parametrize("split", range(1, 50))
def test_real_shared_rx_handles_fragmented_response_and_pings(split):
    async def scenario():
        data = response()
        stream = Stream([b"\x0a" + data[:split], data[split:] + b"\x0a"])
        budget = Session300()
        session = V4Session(
            user_guid="b" * 32, transport_factory=lambda: stream, session_300=budget
        )
        await session.connect()
        result = await session.request_v4_data()
        while budget.pongs < 2:
            await asyncio.sleep(0)
        assert result.registers == (17,) * 20
        assert budget.requests == budget.responses == 1
        assert budget.pings == budget.pongs == 2
        assert stream.writes[1:] == [
            bytes.fromhex("0DFFFF00000006010404000014"),
            b"\x0b",
            b"\x0b",
        ]
        assert session.snapshot.handoff is HandoffState.EXPERIMENTAL
        assert session.snapshot.boundary_proven is False
        await session.abort()
        assert session._rx_task.done() and not session._operations
        assert stream.active_reads == stream.active_tx == 0
        assert stream.close_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("data", [response() * 2, b"\x1b", b"\xff", response()[:-1]])
def test_bad_or_duplicate_rx_cannot_complete_a_read(data):
    async def scenario():
        stream = Stream([data, b""])
        session = V4Session(
            user_guid="b" * 32,
            session_300=Session300(),
            transport_factory=lambda: stream,
        )
        await session.connect()
        with pytest.raises(HobenProtocolError):
            await session.request_v4_data()
        await session.abort()
        assert stream.close_count == 1 and session._pending_read is None

    asyncio.run(scenario())


def test_opening_coalesced_response_is_not_assigned_to_new_read():
    async def scenario():
        stream = Stream(suffix=response())
        session = V4Session(
            user_guid="b" * 32,
            session_300=Session300(),
            transport_factory=lambda: stream,
        )
        await session.connect()
        with pytest.raises(HobenProtocolError):
            await session.request_v4_data()
        await session.abort()
        assert stream.close_count == 1

    asyncio.run(scenario())


def test_shared_limits_and_cadence_are_strict_across_instances():
    now = [0]
    budget = Session300(clock=lambda: now[0])
    for _ in range(3):
        budget.opening()
    with pytest.raises(Session300BudgetError):
        budget.opening()
    budget.request()
    with pytest.raises(Session300BudgetError):
        budget.request()
    for _ in range(5):
        now[0] += 60
        budget.request()
    now[0] += 60
    with pytest.raises(Session300BudgetError):
        budget.request()
    for _ in range(256):
        budget.receive(b"x" * 4096)
    with pytest.raises(Session300BudgetError):
        budget.receive(b"x")
    assert budget.opens == 3 and budget.requests == 6


def test_an_old_generation_cannot_mark_a_new_session_lost():
    budget = Session300()
    budget.opening()
    budget.accepted(1)
    budget.opening()
    assert not budget.usable
    budget.accepted(2)
    budget.lost(1)
    assert budget.usable
    budget.lost(2)
    assert not budget.usable
