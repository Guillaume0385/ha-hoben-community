"""Pure #219-A analysis of ONE read delivery, never a stream framer.

The five-byte envelope is documented in protocol.md §2. MBAP/PDU checks below
are internal Modbus consistency checks (§6), not message/TLS boundary evidence.
Values stay private and unmapped; no address, physical unit or snapshot is inferred.
"""

from dataclasses import dataclass, field

from .modbus import ModbusExceptionResponse, ModbusReadResponse, decode_read_response

_STATUSES = {"parsed", "malformed", "unsupported", "incomplete", "ambiguous"}
_REASONS = {
    "ok",
    "read_exception",
    "missing_type",
    "wrong_type",
    "missing_metadata",
    "missing_mbap",
    "invalid_protocol",
    "invalid_length",
    "body_missing",
    "delivery_suffix",
    "missing_byte_count",
    "invalid_byte_count",
    "values_missing",
    "values_extra",
    "unsupported_function",
    "exception_size",
    "oversized_delivery",
    "not_read_start",
    "recovery_discarded",
    "parser_failure",
}
_NUMBERS = {
    "delivery_bytes": 4096,
    "metadata_bytes": 4,
    "mbap_bytes": 7,
    "pdu_bytes": 4084,
    "declared_mbap_length": 65535,
    "declared_value_bytes": 255,
    "observed_value_bytes": 4082,
    "value_count": 125,
}
_FLAGS = {
    "transaction_present",
    "protocol_present",
    "mbap_length_present",
    "discriminator_valid",
    "metadata_complete",
    "mbap_complete",
    "protocol_valid",
    "length_consistent",
    "unit_present",
    "function_present",
    "byte_count_present",
}
_FUNCTIONS = {"absent", "read_holding", "read_input", "read_exception", "unsupported"}


def _empty_report(size):
    return {
        **dict.fromkeys(_NUMBERS),
        **dict.fromkeys(_FLAGS),
        "delivery_bytes": size,
        "status": "incomplete",
        "reason": "missing_type",
        "function_category": "absent",
    }


@dataclass(frozen=True, slots=True, repr=False)
class DataUpdatedResult:
    """Private decoded content plus an explicitly closed diagnostic projection."""

    _report: dict = field(repr=False)
    metadata: bytes | None = field(default=None, repr=False)
    response: ModbusReadResponse | ModbusExceptionResponse | None = field(
        default=None, repr=False
    )

    def safe_report(self):
        """Revalidate keys AND values; never serialize the dataclass or response."""
        source = self._report if type(self._report) is dict else {}
        return {
            "length_scope": "read_delivery",
            "boundary_proven": False,
            "status": source.get("status")
            if type(source.get("status")) is str and source["status"] in _STATUSES
            else "malformed",
            "reason": source.get("reason")
            if type(source.get("reason")) is str and source["reason"] in _REASONS
            else "invalid_length",
            "function_category": source.get("function_category")
            if type(source.get("function_category")) is str
            and source["function_category"] in _FUNCTIONS
            else "unsupported",
            **{
                key: source.get(key)
                if type(source.get(key)) is int and 0 <= source[key] <= maximum
                else None
                for key, maximum in _NUMBERS.items()
            },
            **{
                key: source.get(key) if type(source.get(key)) is bool else None
                for key in sorted(_FLAGS)
            },
        }

    def __repr__(self):
        report = self.safe_report()
        return (
            f"DataUpdatedResult(status={report['status']}, reason={report['reason']})"
        )


def unexamined_delivery(size, reason):
    """Unknown boundary: record the read size without examining any sections."""
    report = _empty_report(size)
    report.update(status="ambiguous", reason=reason)
    return DataUpdatedResult(report)


def parse_data_updated(data: bytes) -> DataUpdatedResult:
    """Analyze the complete supplied candidate; never split, join or scan bytes.

    Functions 03/04 and their exception forms follow Modbus V1.1b3 §§6.3/6.4/7.
    Unsupported PDUs remain opaque. A coherent Length never authorizes consuming
    only a prefix: trailing bytes make this entire delivery ambiguous.
    """
    if type(data) is not bytes:
        raise TypeError("DataUpdated delivery must be bytes")
    size = len(data)
    report = _empty_report(size)

    def outcome(status, reason, response=None):
        report.update(status=status, reason=reason)
        return DataUpdatedResult(
            report,
            data[1:5] if 5 <= size <= 4096 and data[0] == 27 else None,
            response,
        )

    if size > 4096:
        return outcome("malformed", "oversized_delivery")
    if not data:
        return outcome("incomplete", "missing_type")
    if data[0] != 27:
        report["discriminator_valid"] = False
        return outcome("malformed", "wrong_type")
    report.update(
        discriminator_valid=True,
        metadata_bytes=min(4, max(0, size - 1)),
        metadata_complete=size >= 5,
        mbap_bytes=min(7, max(0, size - 5)),
        mbap_complete=size >= 12,
        unit_present=size >= 12,
        function_present=size >= 13,
        pdu_bytes=max(0, size - 12),
        transaction_present=size >= 7,
        protocol_present=size >= 9,
        mbap_length_present=size >= 11,
    )
    if size >= 9:
        report["protocol_valid"] = data[7:9] == b"\x00\x00"
    if size >= 11:
        length = int.from_bytes(data[9:11], "big")
        report.update(
            declared_mbap_length=length, length_consistent=size - 11 == length
        )
    if size >= 13:
        report["function_category"] = {
            3: "read_holding",
            4: "read_input",
            131: "read_exception",
            132: "read_exception",
        }.get(data[12], "unsupported")
    if size >= 13 and data[12] in {3, 4}:
        report["byte_count_present"] = size >= 14
        if size >= 14:
            report["declared_value_bytes"] = data[13]
            report["observed_value_bytes"] = size - 14
    elif size >= 13 and data[12] in {131, 132}:
        report["byte_count_present"] = False
    if size < 5:
        return outcome("incomplete", "missing_metadata")
    if size < 12:
        return outcome("incomplete", "missing_mbap")
    if not report["protocol_valid"]:
        return outcome("malformed", "invalid_protocol")
    if not 2 <= length <= 254:
        return outcome("malformed", "invalid_length")
    if size - 11 < length:
        return outcome("incomplete", "body_missing")
    if size - 11 > length:
        return outcome("ambiguous", "delivery_suffix")
    function = data[12]  # Length >=2 and exact internal size guarantee this byte.
    if function not in {3, 4, 131, 132}:
        return outcome("unsupported", "unsupported_function")
    if function in {131, 132}:
        if size - 12 != 2:
            return outcome("malformed", "exception_size")
        report["value_count"] = 0
        return outcome("parsed", "read_exception", decode_read_response(data[5:]))
    if size < 14:
        return outcome("incomplete", "missing_byte_count")
    count = data[13]
    if count == 0 or count % 2 or count > 250:
        return outcome("malformed", "invalid_byte_count")
    if size - 14 < count:
        return outcome("incomplete", "values_missing")
    if size - 14 > count:
        return outcome("ambiguous", "values_extra")
    report["value_count"] = count // 2
    return outcome("parsed", "ok", decode_read_response(data[5:]))
