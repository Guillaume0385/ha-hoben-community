"""Stateful read-only identity over bounded TLS sessions, without HA imports.

OpenedClient's complete boundary remains unknown. Each refresh therefore opens
and closes its own verified connection; no receive worker or polling task exists.
"""

import asyncio
import math
from dataclasses import dataclass

from .exceptions import (
    HobenAmbiguousSessionError,
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
    AuthorizationRequiredResult,
    ClosedSessionResult,
    SessionProtocolError,
    SessionTimeout,
    _open_session,
)
from .transport import AsyncTlsTransport, TransportError, TransportTimeout
from .v4_read import V4ReadProtocolError, V4ReadTimeout, _read_v4

_DEFAULT_BUILD = 34
_DEFAULT_DEVICE_INFO = "ha-hoben-community/HobenClient/en/Python/Linux/0/0/1/0/0,0"
_MAX_RETRY_DELAY = 30.0


@dataclass(frozen=True, slots=True)
class RawStoveSnapshot:
    """Raw UInt16 registers and public opening metadata, with no identity/packet.

    No physical interpretation of V4 registers is established. This immutable
    model can be passed directly to a future DataUpdateCoordinator; even an
    asdict export contains no UserGuid, DeviceGuid or underlying session object.
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
    No pairing, command, permanent socket, background task or polling is exposed.
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
        build: int = _DEFAULT_BUILD,
        device_info: str = _DEFAULT_DEVICE_INFO,
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
        self._active_refresh: asyncio.Task | None = None
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
            self._active_refresh = asyncio.current_task()
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
                self._active_refresh = None

    async def async_close(self) -> None:
        """Permanently close, cancel an active refresh, and await its transport cleanup.

        Idempotent, including during backoff. Queued/new refreshes fail with a
        typed closed-client error. The recorded task is the caller's task, not
        a background worker; callers should expect its cancellation on unload.
        """
        self._closed = True
        if self._active_refresh is not None:
            self._active_refresh.cancel()
        async with self._lock:
            pass

    async def _refresh_once(self) -> RawStoveSnapshot:
        """Own one fresh connection; sanitize primitives without retrying protocol."""
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
                response = await _read_v4(transport, read_timeout=self._read_timeout)
                if isinstance(response, ModbusExceptionResponse):
                    raise HobenModbusError(response.exception_code)
                snapshot = RawStoveSnapshot(
                    profile=session.profile,
                    registers=response.registers,
                    product_type=opened.product_type,
                    product_revision=opened.product_revision,
                    software_major=opened.software_major,
                    software_minor=opened.software_minor,
                    application_version=opened.application_version,
                )
                failed = False
                return snapshot
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
