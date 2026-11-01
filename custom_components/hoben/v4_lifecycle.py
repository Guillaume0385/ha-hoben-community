"""Shared V4 lifecycle ownership, independent of HA and real stream routing.

Local recovery policy only: a sanitized transport loss or complete experimental
post-open CloseClient can consume one retry under the same finite budget.
By default protocol/identity failures and application deadlines stop. The HA
adapter can opt in to recovering exact acquisition/timeout failures after full
cleanup. A separate explicit HA policy waits 60 seconds after confirmed cleanup
and permits unlimited attempts; campaign/quarantine budgets remain finite.
These are local availability policies, not server-behavior claims.
A quiet RX owner has no application inactivity timer.
"""

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from itertools import count

from .client import _validate_delay, _validate_device_guid
from .error_phases import phase_of, with_phase
from .exceptions import (
    HobenCleanupError,
    HobenClientClosedError,
    HobenClosedError,
    HobenError,
    HobenInternalError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
)
from .modbus import ModbusReadResponse
from .myhoben import INITIAL_DEVICE_GUID, CloseClientReason, normalize_user_guid
from .session_monitor import SessionEvent, error_event, notify_status
from .session_observation import SessionLossKind, SessionObservation
from .v4_eof_quarantine import STABLE_FOR_MS, Event, RecoveryTiming
from .v4_experiment import ExperimentalCloseClientError
from .v4_session import (
    OpeningMetadata,
    SessionState,
    SessionStateError,
    V4OpeningOptions,
    V4Session,
    V4SessionMode,
    _QuarantineCapability,
)

_LOGGER = logging.getLogger(__name__)
HA_RECONNECT_SECONDS = 60.0


class LifecycleStoppedError(HobenClientClosedError):
    """Explicit shutdown; never eligible for recovery."""

    code = "session_lifecycle_stopped"


class LifecycleExhaustedError(HobenError):
    """The finite lifetime connection budget was consumed."""

    code = "session_lifecycle_exhausted"

    def __init__(self, last_error: HobenError | None = None) -> None:
        self.last_error = last_error
        super().__init__()


class _LifecycleQuarantineCapability:
    """Private, one-use second-scenario binding; no current consumer provides it.

    The session capability validates exact owners, one common injected clock and
    bounded integer deadlines before any I/O. L3 timing is bound to the first
    actual strict acceptance, never to a caller-supplied acceptance timestamp.
    """

    __slots__ = ("_initial", "_claimed", "_timing", "_origin", "_permit", "_recovered")

    def __init__(self, budget, no_pong, **deadlines):
        self._initial = _QuarantineCapability(budget, no_pong, **deadlines)
        self._claimed = False
        self._timing = self._origin = self._permit = None
        self._recovered = False

    def __repr__(self):
        return "_LifecycleQuarantineCapability()"


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    """Allowlisted counters/state only; no session, identity or error payload."""

    state: SessionState = SessionState.DISCONNECTED
    attempts: int = 0
    max_attempts: int | None = 1
    failure: str | None = None
    close_client_subcode: int | None = None


@dataclass(frozen=True, slots=True)
class LifecycleWitness:
    """Opaque local evidence only; no identity, frames, or household readings."""

    established_generation: int | None = None
    lost_generation: int | None = None
    loss_monotonic_ms: int | None = None
    verified_read_generation: int | None = None
    verified_read_sequence: int | None = None


class V4Lifecycle:
    """Own fresh sessions, with a finite default and an explicit HA retry policy.

    connect() waits for the first accepted opening. Recovery then runs until an
    explicit stop, non-retryable failure or budget exhaustion. wait_connected()
    observes recovery; reads always fail back to their original caller, without
    replay. Factories and sleep are injectable for deterministic offline tests.

    retry_delays specifies each allowed recovery wait (one initial attempt plus
    at most eight retries). Positive, finite delays are local policy, not an
    inferred Hoben timing rule. Success never replenishes this lifetime budget.
    The default factory retains V4Session's verified, fixed TLS destination.
    recover_acquisition is an explicit persistent-adapter policy. It never
    changes the default campaign/quarantine policy, framing or attempt budget.
    ha_reconnect additionally selects unlimited attempts with a fixed >=60 s
    delay, including recoverable opening failures. It requires persistent mode
    and recovery opt-in; it cannot be combined with experimental capabilities.
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
        "_quarantine",
        "_clock",
        "_witness",
        "_generation",
        "_mode",
        "_opening_options",
        "_opening_metadata",
        "_accepted_device_guid",
        "_observation",
        "_active_generation",
        "_recover_acquisition",
        "_ha_reconnect",
        "_status_callback",
    )

    def __init__(
        self,
        *,
        user_guid: str,
        device_guid: str = INITIAL_DEVICE_GUID,
        mode: V4SessionMode = V4SessionMode.CONSERVATIVE,
        opening_options: V4OpeningOptions | None = None,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
        session_factory: Callable[..., V4Session] = V4Session,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        recover_acquisition: bool = False,
        ha_reconnect: bool = False,
        _status_callback=None,
        _quarantine: _LifecycleQuarantineCapability | None = None,
    ) -> None:
        # Validate all configuration before any factory can acquire a transport.
        try:
            user_guid = normalize_user_guid(user_guid)
            _validate_device_guid(device_guid)
            if type(mode) is not V4SessionMode or (
                opening_options is not None
                and type(opening_options) is not V4OpeningOptions
            ):
                raise HobenInvalidInputError()
            if type(recover_acquisition) is not bool or (
                recover_acquisition and mode is not V4SessionMode.PERSISTENT
            ):
                raise HobenInvalidInputError()
            if type(ha_reconnect) is not bool or (
                ha_reconnect
                and (mode is not V4SessionMode.PERSISTENT or not recover_acquisition)
            ):
                raise HobenInvalidInputError()
            if _status_callback is not None and not callable(_status_callback):
                raise HobenInvalidInputError()
            if (
                not isinstance(retry_delays, tuple)
                or len(retry_delays) > 8
                or not callable(session_factory)
                or not callable(sleep)
                or not callable(clock)
            ):
                raise HobenInvalidInputError()
            for delay in retry_delays:
                _validate_delay(delay, allow_zero=mode is V4SessionMode.PERSISTENT)
                if mode is V4SessionMode.PERSISTENT and delay > 30:
                    raise HobenInvalidInputError()
        except (TypeError, ValueError):
            raise HobenInvalidInputError() from None
        if _quarantine is not None:
            if (
                type(_quarantine) is not _LifecycleQuarantineCapability
                or _quarantine._claimed
                or len(retry_delays) > 2
                or mode is V4SessionMode.PERSISTENT
            ):
                raise HobenInvalidInputError()
            _quarantine._claimed = True
        self._quarantine = _quarantine
        self._mode, self._opening_options = mode, opening_options
        self._recover_acquisition = recover_acquisition
        self._ha_reconnect = ha_reconnect
        self._status_callback = _status_callback
        self._opening_metadata: OpeningMetadata | None = None
        self._accepted_device_guid: str | None = None
        self._clock = clock
        self._witness = LifecycleWitness()
        self._generation = 0
        self._observation = SessionObservation()
        self._active_generation: int | None = None
        self._user_guid = user_guid
        self._device_guid = device_guid
        self._factory = session_factory
        self._sleep = sleep
        self._delays = retry_delays
        self._snapshot = LifecycleSnapshot(
            max_attempts=None if ha_reconnect else len(retry_delays) + 1
        )
        self._session: V4Session | None = None
        self._task: asyncio.Task[HobenError] | None = None
        self._ready: asyncio.Future[HobenError | None] | None = None
        self._connected = asyncio.Event()
        self._failure: HobenError | None = None
        self._stopping = False

    def __repr__(self) -> str:
        return f"V4Lifecycle(state={self.state.value})"

    @property
    def ha_recovery_pending(self) -> bool:
        """A setup caller may await this same owner; never recreate its budget."""
        return bool(
            self._ha_reconnect
            and not self._stopping
            and self._task is not None
            and not self._task.done()
        )

    def _log_attempt(
        self, attempt: int, result: str, error: HobenError | None = None
    ) -> None:
        """Fixed categories only, even if an injected exception has arbitrary text."""
        if not self._ha_reconnect:
            return
        categories = {
            HobenTransportError: "transport_unavailable",
            HobenTimeoutError: "timeout",
            HobenProtocolError: "malformed_response",
            HobenClosedError: "server_closed",
            ExperimentalCloseClientError: "server_closed",
        }
        category = (
            "initial"
            if error is None
            else categories.get(type(error), "permanent_error")
        )
        phase = error_event(error).phase if error is not None else None
        _LOGGER.info(
            "Hoben HA connection attempt=%d accepted_generation=%d "
            "category=%s result=%s phase=%s",
            attempt,
            self._generation,
            category,
            result,
            phase or "unknown",
        )
        if result == "failed" and type(error) is HobenProtocolError:
            report = error.diagnostic.safe_report()
            _LOGGER.warning(
                "Hoben malformed_response [%s]",
                ", ".join(f"{key}={value}" for key, value in report.items()),
            )

    @property
    def state(self) -> SessionState:
        """Return the controller state, not a claim about proven RX framing."""
        if (
            self._quarantine is not None
            and self._session is not None
            and self._snapshot.state is SessionState.CONNECTED
            and self._session.state is not SessionState.CONNECTED
        ):
            return self._session.state
        return self._snapshot.state

    @property
    def snapshot(self) -> LifecycleSnapshot:
        """Return immutable categorical state and the lifetime attempt count."""
        return (
            replace(self._snapshot, state=self.state)
            if self._quarantine
            else self._snapshot
        )

    @property
    def witness(self) -> LifecycleWitness:
        """Latest immutable owner-origin evidence, never a polling inference."""
        return self._witness

    @property
    def session_observation(self) -> SessionObservation:
        """Project safe owner evidence without I/O, mutation or identity access."""
        witness = self._witness
        return replace(
            self._observation,
            attempts=self._snapshot.attempts,
            generation=witness.established_generation,
            read_generation=witness.verified_read_generation,
            read_sequence=witness.verified_read_sequence,
            active=(
                not self._stopping
                and self._failure is None
                and self._session is not None
                and self._session.state is SessionState.CONNECTED
                and self._task is not None
                and not self._task.done()
            ),
            stopped=(
                self._stopping
                and self._session is None
                and (self._task is None or self._task.done())
            ),
        )

    def _note_natural_loss(self, session: V4Session, error: HobenError) -> None:
        """Record a witnessed loss before cleanup, never a local close/timeout."""
        if (
            self._stopping
            or self._quarantine is not None
            or session is not self._session
            or self._witness.established_generation is None
            or type(error) is not HobenTransportError
            or not session.loss_is_retryable
        ):
            return
        at_ms = session.loss_monotonic_ms
        if at_ms is None:
            return
        self._observation = replace(
            self._observation,
            loss_generation=self._witness.established_generation,
            loss_kind=SessionLossKind.TRANSPORT,
            close_client_subcode=None,
        )
        self._witness = replace(
            self._witness,
            lost_generation=self._witness.established_generation,
            loss_monotonic_ms=at_ms,
        )

    @property
    def device_guid_for_persistence(self) -> str:
        """Sensitive identity access, never suitable for logs or diagnostics."""
        return self._device_guid

    @property
    def opening_metadata(self) -> OpeningMetadata | None:
        """Last accepted V4 metadata, retained across loss; never credentials."""
        return self._opening_metadata

    @property
    def accepted_device_guid_for_persistence(self) -> str | None:
        """Sensitive: retrieve before explicit close, NEVER log or export.

        The accepted identity survives terminal read/reconnect failure so an
        adapter can persist it even when no snapshot was returned. Explicit
        close erases it. A failed/unsupported opening never updates this cache.
        """
        return self._accepted_device_guid

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

    @property
    def data_updated_transport_alive(self):
        return (
            self.state is SessionState.CONNECTED
            and self._session is not None
            and self._session.state is SessionState.CONNECTED
        )

    @property
    def data_updated_recovering(self):
        """Same-session acquisition recovery, independent of reconnect policy."""
        return (
            self.state is SessionState.CONNECTED
            and self._session is not None
            and self._session.data_updated_recovering
        )

    async def wait_connected(self) -> None:
        """Wait for recovery, or raise its terminal result without cancelling it."""
        if self._stopping:
            raise LifecycleStoppedError()
        if self._task is None:
            raise SessionStateError()
        while True:
            await self._connected.wait()
            if (
                self._ha_reconnect
                and self.state is SessionState.CONNECTED
                and self._session is not None
                and self._session.state is not SessionState.CONNECTED
            ):
                # RX can publish loss before this owner resumes. A setup retry
                # must await the owner, not repeatedly reuse the stale event.
                self._connected.clear()
                continue
            if self.state is SessionState.CONNECTED:
                return
            if not self._quarantine or self._task.done() or self._stopping:
                raise self._failure or LifecycleStoppedError()
            # A session can suspend synchronously before the owner task wakes.
            # Clearing and rechecking involves no await and cannot lose a later
            # recovery/terminal notification. This is not a polling loop.
            self._connected.clear()

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
        response = await session.request_v4_data(timeout=timeout)
        # The checked owner and immutable generation must still match. A later
        # session, an invalid result or a cancelled caller never claims a read.
        if (
            self._stopping
            or session is not self._session
            or self.state is not SessionState.CONNECTED
            or session.verified_read_sequence <= 0
        ):
            return response
        self._witness = replace(
            self._witness,
            verified_read_generation=self._witness.established_generation,
            verified_read_sequence=session.verified_read_sequence,
        )
        return response

    async def _cleanup(self, *, _quarantine_permit=None) -> None:
        session = self._session
        if session is not None:
            try:
                if _quarantine_permit is not None:
                    await session._cleanup_quarantine(self, _quarantine_permit)
                else:
                    await session.abort()
            except asyncio.CancelledError:
                raise  # Keep ownership so explicit close can finish cancellation.
            except Exception as failure:
                self._observation = replace(self._observation, cleanup_failed=True)
                self._session = None
                raise with_phase(failure, "cleanup")
            else:
                if session.cleanup_succeeded:
                    if self._active_generation is not None:
                        self._observation = replace(
                            self._observation,
                            cleaned_generation=self._active_generation,
                        )
                else:
                    self._observation = replace(self._observation, cleanup_failed=True)
                self._session = None
            finally:
                if self._session is None:
                    self._active_generation = None

    def _private_session(self, attempt):
        cap = self._quarantine
        kwargs = {"user_guid": self._user_guid, "device_guid": self._device_guid}
        # Omit new options for existing injected factories and campaign paths.
        if self._mode is V4SessionMode.PERSISTENT:
            kwargs["mode"] = self._mode
        if self._ha_reconnect:
            kwargs["recover_data_updated"] = True
        if self._opening_options is not None:
            kwargs["opening_options"] = self._opening_options
        if cap is not None:
            kwargs.update(
                session_300=cap._initial._budget,
                no_pong_after_120=cap._initial._no_pong,
            )
            if attempt == 1:
                kwargs["_quarantine"] = cap._initial
        session = self._factory(**kwargs)
        if (
            not isinstance(session, V4Session)
            or session.state is not SessionState.DISCONNECTED
            or (
                self._mode is V4SessionMode.PERSISTENT
                and session.mode is not V4SessionMode.PERSISTENT
            )
        ):
            raise HobenInvalidInputError()
        session._status_callback = self._status_callback
        if session._framer is not None:
            session._framer.frame_log.generation = attempt
        if cap is not None:
            if (
                type(session) is not V4Session
                or session._experiment is not cap._initial._budget
                or session._no_pong is not cap._initial._no_pong
                or session._experiment.opens != attempt - 1
                or session._transport is not None
                or session._rx_task is not None
            ):
                raise HobenInvalidInputError()
            session._framer._reject_close_client = True
            if attempt == 1:
                session._bind_quarantine_owner(self)
                cap._origin = session
            else:
                session._limit_recovery_acceptance(
                    min(
                        cap._timing.recovery_deadline_ms,
                        cap._timing.functional_deadline_ms - STABLE_FOR_MS,
                    )
                )
        session._loss_clock = self._clock
        return session

    def _check_private_recovery(self, *, delay_ms=0, accepted_session=None):
        cap = self._quarantine
        if (
            self._stopping
            or asyncio.current_task().cancelling()
            or cap._timing is None
            or cap._origin is None
            or not cap._origin._quarantine_permit_valid(self, cap._permit)
        ):
            raise HobenProtocolError()
        now = cap._origin._quarantine_checked_at
        timing = cap._timing
        if (
            now + delay_ms >= timing.recovery_deadline_ms
            or now + delay_ms + STABLE_FOR_MS >= timing.functional_deadline_ms
        ):
            raise HobenProtocolError()
        if accepted_session is not None:
            accepted = V4Session._quarantine_time(
                accepted_session._experiment.accepted_at
            )
            if (
                accepted is None
                or accepted <= cap._origin._quarantine_observation.at_ms
                or accepted >= timing.recovery_deadline_ms
                or accepted + STABLE_FOR_MS >= timing.functional_deadline_ms
                or accepted_session.state is not SessionState.CONNECTED
                or not accepted_session._experiment.usable
            ):
                raise HobenProtocolError()
        return (
            min(
                timing.recovery_deadline_ms,
                timing.functional_deadline_ms - STABLE_FOR_MS,
            )
            - now
        ) / 1000

    async def _claim_private_recovery(self, session):
        cap = self._quarantine
        if cap._recovered:
            return False  # A second accepted generation's loss is terminal.
        if cap._permit is None:
            if session is not cap._origin:
                return False
            # Let queued explicit stops/cancellations win before consumption.
            await asyncio.sleep(0)
            if self._stopping or asyncio.current_task().cancelling():
                return False
            cap._permit = session._consume_quarantine(self, 1)
        self._check_private_recovery()
        return True

    async def _wait_private_loss(self, session):
        cap = self._quarantine
        now = session._quarantine_now()
        deadline = (
            cap._timing.functional_deadline_ms
            if cap._recovered
            else min(
                cap._timing.recovery_deadline_ms,
                cap._timing.functional_deadline_ms - STABLE_FOR_MS,
            )
        )
        if now is None or now >= deadline:
            raise HobenProtocolError()
        # This private lifecycle cannot outlive the fixed functional envelope,
        # even without a collector. Expiry makes no claim of stable success.
        async with asyncio.timeout((deadline - now) / 1000):
            await session._wait_unavailable()
            if session.state is SessionState.QUARANTINED:
                self._snapshot = replace(self._snapshot, state=SessionState.QUARANTINED)
                self._connected.clear()
            await session.wait_lost()

    async def _run(self) -> HobenError:
        error: HobenError = LifecycleStoppedError()
        try:
            attempts = (
                count(1)
                if self._ha_reconnect
                else range(1, self.snapshot.max_attempts + 1)
            )
            for attempt in attempts:
                if self._stopping or asyncio.current_task().cancelling():
                    raise LifecycleStoppedError()
                self._log_attempt(attempt, "started", None if attempt == 1 else error)
                self._snapshot = replace(
                    self._snapshot,
                    attempts=attempt,
                    state=SessionState.CONNECTING
                    if attempt == 1
                    else SessionState.RECONNECTING,
                )
                notify_status(self._status_callback)
                opened = False
                session = None
                try:
                    if self._quarantine is not None and attempt > 1:
                        await asyncio.sleep(0)
                        self._check_private_recovery()
                    session = self._private_session(attempt)
                    self._session = session
                    if self._quarantine is not None and attempt > 1:
                        async with asyncio.timeout(self._check_private_recovery()):
                            await session.connect()
                    else:
                        await session.connect()
                    opened = True
                    if self._quarantine is not None:
                        if attempt > 1:
                            # Strict acceptance consumes the sole stable phase,
                            # even if RX fails before it can be published usable.
                            self._quarantine._recovered = True
                        if attempt == 1:
                            cap = self._quarantine
                            observation, process, suite = cap._initial._deadlines
                            cap._timing = RecoveryTiming(
                                accepted_generation=session._experiment_generation,
                                accepted_at_ms=V4Session._quarantine_time(
                                    session._experiment.accepted_at
                                ),
                                observation_deadline_ms=observation,
                                process_deadline_ms=process,
                                suite_deadline_ms=suite,
                            )
                        await asyncio.sleep(0)
                        if self._stopping or asyncio.current_task().cancelling():
                            raise LifecycleStoppedError()
                        if attempt > 1:
                            self._check_private_recovery(accepted_session=session)
                    self._device_guid = session.device_guid_for_persistence
                    self._accepted_device_guid = self._device_guid
                    self._opening_metadata = session.snapshot.opening
                    self._generation += 1
                    self._active_generation = self._generation
                    self._witness = replace(
                        self._witness,
                        established_generation=self._generation,
                        verified_read_generation=None,
                        verified_read_sequence=None,
                    )
                    self._snapshot = replace(
                        self._snapshot, state=SessionState.CONNECTED, failure=None
                    )
                    self._failure = None
                    notify_status(
                        self._status_callback,
                        SessionEvent("accepted", generation=self._generation),
                    )
                    self._log_attempt(attempt, "connected")
                    self._connected.set()
                    if not self._ready.done():
                        self._ready.set_result(None)
                    if self._quarantine is None:
                        await session.wait_lost()
                    else:
                        await self._wait_private_loss(session)
                except HobenError as failure:
                    error = failure
                except Exception as failure:
                    error = with_phase(
                        HobenInternalError(), phase_of(failure) or "unknown"
                    )
                self._failure = error
                notify_status(self._status_callback, error_event(error))
                self._log_attempt(attempt, "failed", error)
                self._connected.clear()
                if opened:
                    self._note_natural_loss(session, error)
                    if (
                        not self._stopping
                        and self._quarantine is None
                        and type(error) is ExperimentalCloseClientError
                        and session.close_client_received
                    ):
                        self._observation = replace(
                            self._observation,
                            loss_generation=self._witness.established_generation,
                            loss_kind=SessionLossKind.CLOSE_CLIENT,
                            close_client_subcode=session.snapshot.close_client_subcode,
                        )
                # Exact classification excludes application deadlines (including
                # read timeouts), protocol ambiguity, auth and Modbus errors.
                retryable = type(error) is HobenTransportError and (
                    not opened or session.loss_is_retryable
                )
                # Only a complete post-open experimental CloseClient may also
                # consume this same finite retry budget. Never replay a read or
                # record this local terminal transition as a natural TLS EOF.
                retryable = retryable or (
                    type(error) is ExperimentalCloseClientError
                    and opened
                    and session.close_client_received
                )
                if self._recover_acquisition and opened:
                    # HA opts in to discarding the entire rejected session,
                    # not its unknown bytes. No read is replayed. The same
                    # finite lifetime attempts, delay and cleanup gate apply.
                    retryable = retryable or type(error) in (
                        HobenProtocolError,
                        HobenTimeoutError,
                    )
                    if type(error) is ExperimentalCloseClientError:
                        retryable = error.reason not in (
                            CloseClientReason.INVALID_IDENTIFIER,
                            CloseClientReason.AUTHORIZATION_REJECTED,
                            CloseClientReason.AUTHORIZATION_TIMEOUT,
                        )
                if self._ha_reconnect and not opened:
                    retryable = retryable or type(error) in (
                        HobenTimeoutError,
                        HobenProtocolError,
                    )
                    retryable = retryable or (
                        type(error) is HobenClosedError
                        and error.reason is CloseClientReason.SERVER_MAINTENANCE
                    )
                permit = None
                if self._quarantine is not None:
                    retryable = False
                    try:
                        if opened or (
                            type(error) is HobenTransportError
                            and self._quarantine._permit is not None
                        ):
                            retryable = await self._claim_private_recovery(session)
                            if session is self._quarantine._origin:
                                permit = self._quarantine._permit
                    except HobenError:
                        pass  # No admissible, current, unconsumed origin proof.
                self._snapshot = replace(
                    self._snapshot,
                    failure=error.code,
                    close_client_subcode=(
                        session.snapshot.close_client_subcode
                        if session is not None
                        and session.snapshot.close_client_subcode is not None
                        else self._snapshot.close_client_subcode
                    ),
                    state=SessionState.RECONNECTING
                    if retryable
                    else SessionState.DISCONNECTED,
                )
                notify_status(self._status_callback)
                try:
                    if permit is not None:
                        async with asyncio.timeout(self._check_private_recovery()):
                            await self._cleanup(_quarantine_permit=permit)
                    else:
                        await self._cleanup()
                except HobenTransportError:
                    if self._quarantine is not None:
                        raise  # A private recovery requires successful cleanup.
                    pass  # Transport is detached; preserve the primary failure.
                if type(error) is ExperimentalCloseClientError:
                    retryable = retryable and session.close_client_cleanup_succeeded
                if self._mode is V4SessionMode.PERSISTENT and session is not None:
                    # Production never reopens after an unconfirmed cleanup,
                    # including a close error already caught by the RX owner.
                    retryable = retryable and session.cleanup_succeeded
                    if self._ha_reconnect and not session.cleanup_succeeded:
                        error = with_phase(HobenCleanupError(), "cleanup")
                if not retryable:
                    break
                if not self._ha_reconnect and attempt == self.snapshot.max_attempts:
                    error = LifecycleExhaustedError(error)
                    break
                if opened and type(error) in (HobenProtocolError, HobenTimeoutError):
                    observed = error_event(error)
                    notify_status(
                        self._status_callback,
                        SessionEvent("recovery", observed.category, observed.phase),
                    )
                if self._quarantine is not None:
                    self._check_private_recovery(
                        delay_ms=math.ceil(self._delays[attempt - 1] * 1000)
                    )
                if self._quarantine is not None:
                    async with asyncio.timeout(self._check_private_recovery()):
                        await self._sleep(self._delays[attempt - 1])
                else:
                    await self._sleep(
                        HA_RECONNECT_SECONDS
                        if self._ha_reconnect
                        else self._delays[attempt - 1]
                    )
                if self._quarantine is not None:
                    self._check_private_recovery()
        except asyncio.CancelledError:
            error = LifecycleStoppedError()
        except Exception as failure:
            error = with_phase(HobenInternalError(), phase_of(failure) or "unknown")
        finally:
            if self._quarantine is not None and self._quarantine._origin is not None:
                self._quarantine._origin._quarantine_stop(Event.CANCEL)
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
            if not self._stopping:
                notify_status(self._status_callback, error_event(error))
            notify_status(self._status_callback, SessionEvent("ended"))
            self._connected.set()  # Wake observers on terminal failure too.
            if not self._ready.done():
                self._ready.set_result(error)
        return error

    async def close(self) -> None:
        """Permanently stop opening, TX, cleanup or backoff; never reconnect late."""
        self._stopping = True
        if self._quarantine is not None and self._quarantine._origin is not None:
            self._quarantine._origin._quarantine_stop(Event.CANCEL)
        self._snapshot = replace(self._snapshot, state=SessionState.CLOSED)
        notify_status(self._status_callback, SessionEvent("ended"))
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
                self._accepted_device_guid = None
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
            self._accepted_device_guid = None
