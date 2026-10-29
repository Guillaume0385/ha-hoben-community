"""Stateful identity, explicit association and read-only refresh, without HA.

Refreshes reuse the shared persistent V4 lifecycle. Scheduling stays with HA;
the shared runtime owns framing, RX/TX, finite recovery and terminal cleanup.
OpenedClient's complete boundary remains unproven on this experimental branch.
"""

import asyncio
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from .exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationCodeError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenClosedError,
    HobenInternalError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenProtocolError,
    HobenRefreshExhaustedError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .myhoben import (
    INITIAL_DEVICE_GUID,
    CloseClientReason,
    encode_open_client,
    normalize_user_guid,
)
from .profiles import StoveProfile
from .session import (
    AuthorizationCodeProvider,
    AuthorizationRequiredResult,
    ClosedSessionResult,
    OpenSessionResult,
    SessionAuthorizationCodeError,
    SessionProtocolError,
    SessionTimeout,
    _open_session,
)
from .session_observation import SessionObservation
from .transport import AsyncTlsTransport, TransportError, TransportTimeout

if TYPE_CHECKING:
    from .v4_lifecycle import V4Lifecycle

# protocol.md §4 confirms the analyzed Android build.
DEFAULT_BUILD = 34
# Keep the documented community descriptor shared with the exploratory probes.
# It is not official MyHOBEN metadata; only its slash-separated shape is known.
DEFAULT_DEVICE_INFO = "ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
_MAX_RETRY_DELAY = 30.0


@dataclass(frozen=True, slots=True)
class AssociationResult:
    """Successful supported opening, without credentials, packet or stove values.

    Success can be an already-authorized opening or follow one DeviceAuthRes.
    Retrieve the assigned identity only via device_guid_for_persistence.
    """

    profile: StoveProfile
    product_type: int
    product_revision: int
    software_major: int
    software_minor: int
    application_version: int

    def safe_report(self) -> dict[str, int | str]:
        """Allowlist public metadata; do not expose the provider or its code."""
        return {
            "state": "associated",
            "profile": self.profile.value,
            "product_type": self.product_type,
            "product_revision": self.product_revision,
            "software_major": self.software_major,
            "software_minor": self.software_minor,
            "application_version": self.application_version,
        }


@dataclass(frozen=True, slots=True)
class RawStoveSnapshot:
    """Raw UInt16 registers and public opening metadata, with no identity/packet.

    Semantic conversion belongs to v4_state.py, not this raw client API. An
    asdict export contains no UserGuid, DeviceGuid or underlying session object,
    but register contents are private household data and must not be logged live.
    """

    profile: StoveProfile
    registers: tuple[int, ...]
    product_type: int
    product_revision: int
    software_major: int
    software_minor: int
    application_version: int

    def safe_report(self) -> dict[str, int | str]:
        """Report public metadata/count only; register values stay in the model."""
        return {
            "state": "read",
            "profile": self.profile.value,
            "product_type": self.product_type,
            "product_revision": self.product_revision,
            "software_major": self.software_major,
            "software_minor": self.software_minor,
            "application_version": self.application_version,
            "register_count": len(self.registers),
        }


def _validate_device_guid(value: str) -> str:
    """The proven constraint is exactly 32 ASCII bytes, not a hex/GUID format."""
    if not isinstance(value, str) or len(value) != 32 or not value.isascii():
        raise HobenInvalidInputError()
    return value


def _validate_delay(value: float, *, allow_zero: bool = False) -> None:
    """Reject implicit coercion and non-finite settings without echoing input."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or (value < 0 if allow_zero else value <= 0)
    ):
        raise HobenInvalidInputError()


class HobenClient:
    """Reusable read-only protocol API; scheduling/storage belongs to the caller.

    Normalize the HOBEN identifier once. Without a persisted DeviceGuid, start
    from INITIAL_DEVICE_GUID. Adopt the returned 32-byte ASCII identity after a
    valid, unambiguous V4 opening, BEFORE reading: a later transport/read failure
    must not discard the assigned identity. Unsupported/ambiguous openings never
    update it. Healthy refreshes share one verified myhoben.fr:465 transport.

    Refreshes are serialized, including backoff and identity changes. Default:
    two lifetime opening attempts with one 1-second async delay, configurable to
    1..2 attempts and 0..30 seconds. Success never resets that finite budget.
    Rejected acquisition/timeout and transport losses close before a bounded
    recovery; failed reads return to their caller without replay. Later refreshes
    can use a recovered generation only after a new correlated response. Terminal
    failure requires an explicit new client/config-entry reload.
    Explicit association uses the same lock and handshake, with one attempt and
    no Modbus read. No control or client-owned polling task.
    """

    def __init__(
        self,
        user_guid: str,
        device_guid: str | None = None,
        *,
        max_attempts: int = 2,
        retry_delay: float = 1.0,
        handshake_timeout: float = 30.0,
        read_timeout: float = 30.0,
        build: int = DEFAULT_BUILD,
        device_info: str = DEFAULT_DEVICE_INFO,
    ) -> None:
        # Validate every field before constructing a transport. Codec validation
        # remains shared with the legacy helpers; its temporary packet is unused.
        try:
            self._user_guid = normalize_user_guid(user_guid)
            self._device_guid = _validate_device_guid(
                INITIAL_DEVICE_GUID if device_guid is None else device_guid
            )
            encode_open_client(self._user_guid, build, self._device_guid, device_info)
        except (TypeError, ValueError):
            raise HobenInvalidInputError() from None
        if (
            not isinstance(max_attempts, int)
            or isinstance(max_attempts, bool)
            or not 1 <= max_attempts <= 2
        ):
            raise HobenInvalidInputError()
        _validate_delay(retry_delay, allow_zero=True)
        if retry_delay > _MAX_RETRY_DELAY:
            raise HobenInvalidInputError()
        _validate_delay(handshake_timeout)
        _validate_delay(read_timeout)
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._handshake_timeout = handshake_timeout
        self._read_timeout = read_timeout
        self._build = build
        self._device_info = device_info
        self._profile: StoveProfile | None = None
        self._last_snapshot: RawStoveSnapshot | None = None
        self._lock = asyncio.Lock()
        self._active_operation: asyncio.Task | None = None
        self._closed = False
        self._lifecycle: V4Lifecycle | None = None

    def __repr__(self) -> str:
        """Do not expose either identity or caller-supplied DeviceInfo."""
        return f"HobenClient(profile={self._profile!r}, closed={self._closed})"

    @property
    def device_guid_for_persistence(self) -> str:
        """Sensitive: explicitly retrieve for secure storage, NEVER logs/diagnostics.

        Returns the initial value until the shared owner accepts a V4 opening.
        HA persists it in ConfigEntry storage and seeds later clients from it.
        This client never writes files or external storage.
        """
        self._adopt_persistent_identity()
        return self._device_guid

    @property
    def has_assigned_device_guid(self) -> bool:
        """Non-sensitive indication that the current identity differs from zero."""
        return self.device_guid_for_persistence != INITIAL_DEVICE_GUID

    @property
    def profile(self) -> StoveProfile | None:
        """Last successfully accepted profile, even if its following read failed."""
        self._adopt_persistent_identity()
        return self._profile

    @property
    def last_snapshot(self) -> RawStoveSnapshot | None:
        """Last complete successful refresh; failures never replace this snapshot."""
        return self._last_snapshot

    @property
    def session_observation(self) -> SessionObservation:
        """Immutable owner evidence; never creates a session or adopts identity."""
        if self._lifecycle is None:
            return SessionObservation(stopped=self._closed)
        return self._lifecycle.session_observation

    def safe_report(self) -> dict[str, str | bool | int]:
        """Allowlisted diagnostics; no dataclass/session or generic identity export."""
        self._adopt_persistent_identity()
        report = {
            "state": "closed" if self._closed else "ready",
            "profile": self._profile.value if self._profile is not None else "unknown",
            "has_assigned_device_guid": self.has_assigned_device_guid,
        }
        if self._lifecycle is not None:
            subcode = self._lifecycle.snapshot.close_client_subcode
            if subcode is not None:
                report["close_client_subcode"] = subcode
        return report

    def _adopt_persistent_identity(self) -> None:
        """Cache only the shared owner's accepted identity, including on failure."""
        if self._lifecycle is not None:
            assigned = self._lifecycle.accepted_device_guid_for_persistence
            if assigned is not None:
                self._device_guid = assigned
                self._profile = StoveProfile.V4

    async def async_refresh(self) -> RawStoveSnapshot:
        """Read once on the shared lifecycle; never reset it or replay a read."""
        async with self._lock:
            if self._closed:
                raise HobenClientClosedError()
            self._active_operation = asyncio.current_task()
            try:
                snapshot = await self._refresh_once()
                self._last_snapshot = snapshot
                return snapshot
            except asyncio.CancelledError:
                self._adopt_persistent_identity()
                if self._lifecycle is not None:
                    await self._lifecycle.close()
                raise
            finally:
                self._adopt_persistent_identity()
                self._active_operation = None

    async def async_associate(
        self,
        *,
        authorization_code_provider: AuthorizationCodeProvider | None = None,
    ) -> AssociationResult:
        """Open once, optionally submit a caller's code, adopt identity, then close.

        Await the provider only on DeviceAuthReq, at most once. It must be
        nonblocking and return an int representable as UInt16, never a bool.
        No provider means authorization-required, as for the existing refresh.
        An already-authorized client succeeds without consulting the provider.

        The existing handshake_timeout includes provider waiting; it is a local
        budget, not server expiration semantics. No automatic retry/resubmission
        occurs, even on transport failure. The caller decides any later attempt.
        No Modbus request is sent and last_snapshot is not changed. The provider
        and code are not stored on this client or in the returned public model.
        """
        async with self._lock:
            if self._closed:
                raise HobenClientClosedError()
            if authorization_code_provider is not None and not callable(
                authorization_code_provider
            ):
                raise HobenInvalidInputError()
            self._active_operation = asyncio.current_task()
            try:
                # Explicit association retains its existing one-shot contract.
                # Stop any earlier persistent owner first, without rearming its
                # finite budget; config-flow already uses a fresh client here.
                if self._lifecycle is not None:
                    self._adopt_persistent_identity()
                    await self._lifecycle.close()
                async with self._session_once(
                    authorization_code_provider=authorization_code_provider
                ) as (_, session):
                    opened = session.opened_client
                    return AssociationResult(
                        profile=session.profile,
                        product_type=opened.product_type,
                        product_revision=opened.product_revision,
                        software_major=opened.software_major,
                        software_minor=opened.software_minor,
                        application_version=opened.application_version,
                    )
            finally:
                self._active_operation = None

    async def async_close(self) -> None:
        """Permanently close, cancel an active operation, and await TLS cleanup.

        Idempotent, including during code input/backoff. Queued/new calls fail
        with a typed closed-client error. Cancel the active caller, then stop
        all shared background ownership; unload awaits both cleanup paths.
        """
        self._closed = True
        self._adopt_persistent_identity()
        if self._active_operation is not None:
            self._active_operation.cancel()
        async with self._lock:
            if self._lifecycle is not None:
                self._adopt_persistent_identity()
                await self._lifecycle.close()

    async def _refresh_once(self) -> RawStoveSnapshot:
        """Adapt only public shared APIs; no framing or recovery policy here."""
        # The shared modules use this module's frozen identity/options helpers.
        # Import after module initialization rather than introducing a cycle.
        from .v4_lifecycle import (
            LifecycleExhaustedError,
            LifecycleStoppedError,
            V4Lifecycle,
        )
        from .v4_session import (
            SessionStateError,
            V4OpeningOptions,
            V4Session,
            V4SessionMode,
        )

        try:
            if self._lifecycle is None:
                self._lifecycle = V4Lifecycle(
                    user_guid=self._user_guid,
                    device_guid=self._device_guid,
                    mode=V4SessionMode.PERSISTENT,
                    opening_options=V4OpeningOptions(
                        build=self._build,
                        device_info=self._device_info,
                        handshake_timeout=self._handshake_timeout,
                    ),
                    retry_delays=(self._retry_delay,) * (self._max_attempts - 1),
                    session_factory=partial(
                        V4Session, transport_factory=AsyncTlsTransport
                    ),
                    sleep=asyncio.sleep,
                    recover_acquisition=True,
                )
                await self._lifecycle.connect()
            else:
                await self._lifecycle.wait_connected()
            self._adopt_persistent_identity()
            before = self._lifecycle.witness
            response = await self._lifecycle.request_v4_data(timeout=self._read_timeout)
            after = self._lifecycle.witness
            opened = self._lifecycle.opening_metadata
            if (
                opened is None
                or after.verified_read_generation != before.established_generation
                or after.established_generation != before.established_generation
                or after.verified_read_sequence is None
                or after.verified_read_sequence <= (before.verified_read_sequence or 0)
            ):
                self._adopt_persistent_identity()
                await self._lifecycle.close()
                raise HobenInternalError()
            return RawStoveSnapshot(
                profile=StoveProfile.V4,
                registers=response.registers,
                product_type=opened.product_type,
                product_revision=opened.product_revision,
                software_major=opened.software_major,
                software_minor=opened.software_minor,
                application_version=opened.application_version,
            )
        except LifecycleExhaustedError as error:
            raise HobenRefreshExhaustedError(
                self._lifecycle.snapshot.attempts,
                error.last_error or HobenTransportError(),
            ) from None
        except LifecycleStoppedError:
            raise HobenClientClosedError() from None
        except SessionStateError:
            # A loss between wait_connected and request registration is still a
            # failed refresh. Do not retry it or claim a recovered snapshot.
            raise HobenTransportError() from None

    @asynccontextmanager
    async def _session_once(
        self,
        *,
        authorization_code_provider: AuthorizationCodeProvider | None = None,
    ) -> AsyncIterator[tuple[AsyncTlsTransport, OpenSessionResult]]:
        """Share checked opening, identity adoption, cleanup and sanitized failures."""
        transport = AsyncTlsTransport()
        failed = True
        try:
            try:
                session = await _open_session(
                    transport,
                    user_guid=self._user_guid,
                    device_guid=self._device_guid,
                    build=self._build,
                    device_info=self._device_info,
                    handshake_timeout=self._handshake_timeout,
                    authorization_code_provider=authorization_code_provider,
                )
                if isinstance(session, AuthorizationRequiredResult):
                    raise HobenAuthorizationRequiredError()
                if isinstance(session, ClosedSessionResult):
                    if session.reason is CloseClientReason.INVALID_IDENTIFIER:
                        raise HobenInvalidCredentialsError(session.reason)
                    raise HobenClosedError(session.reason)
                if session.unclassified_bytes:
                    raise HobenAmbiguousSessionError()
                if session.profile is not StoveProfile.V4:
                    raise HobenUnsupportedProfileError(session.profile)
                opened = session.opened_client
                try:
                    assigned = _validate_device_guid(opened.device_guid)
                except HobenInvalidInputError:
                    raise HobenProtocolError() from None
                self._device_guid = assigned
                self._profile = session.profile
                yield transport, session
                failed = False
            finally:
                try:
                    await transport.close()
                except TransportError:
                    # Never mask a protocol/authentication error with shutdown
                    # failure and thereby accidentally make it retryable.
                    if not failed:
                        raise
        except (TransportTimeout, SessionTimeout):
            raise HobenTimeoutError() from None
        except TransportError:
            raise HobenTransportError() from None
        except SessionProtocolError:
            raise HobenProtocolError() from None
        except SessionAuthorizationCodeError:
            raise HobenAuthorizationCodeError() from None
