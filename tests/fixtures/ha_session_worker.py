"""Fixed offline fixtures only. No live mode, secret reader or external socket."""

import asyncio
import errno
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def resources(case):
    if case == "memory":
        payload = bytearray(80 * 1024 * 1024)
        payload[0] = 1
        return
    if case == "resistant":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        ready_r, ready_w = os.pipe()
        if os.fork() == 0:
            os.setsid()
            os.write(ready_w, b"R")
        else:
            assert os.read(ready_r, 1) == b"R"
        while True:
            signal.pause()
    if case == "processes":
        children = []
        try:
            for _ in range(256):
                try:
                    pid = os.fork()
                except OSError as error:
                    if error.errno != errno.EAGAIN:
                        raise
                    break
                if pid == 0:
                    signal.pause()
                    os._exit(0)
                children.append(pid)
        finally:
            for pid in children:
                os.kill(pid, signal.SIGKILL)
            for pid in children:
                os.waitpid(pid, 0)


async def session(case):
    from homeassistant.config_entries import ConfigEntries, ConfigEntry
    from homeassistant.core import HomeAssistant

    from custom_components.hoben.client import HobenClient
    from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
    from custom_components.hoben.transport import (
        AsyncTlsTransport,
        TransportEOF,
        TransportTlsError,
    )
    from scripts.ha_live_proof import empty_evidence
    from scripts.ha_session_observer import observe

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)

    identity = "D" * 32
    response = bytes.fromhex("0effff0000002b010428") + b"\x00\x11" * 20
    opening = (
        bytes([4, 0, 0, 0, 0, 0, 0, 0, 5, 2, 8, 0, 0, 0])
        + identity.encode()
        + b"\x00\x02"
    )
    loss = {
        "close_client": [b"\x05", b"\x03\x0a" + response],
        "eof": [TransportEOF("synthetic-private")],
        "tls": [TransportTlsError("synthetic-private")],
    }.get(case)
    batches = (
        [[[response]] * 6]
        if loss is None
        else [[[response], [response], loss], [[response]] * 3]
    )
    if case == "read_timeout":
        batches = [[[]]]
    wires = []

    class Wire(AsyncTlsTransport):
        def __init__(self):
            super().__init__()
            self.queue, self.reads = asyncio.Queue(), iter(batches[len(wires)])
            wires.append(self)

        async def connect(self):
            pass

        async def write(self, packet):
            if packet[0] == 3:
                self.queue.put_nowait(opening)
            elif packet[0] == 13:
                assert packet == bytes.fromhex("0dffff00000006010404000014")
                for value in next(self.reads):
                    self.queue.put_nowait(value)
            elif packet != b"\x0b":
                raise AssertionError("unexpected offline TX")

        async def read(self, max_bytes=4096, *, bounded=True):
            value = await self.queue.get()
            if isinstance(value, Exception):
                raise value
            assert len(value) <= max_bytes
            return value

        async def close(self):
            pass

    with tempfile.TemporaryDirectory() as directory:
        hass = HomeAssistant(directory)
        hass.config_entries = ConfigEntries(hass, {})
        entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain="hoben",
            data={
                "user_guid": "12345678123456781234567812345678",
                "device_guid": identity,
            },
            options={},
            source="user",
            title="Offline",
            unique_id=None,
            discovery_keys={},
            subentries_data=[],
        )
        client = HobenClient(
            entry.data["user_guid"],
            identity,
            read_timeout=0.01 if case == "read_timeout" else 30,
        )
        coordinator = HobenDataUpdateCoordinator(hass, entry, client)
        now = 0.0

        async def sleep(delay):
            nonlocal now
            now += delay
            await asyncio.sleep(0)

        try:
            evidence = empty_evidence()
            with patch("custom_components.hoben.client.AsyncTlsTransport", Wire):
                try:
                    return await observe(
                        coordinator, clock=lambda: now, sleep=sleep, evidence=evidence
                    )
                except asyncio.CancelledError:
                    return evidence
        finally:
            await client.async_close()
            await hass.async_stop()


def main():
    # The PID 1 guardian drops all supplementary groups and root capabilities.
    if os.getuid() != 65534 or os.getgid() != 65534:
        return 1
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if int(status["CapEff"], 16) != 0 or status["NoNewPrivs"].strip() != "1":
        return 1
    if os.access("/sys/fs/cgroup/cgroup.procs", os.W_OK):
        return 1
    case = sys.argv[1]
    if case in {"memory", "processes", "resistant"}:
        resources(case)
        from scripts.ha_live_proof import empty_evidence

        evidence = empty_evidence()
    elif case == "forged":
        evidence = {"private": "PRIVATE_PAYLOAD"}
    else:
        if case not in {"healthy", "close_client", "eof", "tls", "read_timeout"}:
            return 1
        evidence = asyncio.run(session(case))
    encoded = json.dumps(evidence, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 8192:
        return 1
    os.write(int(os.environ["HA_EVIDENCE_FD"]), encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
