"""One verified session and one documented V4 read, with no register semantics."""

import asyncio
import math
from dataclasses import dataclass

from .modbus import (
    HOBEN_UNIT_ID,
    READ_INPUT_REGISTERS,
    ModbusExceptionResponse,
    ModbusReadResponse,
    build_read_input_registers,
    decode_read_response,
    modbus_tcp_frame_size,
)
from .myhoben import (
    DATA_RESPONSE_CLIENT,
    decode_data_response_client,
    encode_data_request_client,
)
from .profiles import StoveProfile
from .session import (
    AuthorizationRequiredResult,
    ClosedSessionResult,
    OpenSessionResult,
    UnexpectedMessageType,
    _open_session,
)
from .transport import AsyncTlsTransport, TransportEOF, TransportError

# protocol.md §7: the only application request allowed by this operation.
_TRANSACTION_ID = 0xFFFF
_START_ADDRESS = 1024
_QUANTITY = 20
_PING = 0x0A
_PONG = b"\x0b"
_READ_SIZE = 4096
_MBAP_PREFIX_SIZE = 6


class V4ReadProtocolError(Exception):
    """A malformed, ambiguous or uncorrelated read response; no payload data."""


class V4ReadTimeout(TimeoutError):
    """The sole read exchange exceeded its total deadline, including Ping time."""


@dataclass(frozen=True)
class V4ReadBlockedResult:
    """OpenedClient observed, but its profile/boundary forbids an application read."""

    session: OpenSessionResult

    def safe_report(self) -> dict[str, int | str]:
        """Expose only the sanitized session metadata and an allowlisted reason."""
        return self.session.safe_report() | {
            "state": "read_not_attempted",
            "error": (
                "unclassified_opened_client_bytes"
                if self.session.unclassified_bytes
                else "unsupported_profile"
            ),
        }


@dataclass(frozen=True)
class V4ReadResult:
    """One correlated read or exception, with its opening evidence.

    The session retains the server's DeviceGuid with repr redaction. Export only
    safe_report() and session.safe_report(), never dataclasses.asdict().
    """

    response: ModbusReadResponse | ModbusExceptionResponse
    session: OpenSessionResult

    def safe_report(self) -> dict[str, int | str | list[int]]:
        """Return raw UInt16 values or the raw numeric Modbus exception code."""
        report: dict[str, int | str | list[int]] = {
            "profile": StoveProfile.V4.value,
            "function": READ_INPUT_REGISTERS,
            "start_address": _START_ADDRESS,
            "quantity": _QUANTITY,
        }
        if isinstance(self.response, ModbusExceptionResponse):
            report.update(
                state="modbus_exception", exception_code=self.response.exception_code
            )
        else:
            report.update(state="read", registers=list(self.response.registers))
        return report


V4Result = (
    V4ReadResult
    | V4ReadBlockedResult
    | AuthorizationRequiredResult
    | ClosedSessionResult
)


async def _receive_v4_response(
    transport: AsyncTlsTransport,
) -> ModbusReadResponse | ModbusExceptionResponse:
    """Buffer one 0x0E envelope, using MBAP only once its six-byte prefix exists.

    Leading standalone Ping is the only additional message allowed. Reject any
    suffix already buffered after the response, without parsing or answering it.
    Never read again after the first complete response, even for another reply.
    """
    buffer = bytearray()
    while True:
        if buffer:
            if buffer[0] == _PING:
                del buffer[0]
                await transport.write(_PONG)
                continue
            if buffer[0] != DATA_RESPONSE_CLIENT:
                raise UnexpectedMessageType(buffer[0])
            if len(buffer) >= 1 + _MBAP_PREFIX_SIZE:
                try:
                    size = 1 + modbus_tcp_frame_size(
                        bytes(buffer[1 : 1 + _MBAP_PREFIX_SIZE])
                    )
                except ValueError:
                    raise V4ReadProtocolError("Invalid response MBAP prefix") from None
                if len(buffer) > size:
                    raise V4ReadProtocolError("Unexpected trailing response bytes")
                if len(buffer) == size:
                    try:
                        response = decode_read_response(
                            decode_data_response_client(bytes(buffer))
                        )
                    except ValueError:
                        raise V4ReadProtocolError("Invalid V4 read response") from None
                    if (
                        response.transaction_id != _TRANSACTION_ID
                        or response.unit_id != HOBEN_UNIT_ID
                        or response.function_code != READ_INPUT_REGISTERS
                    ):
                        raise V4ReadProtocolError("Uncorrelated V4 read response")
                    if isinstance(response, ModbusReadResponse) and (
                        len(response.registers) != _QUANTITY
                    ):
                        raise V4ReadProtocolError(
                            "V4 read requires exactly 20 registers"
                        )
                    return response
        # Yield even with a buffered stream, so endless Ping cannot defeat the
        # overall exchange deadline or cancellation. No polling/retry is added.
        await asyncio.sleep(0)
        try:
            buffer.extend(await transport.read(_READ_SIZE))
        except TransportEOF:
            if buffer:
                raise V4ReadProtocolError("Truncated DataResponseClient") from None
            raise


async def open_and_read_v4_once(
    transport: AsyncTlsTransport,
    *,
    user_guid: str,
    build: int,
    device_guid: str,
    device_info: str,
    handshake_timeout: float = 30.0,
    read_timeout: float = 30.0,
) -> V4Result:
    """Own connect → OpenClient → V4 gate → one read → one response → close.

    Reuse the shared session/codec rules; never persist the returned DeviceGuid.
    Authorization/closure observations stop immediately. Only an OpenedClient
    with dynamically selected V4 and no already-read unclassified suffix permits
    the fixed function 04 request (FFFF, unit 1, address 1024, quantity 20).
    The total OpenedClient length remains unresolved: this limited gate does not
    prove that an undocumented suffix could never arrive in a later TLS read.
    No request customization, pairing, writes, polling or reconnect exists here.
    Per-operation transport timeouts and separate finite handshake/read deadlines
    apply. Always close, including invalid input, timeout, error and cancellation.
    """
    failed = True
    try:
        if (
            not isinstance(read_timeout, (int, float))
            or isinstance(read_timeout, bool)
            or not math.isfinite(read_timeout)
            or read_timeout <= 0
        ):
            raise ValueError("read_timeout must be positive finite seconds")
        session = await _open_session(
            transport,
            user_guid=user_guid,
            build=build,
            device_guid=device_guid,
            device_info=device_info,
            handshake_timeout=handshake_timeout,
        )
        if not isinstance(session, OpenSessionResult):
            result = session
        elif session.profile is not StoveProfile.V4 or session.unclassified_bytes:
            result = V4ReadBlockedResult(session)
        else:
            request = encode_data_request_client(
                build_read_input_registers(
                    _TRANSACTION_ID, _START_ADDRESS, _QUANTITY, unit_id=HOBEN_UNIT_ID
                )
            )
            try:
                async with asyncio.timeout(read_timeout):
                    await transport.write(request)
                    result = V4ReadResult(
                        await _receive_v4_response(transport), session
                    )
            except TransportError:
                raise
            except TimeoutError:
                raise V4ReadTimeout("V4 read exchange timed out") from None
        failed = False
        return result
    finally:
        try:
            await transport.close()
        except TransportError:
            if not failed:
                raise
