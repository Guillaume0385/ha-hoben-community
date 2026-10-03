"""One-shot OpenClient handshake; no polling, pairing or persistent session."""

import asyncio
import math
from dataclasses import dataclass

from .myhoben import (
    OPENED_CLIENT,
    OpenedClient,
    decode_opened_client,
    encode_open_client,
)
from .profiles import StoveProfile, select_stove_profile
from .transport import AsyncTlsTransport, TransportError

_PING = 0x0A
_PONG = b"\x0b"
# Confirmed fields end at offset 47. This is NOT a complete-message length.
_OPENED_CLIENT_PREFIX_SIZE = 48
_READ_SIZE = 4096


class SessionProtocolError(Exception):
    """A malformed or unsupported handshake response, without payload data."""


class UnexpectedMessageType(SessionProtocolError):
    """Only the numeric type is retained; its payload boundary is unknown."""

    def __init__(self, message_type: int) -> None:
        self.message_type = message_type
        super().__init__(f"Unexpected MyHOBEN message type: {message_type}")


class SessionTimeout(TimeoutError):
    """The overall OpenClient/OpenedClient exchange exceeded its deadline."""


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
            "message_type": OPENED_CLIENT,
            "product_type": opened.product_type,
            "product_revision": opened.product_revision,
            "software_major": opened.software_major,
            "software_minor": opened.software_minor,
            "application_version": opened.application_version,
            "profile": self.profile.value,
            "unclassified_bytes": self.unclassified_bytes,
        }


async def _receive_opened_client(transport: AsyncTlsTransport) -> OpenSessionResult:
    """Accumulate a small prefix buffer and answer only standalone leading Ping."""
    buffer = bytearray()
    while True:
        if buffer:
            message_type = buffer[0]
            if message_type == _PING:
                del buffer[0]
                await transport.write(_PONG)
                continue
            if message_type != OPENED_CLIENT:
                raise UnexpectedMessageType(message_type)
            if len(buffer) >= _OPENED_CLIENT_PREFIX_SIZE:
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
        buffer.extend(await transport.read(_READ_SIZE))


async def open_session_once(
    transport: AsyncTlsTransport,
    *,
    user_guid: str,
    build: int,
    device_guid: str,
    device_info: str,
    handshake_timeout: float = 30.0,
) -> OpenSessionResult:
    """Own connect → one OpenClient → confirmed OpenedClient prefix → close.

    Supply all codec inputs unchanged; no identifier is generated or normalized.
    UNKNOWN is a successful profile selection. Per-operation transport timeouts
    apply alongside a finite total exchange deadline (after TLS connection).
    This connection cannot be reused as a session: the response's full length
    remains unknown. Close on success, invalid input, EOF, error and cancellation.
    """
    failed = True
    try:
        if (
            not isinstance(handshake_timeout, (int, float))
            or isinstance(handshake_timeout, bool)
            or not math.isfinite(handshake_timeout)
            or handshake_timeout <= 0
        ):
            raise ValueError("handshake_timeout must be positive finite seconds")
        try:
            request = encode_open_client(user_guid, build, device_guid, device_info)
        except (TypeError, ValueError):
            raise ValueError("Invalid OpenClient fields") from None
        await transport.connect()
        try:
            async with asyncio.timeout(handshake_timeout):
                await transport.write(request)
                result = await _receive_opened_client(transport)
        except TransportError:
            # Preserve the operation-specific timeout/EOF instead of relabeling it.
            raise
        except TimeoutError:
            raise SessionTimeout("OpenClient handshake timed out") from None
        failed = False
        return result
    finally:
        try:
            await transport.close()
        except TransportError:
            # A secondary shutdown failure must not hide the original outcome.
            if not failed:
                raise
