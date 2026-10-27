"""C1 fixture-only collector: actual HA coordinator/client, injected offline I/O.

Not a script or live entry point. The HA test harness prohibits sockets and
constructs a fresh isolated coordinator; no client/HA instance is created here.
C2 admission, secret loading and process/resource supervision do not exist here.
"""

import asyncio
from collections.abc import Awaitable, Callable

from custom_components.hoben.client import HobenClient
from custom_components.hoben.coordinator import (
    HobenCoordinatorData,
    HobenDataUpdateCoordinator,
)
from custom_components.hoben.session_observation import SessionObservation
from scripts.ha_session_proof import (
    LIMITS,
    REFRESH_AT_MS,
    build_report,
    project_observation,
)


class OfflineHaSessionCollector:
    """Observe public evidence only; cancel propagates after owned cleanup.

    Call only with the socket-blocked HA fixtures. clock/sleep are required so
    tests advance the fixed schedule deterministically, without waiting 300 s.
    No retry, induced loss, association, raw decode or private owner access.
    """

    def __init__(
        self,
        coordinator: HobenDataUpdateCoordinator,
        *,
        provenance: dict,
        clock: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        if (
            type(coordinator) is not HobenDataUpdateCoordinator
            or type(coordinator.client) is not HobenClient
            or coordinator.client.session_observation != SessionObservation()
            or coordinator.data is not None
        ):
            raise ValueError("fresh offline HA fixture required")
        self.coordinator = coordinator
        self.provenance = provenance
        self.clock, self.sleep = clock, sleep
        self.report = None

    async def collect(self):
        """Six fixed refresh slots, absolute useful deadline, bounded cleanup.

        Two connects (10 s), handshakes (30 s), transport closes (5 s),
        six reads (30 s) and one 1 s retry require at most 271 s of I/O.
        The absolute 300 s cutoff wins over a late slot's
        recovery; it never extends the window to manufacture a successful read.
        The future 360 s external supervisor includes cleanup and kill/reaping.
        """
        samples, completed, closed = [], False, False
        start = self.clock()
        client = self.coordinator.client
        try:
            async with asyncio.timeout(LIMITS["useful_ms"] / 1000):
                for ordinal, at_ms in enumerate(REFRESH_AT_MS, 1):
                    await self.sleep(max(0, start + at_ms / 1000 - self.clock()))
                    if self.clock() - start >= LIMITS["useful_ms"] / 1000:
                        raise TimeoutError
                    previous = self.coordinator.data
                    try:
                        await self.coordinator.async_refresh()
                    finally:
                        samples.append(
                            {
                                "ordinal": ordinal,
                                "decoded": (
                                    self.coordinator.last_update_success
                                    and type(self.coordinator.data)
                                    is HobenCoordinatorData
                                    and self.coordinator.data is not previous
                                ),
                                "observation": project_observation(
                                    client.session_observation
                                ),
                            }
                        )
                    if self.clock() - start >= LIMITS["useful_ms"] / 1000:
                        raise TimeoutError
                completed = True
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # Only categorical failure, never arbitrary exception text.
        finally:
            # This measures the useful window, not cleanup or process lifetime.
            elapsed_ms = min(LIMITS["useful_ms"], int((self.clock() - start) * 1000))
            try:
                async with asyncio.timeout(LIMITS["cleanup_ms"] / 1000):
                    await client.async_close()
                closed = True
            except Exception:
                pass
            finally:
                self.report = build_report(
                    provenance=self.provenance,
                    samples=samples,
                    cleanup={
                        "completed": closed,
                        "observation": project_observation(client.session_observation),
                    },
                    elapsed_ms=elapsed_ms,
                    completed=completed,
                )
        return self.report
