"""Test-only bootstrap for the real isolated H1/H2 entry point, without sockets.

The simulated server accepts only a fabricated zero UserGuid. Injection happens
after the real entry module loads under -I and its local context checks pass.
No production flag, destination override, gate bypass or fake report is added.
"""

import importlib.util
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

ZERO_IDENTITY = "0" * 32
PRIVATE = "SYNTHETIC-PRIVATE-PYTHON-EXPRESSION"
ROOT = Path(__file__).resolve().parents[1]


def main(candidate: Path, scenario: str) -> int:
    network_attempts = []

    def forbid_network(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
            network_attempts.append(True)
            raise AssertionError("Network forbidden in the simulated campaign")

    sys.addaudithook(forbid_network)
    # Load the unmodified entry module before adding any repository to sys.path:
    # a regression to startup imports must fail under actual isolated Python.
    spec = importlib.util.spec_from_file_location(
        "isolated_experimental_entry",
        candidate / "scripts/run_experimental_boundary.py",
    )
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    original_import = entry.importlib.import_module
    servers, spacing = [], []

    def install_server(name):
        assert name == "scripts.probe_opened_client_boundary"
        if scenario == "import_error":
            raise SyntaxError(PRIVATE)
        probe = original_import(name)
        capture = sys.modules["scripts.boundary_capture"]
        assert Path(capture.__file__).resolve().is_relative_to(candidate)
        # Reuse existing safe synthetic fixtures and virtual-clock transport.
        # Production modules are already loaded from the candidate checkout.
        sys.path.append(str(ROOT))
        from tests.test_boundary_observations import (
            NOTIFICATION,
            RESPONSE,
            VirtualStream,
        )
        from tests.test_post_open_handoff import OPENED_PREFIX

        class SimulatedServer(VirtualStream):
            def __init__(self):
                super().__init__(replies=False)
                self.mode = "H1" if len(servers) < 6 else "H2"
                self.opens = self.requests = self.pongs = 0
                self.initial_device = len(servers) == 0

            async def connect(self):
                await super().connect()
                if scenario == "dns_tls_error":
                    raise OSError(PRIVATE)

            async def write(self, payload):
                if payload[:1] == b"\x03":
                    if scenario == "open_error":
                        raise KeyError(PRIVATE)
                    assert self.opens == 0
                    # Independent OpenClient wire expectations: zero secret,
                    # protocol marker/build and zero -> assigned identity reuse.
                    assert payload[:37] == b"\x03" + b"0" * 32 + b"\x00\x01\x22\x00"
                    device = b"0" * 32 if self.initial_device else OPENED_PREFIX[14:46]
                    assert payload[37:69] == device
                    assert payload[69:] == capture.DEFAULT_DEVICE_INFO.encode()
                    self.opens += 1
                    self.script.append((0.005, b"\x0a"))
                    if scenario == "coalesced":
                        self.script.append(
                            (0.01, OPENED_PREFIX + b"\x0a" + NOTIFICATION)
                        )
                    else:
                        self.script.extend(
                            [
                                (0.01, OPENED_PREFIX[:19]),
                                (0.02, OPENED_PREFIX[19:]),
                                (0.05, b"\x0a" + NOTIFICATION),
                            ]
                        )
                elif payload == b"\x0b":
                    self.pongs += 1
                else:
                    assert self.mode == "H2" and self.requests < 2
                    assert payload == bytes.fromhex("0D FFFF 0000 0006 01 04 0400 0014")
                    self.requests += 1
                    if scenario == "expression_error":
                        response = NameError(PRIVATE)
                    elif scenario == "invalid_response":
                        response = b"\x0e\xff\xff\x00\x00\x00\x01\x01"
                    else:
                        response = RESPONSE
                    if scenario == "fragmented":
                        self.script.extend(
                            [
                                (self.now + 0.25, response[:8]),
                                (self.now + 0.5, response[8:]),
                            ]
                        )
                    else:
                        self.script.append((self.now + 0.25, response))
                await super().write(payload)
                self.script.sort(key=lambda item: item[0])

            async def close(self):
                await super().close()
                if scenario == "cleanup_error":
                    raise ValueError(PRIVATE)

        def factory(**kwargs):
            world = SimulatedServer()
            servers.append(world)
            return world.factory(**kwargs)

        async def wait(task, delay):
            return await servers[-1].wait(task, delay)

        async def sleep(seconds):
            await servers[-1].sleep(seconds)

        async def session_spacing(seconds):
            assert seconds == 15
            spacing.append(seconds)

        # Only existing transport/clock test seams change. The real signal
        # wrapper, campaign, session, parsers, timeline and projection execute.
        capture.collect_session.__kwdefaults__.update(
            transport_factory=factory,
            clock=lambda: servers[-1].clock(),
            sleep=sleep,
            waiter=wait,
        )
        capture.run_campaign.__kwdefaults__["sleep"] = session_spacing
        if scenario == "projection_error":
            original_analysis = capture.analyze_capture

            def analyze(*args, **kwargs):
                if servers[-1].mode == "H2":
                    raise TypeError(PRIVATE)
                return original_analysis(*args, **kwargs)

            capture.analyze_capture = analyze
        return probe

    # Patch this entry's dependency loader only after loading its actual code.
    entry.importlib = SimpleNamespace(import_module=install_server)
    assert os.environ["HOBEN_USER_GUID"] == ZERO_IDENTITY
    assert os.environ.get("HOBEN_DEVICE_GUID", ZERO_IDENTITY) == ZERO_IDENTITY
    # Prove the audit hook protects this subprocess too (pytest's fixture does
    # not propagate to children). No resolver/socket is reached by this call.
    try:
        socket.getaddrinfo("offline.invalid", 465)
    except AssertionError:
        pass
    else:
        raise AssertionError("Missing subprocess network guard")
    assert len(network_attempts) == 1
    network_attempts.clear()
    result = entry.main(["live"])
    assert not network_attempts
    assert all(w.connects == 1 and w.closed and w.active_reads == 0 for w in servers)
    assert all(w.maximum_readers <= 1 for w in servers)
    entry.private_json(
        Path(os.environ["RUNNER_TEMP"]) / "simulation-proof.json",
        {
            "network_attempts": len(network_attempts),
            "spacing_seconds": spacing,
            "sessions": [
                {
                    "mode": w.mode,
                    "open_clients": w.opens,
                    "initial_zero_device": w.initial_device,
                    "v4_requests": w.requests,
                    "pongs": w.pongs,
                    "closed": w.closed,
                    "maximum_readers": w.maximum_readers,
                }
                for w in servers
            ],
        },
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve(strict=True), sys.argv[2]))
