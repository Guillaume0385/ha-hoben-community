"""Bounded shared OpenClient/optional DeviceAuth handshake, without polling."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .myhoben import (
    CLOSE_CLIENT,
    DEVICE_AUTH_REQ,
    OPENED_CLIENT,
    CloseClientReason,
    OpenedClient,
    decode_close_client,
    decode_opened_client,
    encode_device_auth_response,
    encode_open_client,
)
from .profiles import StoveProfile, select_stove_profile
from .transport import AsyncTlsTransport, TransportEOF, TransportError

_PING = 0x0A
_PONG = b"\x0b"
# Confirmed fields end at offset 47. This is NOT a complete-message length.
_OPENED_CLIENT_PREFIX_SIZE = 48
_READ_SIZE = 4096

# A caller may await user input without coupling this layer to Home Assistant.
# Never retain/log the provider or its sensitive result in a public model.
AuthorizationCodeProvider = Callable[[], Awaitable[int]]


class SessionAuthorizationCodeError(Exception):
    """The local provider failed or returned a value not representable as UInt16."""


class SessionProtocolError(Exception):
    """A malformed or unsupported handshake response, without payload data."""


class UnexpectedMessageType(SessionProtocolError):
    """Only the numeric type is retained; its payload boundary is unknown."""

    def __init__(self, message_type: int) -> None:
        self.message_type = message_type
        super().__init__(f"Unexpected MyHOBEN message type: {message_type}")


class SessionTimeout(TimeoutError):
    """The overall handshake, including optional code input, exceeded its deadline."""


@dataclass(frozen=True)
class OpenSessionResult:
    """Parsed response and profile; use safe_report() for shareable diagnostics.

    opened_client retains the codec's DeviceGuid for callers, with repr redaction.
    Do not export it with dataclasses.asdict() or log its identifier explicitly.
    unclassified_bytes counts only the suffix already read, not all server data.
    """

    opened_client: OpenedClient
    profile: StoveProfile
    unclassified_bytes: int = 0

    def safe_report(self) -> dict[str, int | str]:
        """Explicitly allowlist diagnostic fields, excluding all identifiers."""
        opened = self.opened_client
        return {
            "state": "opened",
            "message_type": OPENED_CLIENT,
            "product_type": opened.product_type,
            "product_revision": opened.product_revision,
            "software_major": opened.software_major,
            "software_minor": opened.software_minor,
            "application_version": opened.application_version,
            "profile": self.profile.value,
            "unclassified_bytes": self.unclassified_bytes,
        }


@dataclass(frozen=True)
class AuthorizationRequiredResult:
    """OpenClient reached an authorization request; no code is requested/sent."""

    def safe_report(self) -> dict[str, int | str]:
        """Report only the known type and its documented meaning."""
        return {"state": "authorization_required", "message_type": DEVICE_AUTH_REQ}


@dataclass(frozen=True)
class ClosedSessionResult:
    """Server closure with an allowlisted reason, without any raw payload."""

    reason: CloseClientReason

    def safe_report(self) -> dict[str, int | str]:
        """Unknown/missing subcodes stay unknown; no numeric payload is exported."""
        return {
            "state": "closed",
            "message_type": CLOSE_CLIENT,
            "reason": self.reason.value,
        }


SessionResult = OpenSessionResult | AuthorizationRequiredResult | ClosedSessionResult


async def _receive_response(
    transport: AsyncTlsTransport,
    *,
    authorization_code_provider: AuthorizationCodeProvider | None = None,
) -> SessionResult:
    """Keep one buffer through association; answer only standalone leading Ping.

    protocol.md §5 establishes DeviceAuthReq as a one-byte marker for this
    interoperability path. Consume it without dropping coalesced bytes; the
    existing OpenedClient prefix/suffix policy still applies after a response.
    One explicit code submission is allowed, with no resend or callback loop.
    Without a provider, preserve the observation-only authorization result.
    """
    buffer = bytearray()
    authorization_sent = False
    while True:
        if buffer:
            message_type = buffer[0]
            if message_type == _PING:
                del buffer[0]
                await transport.write(_PONG)
                continue
            if message_type == DEVICE_AUTH_REQ:
                if authorization_code_provider is None:
                    return AuthorizationRequiredResult()
                if authorization_sent:
                    raise SessionProtocolError("Repeated DeviceAuthReq")
                del buffer[0]
                try:
                    code = await authorization_code_provider()
                    response = encode_device_auth_response(code)
                    del code
                except Exception:
                    # Callback exceptions may themselves contain secrets. Keep
                    # cancellation (BaseException) and the overall timeout intact.
                    raise SessionAuthorizationCodeError(
                        "Authorization code unavailable"
                    ) from None
                await transport.write(response)
                del response
                authorization_sent = True
                continue
            if message_type == CLOSE_CLIENT and len(buffer) >= 2:
                return ClosedSessionResult(decode_close_client(bytes(buffer[:2])))
            if message_type not in (OPENED_CLIENT, CLOSE_CLIENT):
                raise UnexpectedMessageType(message_type)
            if (
                message_type == OPENED_CLIENT
                and len(buffer) >= _OPENED_CLIENT_PREFIX_SIZE
            ):
                try:
                    opened = decode_opened_client(
                        bytes(buffer[:_OPENED_CLIENT_PREFIX_SIZE])
                    )
                except ValueError:
                    raise SessionProtocolError("Invalid OpenedClient prefix") from None
                # Never reframe the suffix, even if it looks like another Ping.
                return OpenSessionResult(
                    opened,
                    select_stove_profile(opened),
                    len(buffer) - _OPENED_CLIENT_PREFIX_SIZE,
                )
        # Yield even if streams already have buffered data, allowing the overall
        # deadline/cancellation to fire during an uninterrupted stream of Ping.
        await asyncio.sleep(0)
        try:
            buffer.extend(await transport.read(_READ_SIZE))
        except TransportEOF:
            if buffer == bytes([CLOSE_CLIENT]):
                return ClosedSessionResult(decode_close_client(bytes(buffer)))
            raise


async def _open_session(
    transport: AsyncTlsTransport,
    *,
    user_guid: str,
    build: int,
    device_guid: str,
    device_info: str,
    handshake_timeout: float = 30.0,
    authorization_code_provider: AuthorizationCodeProvider | None = None,
) -> SessionResult:
    """Shared handshake primitive; the one-shot caller must always close.

    This internal helper exposes no persistent client. A provider is invoked
    only after DeviceAuthReq, inside the existing finite handshake deadline.
    That is a local operation budget, not an inferred server code lifetime.
    Callers still enforce profile/boundary checks and own transport cleanup.
    """
    if (
        not isinstance(handshake_timeout, (int, float))
        or isinstance(handshake_timeout, bool)
        or not math.isfinite(handshake_timeout)
        or handshake_timeout <= 0
    ):
        raise ValueError("handshake_timeout must be positive finite seconds")
    if authorization_code_provider is not None and not callable(
        authorization_code_provider
    ):
        raise ValueError("Authorization code provider must be callable")
    try:
        request = encode_open_client(user_guid, build, device_guid, device_info)
    except (TypeError, ValueError):
        raise ValueError("Invalid OpenClient fields") from None
    await transport.connect()
    try:
        async with asyncio.timeout(handshake_timeout):
            await transport.write(request)
            return await _receive_response(
                transport, authorization_code_provider=authorization_code_provider
            )
    except TransportError:
        # Preserve the operation-specific timeout/EOF instead of relabeling it.
        raise
    except TimeoutError:
        raise SessionTimeout("OpenClient handshake timed out") from None


async def open_session_once(
    transport: AsyncTlsTransport,
    *,
    user_guid: str,
    build: int,
    device_guid: str,
    device_info: str,
    handshake_timeout: float = 30.0,
) -> SessionResult:
    """Own connect → one OpenClient → first non-Ping response → close.

    The shared codec validates/normalizes UserGuid. Other inputs are caller-owned.
    Authorization requests and server closures are observations, not successful
    authentication. Never send DeviceAuthRes or process trailing opaque payloads.
    UNKNOWN is a successful profile selection. Per-operation transport timeouts
    apply alongside a finite total exchange deadline (after TLS connection).
    This connection cannot be reused as a session: the response's full length
    remains unknown. Close on success, invalid input, EOF, error and cancellation.
    """
    failed = True
    try:
        result = await _open_session(
            transport,
            user_guid=user_guid,
            build=build,
            device_guid=device_guid,
            device_info=device_info,
            handshake_timeout=handshake_timeout,
        )
        failed = False
        return result
    finally:
        try:
            await transport.close()
        except TransportError:
            # A secondary shutdown failure must not hide the original outcome.
            if not failed:
                raise
