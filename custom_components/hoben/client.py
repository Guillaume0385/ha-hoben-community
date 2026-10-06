"""Stateful identity, explicit association and read-only refresh, without HA.

OpenedClient's complete boundary remains unknown. Each refresh therefore opens
and closes its own verified connection; no receive worker or polling task exists.
"""

import asyncio
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from .exceptions import (
    HobenAmbiguousSessionError,
    HobenAuthorizationCodeError,
    HobenAuthorizationRequiredError,
    HobenClientClosedError,
    HobenClosedError,
    HobenInvalidCredentialsError,
    HobenInvalidInputError,
    HobenModbusError,
    HobenProtocolError,
    HobenRefreshExhaustedError,
    HobenTimeoutError,
    HobenTransportError,
    HobenUnsupportedProfileError,
)
from .modbus import ModbusExceptionResponse
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
from .transport import AsyncTlsTransport, TransportError, TransportTimeout
from .v4_read import V4ReadProtocolError, V4ReadTimeout, _read_v4

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
    update it. Every attempt uses a fresh verified myhoben.fr:465 transport.

    Refreshes are serialized, including backoff and identity changes. Default:
    two total attempts with one 1-second async delay, configurable to 1..2 total
    attempts and 0..30 seconds. Only transport failures/timeouts permit retry.
    Explicit association uses the same lock and handshake, with one attempt and
    no Modbus read. No control, permanent socket, background task or polling.
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

    def __repr__(self) -> str:
        """Do not expose either identity or caller-supplied DeviceInfo."""
        return f"HobenClient(profile={self._profile!r}, closed={self._closed})"

    @property
    def device_guid_for_persistence(self) -> str:
        """Sensitive: explicitly retrieve for secure storage, NEVER logs/diagnostics.

        Returns the initial zero value until a supported unambiguous opening.
        A future HA integration may persist this in ConfigEntry storage and pass
        it to a new client. This client never writes files or external storage.
        """
        return self._device_guid

    @property
    def has_assigned_device_guid(self) -> bool:
        """Non-sensitive indication that the current identity differs from zero."""
        return self._device_guid != INITIAL_DEVICE_GUID

    @property
    def profile(self) -> StoveProfile | None:
        """Last successfully accepted profile, even if its following read failed."""
        return self._profile

    @property
    def last_snapshot(self) -> RawStoveSnapshot | None:
        """Last complete successful refresh; failures never replace this snapshot."""
        return self._last_snapshot

    def safe_report(self) -> dict[str, str | bool]:
        """Allowlisted diagnostics; no dataclass/session or generic identity export."""
        return {
            "state": "closed" if self._closed else "ready",
            "profile": self._profile.value if self._profile is not None else "unknown",
            "has_assigned_device_guid": self.has_assigned_device_guid,
        }

    async def async_refresh(self) -> RawStoveSnapshot:
        """Refresh with finite transport retries; always propagate cancellation."""
        async with self._lock:
            if self._closed:
                raise HobenClientClosedError()
            self._active_operation = asyncio.current_task()
            try:
                for attempt in range(1, self._max_attempts + 1):
                    try:
                        snapshot = await self._refresh_once()
                    except HobenTransportError as error:
                        if attempt == self._max_attempts:
                            raise HobenRefreshExhaustedError(attempt, error) from None
                        # _refresh_once has already closed/discarded its transport.
                        # Keep the lock across this yield and retain any new identity.
                        await asyncio.sleep(self._retry_delay)
                    else:
                        self._last_snapshot = snapshot
                        return snapshot
            finally:
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

        Idempotent, including during code input/backoff. Queued/new calls fail with a
        typed closed-client error. The recorded task is the caller's task, not
        a background worker; callers should expect its cancellation on unload.
        """
        self._closed = True
        if self._active_operation is not None:
            self._active_operation.cancel()
        async with self._lock:
            pass

    async def _refresh_once(self) -> RawStoveSnapshot:
        """One raw refresh; observation-only handshake never sends a code."""
        async with self._session_once() as (transport, session):
            response = await _read_v4(transport, read_timeout=self._read_timeout)
            if isinstance(response, ModbusExceptionResponse):
                raise HobenModbusError(response.exception_code)
            opened = session.opened_client
            return RawStoveSnapshot(
                profile=session.profile,
                registers=response.registers,
                product_type=opened.product_type,
                product_revision=opened.product_revision,
                software_major=opened.software_major,
                software_minor=opened.software_minor,
                application_version=opened.application_version,
            )

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
        except (TransportTimeout, SessionTimeout, V4ReadTimeout):
            raise HobenTimeoutError() from None
        except TransportError:
            raise HobenTransportError() from None
        except (SessionProtocolError, V4ReadProtocolError):
            raise HobenProtocolError() from None
        except SessionAuthorizationCodeError:
            raise HobenAuthorizationCodeError() from None
