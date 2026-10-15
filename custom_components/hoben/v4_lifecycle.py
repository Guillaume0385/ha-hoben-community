"""Bounded V4 lifecycle ownership, independent of HA and real stream routing.

Local recovery policy only: a sanitized transport loss can consume one retry.
Protocol/identity failures and application deadlines stop rather than speculate
about server behavior. A quiet RX owner has no application inactivity timer.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from .client import _validate_delay, _validate_device_guid
from .exceptions import (
    HobenClientClosedError,
    HobenError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTransportError,
)
from .modbus import ModbusReadResponse
from .myhoben import INITIAL_DEVICE_GUID, normalize_user_guid
from .v4_session import SessionState, SessionStateError, V4Session


class LifecycleStoppedError(HobenClientClosedError):
    """Explicit shutdown; never eligible for recovery."""

    code = "session_lifecycle_stopped"


class LifecycleExhaustedError(HobenError):
    """The finite lifetime connection budget was consumed."""

    code = "session_lifecycle_exhausted"


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    """Allowlisted counters/state only; no session, identity or error payload."""

    state: SessionState = SessionState.DISCONNECTED
    attempts: int = 0
    max_attempts: int = 1
    failure: str | None = None


class V4Lifecycle:
    """Own fresh V4Session attempts and a finite, non-resetting retry budget.

    connect() waits for the first accepted opening. Recovery then runs until an
    explicit stop, non-retryable failure or budget exhaustion. wait_connected()
    observes recovery; reads always fail back to their original caller, without
    replay. Factories and sleep are injectable for deterministic offline tests.

    retry_delays specifies each allowed recovery wait (one initial attempt plus
    at most eight retries). Positive, finite delays are local policy, not an
    inferred Hoben timing rule. Success never replenishes this lifetime budget.
    The default factory retains V4Session's verified, fixed TLS destination.
    """

    __slots__ = (
        "_user_guid",
        "_device_guid",
        "_factory",
        "_sleep",
        "_delays",
        "_snapshot",
        "_session",
        "_task",
        "_ready",
        "_connected",
        "_failure",
        "_stopping",
    )

    def __init__(
        self,
        *,
        user_guid: str,
        device_guid: str = INITIAL_DEVICE_GUID,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
        session_factory: Callable[..., V4Session] = V4Session,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        # Validate all configuration before any factory can acquire a transport.
        try:
            user_guid = normalize_user_guid(user_guid)
            _validate_device_guid(device_guid)
            if (
                not isinstance(retry_delays, tuple)
                or len(retry_delays) > 8
                or not callable(session_factory)
                or not callable(sleep)
            ):
                raise HobenInvalidInputError()
            for delay in retry_delays:
                _validate_delay(delay)
        except (TypeError, ValueError):
            raise HobenInvalidInputError() from None
        self._user_guid = user_guid
        self._device_guid = device_guid
        self._factory = session_factory
        self._sleep = sleep
        self._delays = retry_delays
        self._snapshot = LifecycleSnapshot(max_attempts=len(retry_delays) + 1)
        self._session: V4Session | None = None
        self._task: asyncio.Task[HobenError] | None = None
        self._ready: asyncio.Future[HobenError | None] | None = None
        self._connected = asyncio.Event()
        self._failure: HobenError | None = None
        self._stopping = False

    def __repr__(self) -> str:
        return f"V4Lifecycle(state={self.state.value})"

    @property
    def state(self) -> SessionState:
        """Return the controller state, not a claim about proven RX framing."""
        return self._snapshot.state

    @property
    def snapshot(self) -> LifecycleSnapshot:
        """Return immutable categorical state and the lifetime attempt count."""
        return self._snapshot

    @property
    def device_guid_for_persistence(self) -> str:
        """Sensitive identity access, never suitable for logs or diagnostics."""
        return self._device_guid

    async def connect(self) -> None:
        """Start once and await the first opening; cancellation stops ownership."""
        if self._stopping:
            raise LifecycleStoppedError()
        if self._task is not None:
            raise SessionStateError()
        self._ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run(), name="hoben-v4-lifecycle")
        try:
            error = await asyncio.shield(self._ready)
        except asyncio.CancelledError:
            await self.close()
            raise
        if error is not None:
            raise error from None

    async def wait_connected(self) -> None:
        """Wait for recovery, or raise its terminal result without cancelling it."""
        if self._stopping:
            raise LifecycleStoppedError()
        if self._task is None:
            raise SessionStateError()
        await self._connected.wait()
        if self.state is not SessionState.CONNECTED:
            raise self._failure or LifecycleStoppedError()

    async def wait_stopped(self) -> None:
        """Observe a typed terminal result; observer cancellation is harmless."""
        if self._task is None:
            raise LifecycleStoppedError()
        try:
            error = await asyncio.shield(self._task)
        except asyncio.CancelledError:
            if (
                self._stopping
                and self._task.cancelled()
                and (not asyncio.current_task().cancelling())
            ):
                raise LifecycleStoppedError() from None
            raise
        if self._stopping:
            raise LifecycleStoppedError()
        raise error from None

    async def request_v4_data(self, *, timeout: float = 30.0) -> ModbusReadResponse:
        """Delegate once to the current session; never retry a caller's read."""
        if self._stopping:
            raise LifecycleStoppedError()
        session = self._session
        if self.state is not SessionState.CONNECTED or session is None:
            raise self._failure or SessionStateError()
        return await session.request_v4_data(timeout=timeout)

    async def _cleanup(self) -> None:
        session = self._session
        if session is not None:
            try:
                await session.abort()
            except asyncio.CancelledError:
                raise  # Keep ownership so explicit close can finish cancellation.
            except Exception:
                self._session = None
                raise
            else:
                self._session = None

    async def _run(self) -> HobenError:
        error: HobenError = LifecycleStoppedError()
        try:
            for attempt in range(1, self.snapshot.max_attempts + 1):
                self._snapshot = replace(
                    self._snapshot,
                    attempts=attempt,
                    state=SessionState.CONNECTING
                    if attempt == 1
                    else SessionState.RECONNECTING,
                )
                opened = False
                try:
                    session = self._factory(
                        user_guid=self._user_guid, device_guid=self._device_guid
                    )
                    if not isinstance(session, V4Session) or (
                        session.state is not SessionState.DISCONNECTED
                    ):
                        raise HobenInvalidInputError()
                    self._session = session
                    await session.connect()
                    opened = True
                    self._device_guid = session.device_guid_for_persistence
                    self._snapshot = replace(
                        self._snapshot, state=SessionState.CONNECTED, failure=None
                    )
                    self._connected.set()
                    if not self._ready.done():
                        self._ready.set_result(None)
                    await session.wait_lost()
                except HobenError as failure:
                    error = failure
                except Exception:
                    error = HobenProtocolError()
                self._connected.clear()
                # Exact classification excludes application deadlines (including
                # read timeouts), protocol ambiguity, auth and Modbus errors.
                retryable = type(error) is HobenTransportError and (
                    not opened or session.loss_is_retryable
                )
                self._snapshot = replace(
                    self._snapshot,
                    failure=error.code,
                    state=SessionState.RECONNECTING
                    if retryable
                    else SessionState.DISCONNECTED,
                )
                try:
                    await self._cleanup()
                except HobenTransportError:
                    pass  # Transport is detached; preserve the primary failure.
                if not retryable:
                    break
                if attempt == self.snapshot.max_attempts:
                    error = LifecycleExhaustedError()
                    break
                await self._sleep(self._delays[attempt - 1])
        except asyncio.CancelledError:
            error = LifecycleStoppedError()
        except Exception:
            error = HobenProtocolError()
        finally:
            try:
                await self._cleanup()
            except Exception:
                pass  # A secondary close error never replaces the primary cause.
            self._failure = error
            self._snapshot = replace(
                self._snapshot,
                failure=error.code,
                state=SessionState.CLOSED
                if self._stopping
                else SessionState.DISCONNECTED,
            )
            self._user_guid = None
            self._device_guid = INITIAL_DEVICE_GUID
            self._connected.set()  # Wake observers on terminal failure too.
            if not self._ready.done():
                self._ready.set_result(error)
        return error

    async def close(self) -> None:
        """Permanently stop opening, TX, cleanup or backoff; never reconnect late."""
        self._stopping = True
        self._snapshot = replace(self._snapshot, state=SessionState.CLOSED)
        task = self._task
        if task is not None:
            if not task.done() and not task.cancelling():
                task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.cancelled():
                    await task
                if asyncio.current_task().cancelling():
                    raise
            finally:
                try:
                    await self._cleanup()
                except HobenTransportError:
                    pass
                self._user_guid = None
                self._device_guid = INITIAL_DEVICE_GUID
                self._failure = LifecycleStoppedError()
                self._snapshot = replace(
                    self._snapshot,
                    state=SessionState.CLOSED,
                    failure=self._failure.code,
                )
                self._connected.set()
                if self._ready is not None and not self._ready.done():
                    self._ready.set_result(self._failure)
        else:
            self._failure = LifecycleStoppedError()
            self._snapshot = replace(self._snapshot, failure=self._failure.code)
            self._connected.set()
            self._user_guid = None
            self._device_guid = INITIAL_DEVICE_GUID
