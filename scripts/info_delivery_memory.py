"""Bounded #186-D4 memory/clock ports. No socket, TLS, CLI or opt-in supplier."""

import asyncio

from scripts.info_delivery_scenario import (
    InfoDeliveryScenario,
    OfflineTransportLedger,
    require,
)

READ_ONLY_V4 = bytes.fromhex("0dffff00000006010404000014")


class OfflineClock:
    """Explicit virtual time; fixtures install loop_time on their isolated loop."""

    def __init__(self, *, origin):
        require(type(origin) in (int, float) and origin >= 0)
        self.now_ms = 0
        self._origin = origin
        self.loop_time = lambda: self._origin + self.now_ms / 1000
        self._waiters = set()

    def advance_to(self, at_ms):
        require(type(at_ms) is int and self.now_ms <= at_ms <= 4_000_000)
        self.now_ms = at_ms
        for deadline, future in tuple(self._waiters):
            if deadline <= at_ms and not future.done():
                future.set_result(None)

    async def until(self, at_ms):
        require(type(at_ms) is int and 0 <= at_ms <= 4_000_000)
        if self.now_ms >= at_ms:
            return
        future = asyncio.get_running_loop().create_future()
        pair = (at_ms, future)
        self._waiters.add(pair)
        try:
            await future
        finally:
            self._waiters.discard(pair)


class MemoryTransport:
    """Only memory I/O. Fixture supplies synthetic opening/replies/faults.

    One reader and one TX at a time, 32 queued deliveries, 256 deliveries/TX,
    4096 bytes/delivery. These are fixture caps, never claims about wire framing.
    Nothing raw is retained in the ledger or returned report.
    """

    def __init__(self, *, opening, replies=(), close_ms=0, close_fails=False):
        require(type(opening) is bytes and 1 <= len(opening) <= 4096)
        require(type(replies) is tuple and len(replies) <= 32)
        require(
            all(
                (type(item) is bytes and len(item) <= 4096)
                or isinstance(item, Exception)
                for item in replies
            )
        )
        require(type(close_ms) is int and 0 <= close_ms <= 60000)
        require(type(close_fails) is bool)
        self._opening, self._replies = opening, replies
        self._close_ms, self._close_fails = close_ms, close_fails
        self.queue = asyncio.Queue(maxsize=32)
        self.changed = asyncio.Event()
        self.active_reads = self.active_tx = 0
        self.connect_count = self.openings = self.close_count = 0
        self.deliveries = self.transmissions = self.requests = self.pongs = 0
        self.closed = False
        self.plaintext_deliveries = self.plaintext_bytes = 0
        self._ports_claim = self._delivery_port = None
        self.session = self.clock = self.scenario = None
        self.ledger = OfflineTransportLedger(self)
        self.frozen = False

    def feed(self, delivery):
        require(type(delivery) is bytes or isinstance(delivery, Exception))
        if type(delivery) is bytes:
            require(len(delivery) <= 4096)
        require(not self.closed and not self.queue.full())
        self.queue.put_nowait(delivery)

    def _begin_evidence(self):
        if self.scenario is None:
            for _ in range(self.connect_count):
                self.ledger.note("connect")
            if self.openings:
                self.ledger.note("opening")
            if self.closed:
                self.ledger.note("close_completed")
            self.scenario = InfoDeliveryScenario(
                self.session, self.ledger, clock=lambda: self.clock.now_ms / 1000
            )
            self.sample()

    def sample(self):
        if self.scenario is not None and not self.frozen and not self.active_tx:
            self.scenario.sample()

    async def connect(self):
        require(self.connect_count == 0 and not self.closed)
        self.connect_count += 1

    async def read(self, max_bytes=4096, *, bounded=True):
        require(self.active_reads == 0 and not self.closed)
        self.sample()  # Previous delivery has passed through the real RX owner.
        self.changed.set()
        self.active_reads += 1
        try:
            if bounded:
                require(self.openings == 0)
                self.openings += 1
                data, self._opening = self._opening, b""
            else:
                data = await self.queue.get()
                self.deliveries += 1
                require(self.deliveries <= 256)
                if isinstance(data, Exception):
                    raise data
                self.plaintext_deliveries += 1
                self.plaintext_bytes += len(data)
                if self._delivery_port is not None:
                    self._delivery_port.delivered(data)
                if data[:1] == b"\x0c":
                    self._begin_evidence()
                if self.scenario is not None and not self.frozen:
                    self.ledger.note(
                        "info_candidate"
                        if data[:1] == b"\x0c"
                        else "ping"
                        if data == b"\x0a"
                        else "other",
                        len(data),
                    )
            require(len(data) <= max_bytes)
            return data
        finally:
            self.active_reads -= 1
            self.changed.set()

    async def write(self, data):
        require(self.active_tx == 0 and not self.closed)
        # Opening bytes are generated by the real session. Only the opening
        # phase may send them; afterwards only Pong and fixed read-only V4.
        opening = self.transmissions == 0 and data[:1] == b"\x03"
        require(opening or data in (b"\x0b", READ_ONLY_V4))
        require(self.transmissions < 256)
        self.transmissions += 1
        self.active_tx += 1
        try:
            if data == READ_ONLY_V4:
                self.requests += 1
                require(self.requests == 1)
                if self.scenario is not None and not self.frozen:
                    self.ledger.note("request")
                for reply in self._replies:
                    self.feed(reply)
            await asyncio.sleep(0)
            if self.scenario is not None and not self.frozen:
                if data == READ_ONLY_V4:
                    self.ledger.note("request_completed")
                elif data == b"\x0b":
                    self.ledger.note("pong")
            self.pongs += data == b"\x0b"
        finally:
            self.active_tx -= 1
            self.changed.set()

    async def close(self):
        self.close_count += 1
        require(self.close_count == 1)
        # The memory transport itself bounds close too: the real RX/read
        # error path can invoke it BEFORE the adapter starts its own teardown.
        async with asyncio.timeout(5):
            await self.clock.until(self.clock.now_ms + self._close_ms)
        if self._close_fails:
            raise RuntimeError("synthetic_close_failure")
        require(self.active_reads == self.active_tx == 0)
        self.closed = True
        if self.scenario is not None:
            self.ledger.note("close_completed")
        self.changed.set()


class MemoryFactory:
    """Exact, one-use memory port, never a caller's network factory callback."""

    def __init__(self, transport):
        require(type(transport) is MemoryTransport)
        self.transport, self.calls = transport, 0

    def __call__(self):
        require(self.calls == 0)
        self.calls += 1
        return self.transport
