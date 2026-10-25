"""Request-driven synthetic TLS peer for actual persistent-client tests.

Supply complete, independently specified delivery batches. No production
parser is used to decide when a response is delivered or whether it is valid.
"""

import asyncio
from collections import deque
from types import SimpleNamespace


def script_tls(streams, *, openings, reads=(), authorizations=()):
    queue = asyncio.Queue()
    batches = {3: deque(openings), 13: deque(reads), 48: deque(authorizations)}

    def send(packet):
        if packet[0] in batches:
            for item in batches[packet[0]].popleft():
                queue.put_nowait(item)

    async def receive(max_bytes, *, bounded=True):
        item = await queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    streams.reader.read.side_effect = receive
    streams.writer.write.side_effect = send
    return queue


def script_transport(transport, **batches):
    """Same peer batches for tests replacing the transport instead of streams."""
    transport.host, transport.port = "myhoben.fr", 465
    return script_tls(
        SimpleNamespace(
            reader=SimpleNamespace(read=transport.read),
            writer=SimpleNamespace(write=transport.write),
        ),
        **batches,
    )
