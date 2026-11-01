"""Process-local test instrumentation; never imported by the HA integration.

The campaign's isolated worker owns exactly one fresh client. Only that client's
session factory is decorated, while the original lifecycle/session algorithms
remain in charge. No packet is parsed, forged, replayed or retained here.
"""

import asyncio
import logging
from contextlib import contextmanager
from functools import partial

from custom_components.hoben import v4_lifecycle
from custom_components.hoben.exceptions import (
    HobenClientClosedError,
    HobenClosedError,
    HobenInternalError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTlsVerificationError,
    HobenTransportError,
)
from custom_components.hoben.transport import (
    TransportEOF,
    TransportError,
    TransportTlsError,
)
from custom_components.hoben.v4_experiment import ExperimentalCloseClientError
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import V4Session, V4SessionMode
from scripts.campaign_runtime_contract import need

_installed = False
_LOGGER = logging.getLogger(__name__)


def category(error):
    """Types only: never consult exception text, payloads or chains."""
    for kinds, name in (
        ((TransportEOF,), "eof"),
        ((TimeoutError, HobenTimeoutError), "timeout"),
        ((TransportTlsError, HobenTlsVerificationError), "tls"),
        ((TransportError, HobenTransportError), "transport"),
        ((ExperimentalCloseClientError,), "close_client"),
        ((HobenClientClosedError, HobenClosedError), "closed"),
        ((asyncio.CancelledError,), "cancelled"),
        ((HobenInternalError,), "internal"),
        ((HobenProtocolError,), "protocol"),
    ):
        if isinstance(error, kinds):
            return name
    return "internal"


class PongInjection:
    """Constant-space counters; the supplied clock enforces the original bound."""

    def __init__(self, clock, deadline):
        self.clock, self.deadline = clock, deadline
        self.policy = NoPongAfter120(clock=clock)
        self.attempts = self.recovery_pongs = 0
        self.reopened_at = None
        self.enabled = False
        self.tearing_down = False
        self.diagnostic = dict(interruption=None, cleanup=None)

    def note(self, slot, error, owner, generation, subcode=None):
        if self.diagnostic[slot] is not None:
            return
        self.diagnostic[slot] = dict(
            category=category(error),
            owner=owner,
            generation=generation,
            inhibition_exercised=self.policy.suppressed > 0,
            subcode=subcode,
        )
        _LOGGER.warning(
            "HA reconnect test %s category=%s owner=%s generation=%s "
            "inhibition_exercised=%s subcode=%s",
            slot,
            *self.diagnostic[slot].values(),
        )

    def interrupted(self, error, owner, generation, subcode=None):
        if (
            self.enabled
            and not self.tearing_down
            and (
                generation != self.policy.first_generation
                or self.policy.first_loss_after_suppression_at is None
            )
        ):
            self.note("interruption", error, owner, generation, subcode)

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
                # A raced retry cannot silently replace an unexercised first
                # generation while the observer is awaiting a true refresh.
                if probe.diagnostic["interruption"] is not None:
                    raise HobenClientClosedError()
                await self.transport.connect()

            async def read(self, max_bytes=4096, *, bounded=True):
                try:
                    data = await self.transport.read(max_bytes, bounded=bounded)
                    if data == b"":
                        probe.policy.peer_closed(self.generation)
                        probe.interrupted(
                            TransportEOF(), "transport_read", self.generation
                        )
                    return data
                except Exception as error:
                    if probe.enabled and isinstance(error, TransportEOF):
                        probe.policy.peer_closed(self.generation)
                    probe.interrupted(error, "transport_read", self.generation)
                    raise

            async def write(self, data):
                need(probe.enabled and probe.clock() < probe.deadline)
                if data == b"\x0b":
                    if probe.policy.suppress(self.generation):
                        need(probe.policy.suppressed <= 1048576)
                        return
                    await self.send(data)
                    # Opening itself can answer Ping. Only an already accepted
                    # replacement session can attest a post-recovery keepalive.
                    if (
                        probe.reopened_at is not None
                        and self.generation != probe.policy.first_generation
                    ):
                        probe.recovery_pongs += 1
                        need(probe.recovery_pongs <= 1048576)
                else:
                    await self.send(data)

            async def send(self, data):
                try:
                    await self.transport.write(data)
                except Exception as error:
                    probe.interrupted(error, "transport_write", self.generation)
                    raise

            async def close(self):
                # Cleanup is never treated as a peer loss or prohibited by time.
                try:
                    await self.transport.close()
                except (Exception, asyncio.CancelledError) as error:
                    probe.note("cleanup", error, "transport_close", self.generation)
                    raise

        class Session(V4Session):
            def __init__(self, *, transport_factory, **options):
                need(probe.enabled and probe.clock() < probe.deadline)
                if probe.diagnostic["interruption"] is not None:
                    raise HobenClientClosedError()
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
                try:
                    await super().connect()
                except Exception as error:
                    probe.interrupted(error, "opening", self.test_generation)
                    raise
                # Strict acceptance, no await before stamp.
                probe.policy.accepted(self.test_generation)
                if self.test_generation != probe.policy.first_generation:
                    probe.reopened_at = probe.clock()

            async def wait_lost(self):
                try:
                    return await super().wait_lost()
                except Exception as error:
                    # Only the actual shared owner recognizes a complete close.
                    if probe.enabled and self.close_client_received:
                        probe.policy.client_closed(self.test_generation)
                    probe.interrupted(
                        error,
                        "session",
                        self.test_generation,
                        self.snapshot.close_client_subcode
                        if self.close_client_received
                        else None,
                    )
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
