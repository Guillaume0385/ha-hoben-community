"""Process-local test instrumentation; never imported by the HA integration.

The campaign's isolated worker owns exactly one fresh client. Only that client's
session factory is decorated, while the original lifecycle/session algorithms
remain in charge. No packet is parsed, forged, replayed or retained here.
"""

import asyncio
from contextlib import contextmanager
from functools import partial

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_experiment import ExperimentalCloseClientError
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import V4Session, V4SessionMode
from scripts.campaign_runtime_contract import need

_installed = False


class PongInjection:
    """Constant-space counters; the supplied clock enforces the original bound."""

    def __init__(self, clock, deadline):
        self.clock, self.deadline = clock, deadline
        self.policy = NoPongAfter120(clock=clock)
        self.attempts = self.recovery_pongs = 0
        self.reopened_at = None
        self.enabled = False

    def __repr__(self):
        return "PongInjection()"

    @contextmanager
    def install(self, client):
        """Decorate one fresh client's factory, restore it even on cancellation.

        HobenClient has no session-injection API. Its constructor is unchanged;
        the isolated worker temporarily binds its lazy lifecycle factory. The
        binding rejects any second/different client and any production HA retry
        policy. The real lifecycle still enforces its two-opening lifetime cap.
        """
        global _installed
        need(
            client._lifecycle is None
            and not self.enabled
            and not _installed
            and client.ha_reconnect_enabled is False
        )
        original = v4_lifecycle.V4Lifecycle
        probe = self

        class Transport:
            def __init__(self, transport, generation):
                self.transport, self.generation = transport, generation

            async def connect(self):
                need(probe.enabled and probe.clock() < probe.deadline)
                await self.transport.connect()

            async def read(self, max_bytes=4096, *, bounded=True):
                try:
                    return await self.transport.read(max_bytes, bounded=bounded)
                except TransportEOF:
                    if probe.enabled:
                        probe.policy.peer_closed(self.generation)
                    raise

            async def write(self, data):
                need(probe.enabled and probe.clock() < probe.deadline)
                if data == b"\x0b":
                    if probe.policy.suppress(self.generation):
                        need(probe.policy.suppressed <= 1048576)
                        return
                    await self.transport.write(data)
                    # Opening itself can answer Ping. Only an already accepted
                    # replacement session can attest a post-recovery keepalive.
                    if (
                        probe.reopened_at is not None
                        and self.generation != probe.policy.first_generation
                    ):
                        probe.recovery_pongs += 1
                        need(probe.recovery_pongs <= 1048576)
                else:
                    await self.transport.write(data)

            async def close(self):
                # Cleanup is never treated as a peer loss or prohibited by time.
                await self.transport.close()

        class Session(V4Session):
            def __init__(self, *, transport_factory, **options):
                need(probe.enabled and probe.clock() < probe.deadline)
                probe.attempts += 1
                need(probe.attempts <= 2)
                self.test_generation = probe.attempts
                super().__init__(
                    transport_factory=lambda: Transport(
                        transport_factory(), self.test_generation
                    ),
                    **options,
                )

            async def connect(self):
                await super().connect()  # strict acceptance, no await before stamp
                probe.policy.accepted(self.test_generation)
                if self.test_generation != probe.policy.first_generation:
                    probe.reopened_at = probe.clock()

            async def wait_lost(self):
                try:
                    return await super().wait_lost()
                except ExperimentalCloseClientError:
                    # Only the actual shared owner recognizes a complete close.
                    if probe.enabled and self.close_client_received:
                        probe.policy.client_closed(self.test_generation)
                    raise

        def factory(**options):
            need(
                self.enabled
                and client._lifecycle is None
                and client._active_operation is asyncio.current_task()
                and options.get("mode") is V4SessionMode.PERSISTENT
                and options.get("ha_reconnect") is False
            )
            supplied = options["session_factory"]
            need(
                type(supplied) is partial
                and supplied.func is V4Session
                and not supplied.args
                and set(supplied.keywords) == {"transport_factory"}
            )
            options["session_factory"] = partial(Session, **supplied.keywords)
            return original(**options)

        self.enabled = _installed = True
        v4_lifecycle.V4Lifecycle = factory
        try:
            yield self
        finally:
            self.enabled = _installed = False
            v4_lifecycle.V4Lifecycle = original
