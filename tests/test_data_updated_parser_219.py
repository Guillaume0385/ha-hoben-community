"""#219-A pure structural analysis; all candidate bytes are invented fixtures."""

import json
import logging

import pytest

from custom_components.hoben.data_updated_parser import (
    DataUpdatedResult,
    parse_data_updated,
)
from custom_components.hoben.frame_diagnostic import emit_data_updated
from custom_components.hoben.modbus import encode_mbap


def candidate(pdu=b"\x04\x04\xbe\xef\x12\x34", *, unit=1):
    return b"\x1bSECR" + encode_mbap(0xCAFE, unit, pdu)


@pytest.mark.parametrize("function", [3, 4])
@pytest.mark.parametrize("unit", [0, 1, 255])
def test_known_read_is_internal_unsigned_data_without_address_or_unit_inference(
    function, unit
):
    result = parse_data_updated(
        candidate(bytes([function, 4, 190, 239, 18, 52]), unit=unit)
    )
    assert result.response.registers == (0xBEEF, 0x1234)
    assert result.response.transaction_id == 0xCAFE and result.response.unit_id == unit
    assert result.metadata == b"SECR"
    report = result.safe_report()
    assert report["status"] == "parsed" and report["value_count"] == 2
    assert report["length_consistent"] and report["protocol_valid"]
    assert report["length_scope"] == "read_delivery" and not report["boundary_proven"]
    assert "SECR" not in repr(result) and "48879" not in repr(result)
    assert not any(
        k in report
        for k in (
            "metadata",
            "transaction_id",
            "unit_id",
            "registers",
            "address",
            "values",
        )
    )


@pytest.mark.parametrize("function", [131, 132])
def test_exception_is_structure_not_acquisition_or_public_error_value(function):
    result = parse_data_updated(candidate(bytes([function, 0xE7])))
    assert result.safe_report()["status"] == "parsed"
    assert result.safe_report()["value_count"] == 0
    assert result.response.exception_code == 0xE7
    assert "exception_code" not in result.safe_report()


@pytest.mark.parametrize("split", range(18))
def test_each_prefix_is_incomplete_and_has_no_response(split):
    result = parse_data_updated(candidate()[:split])
    assert result.safe_report()["status"] == "incomplete"
    assert result.safe_report()["delivery_bytes"] == split
    assert result.response is None


@pytest.mark.parametrize(
    "tail", [b"\x0a", b"\x0e", candidate(), b"\x0a\x0ePRIVATE_PAYLOAD"]
)
def test_suffix_is_not_scanned_split_or_decoded(tail):
    delivery = candidate() + tail
    result = parse_data_updated(delivery)
    assert result.safe_report()["status"] == "ambiguous"
    assert result.safe_report()["reason"] == "delivery_suffix"
    assert result.safe_report()["delivery_bytes"] == len(delivery)
    assert result.response is None


@pytest.mark.parametrize("length", [0, 1, 255, 65535])
def test_invalid_mbap_length_never_requests_that_many_bytes(length):
    delivery = bytearray(candidate())
    delivery[9:11] = length.to_bytes(2)
    report = parse_data_updated(bytes(delivery)).safe_report()
    assert report["status"] == "malformed" and report["reason"] == "invalid_length"
    assert report["declared_mbap_length"] == length
    assert report["delivery_bytes"] == len(delivery)
    assert report["metadata_complete"] and report["mbap_complete"]


def test_nonzero_protocol_id_has_a_closed_fallback_with_all_observable_sections():
    delivery = bytearray(candidate())
    delivery[7:9] = b"\xbe\xef"
    report = parse_data_updated(bytes(delivery)).safe_report()
    assert report["status"] == "malformed" and report["reason"] == "invalid_protocol"
    assert report["metadata_bytes"] == 4 and report["mbap_bytes"] == 7
    assert report["pdu_bytes"] == 6 and report["observed_value_bytes"] == 4
    assert report["declared_value_bytes"] == 4 and report["value_count"] is None
    assert report["protocol_valid"] is False


@pytest.mark.parametrize(
    "pdu,status,reason",
    [
        (b"\x06\x12\x34\xbe\xef", "unsupported", "unsupported_function"),
        (b"\x04", "incomplete", "missing_byte_count"),
        (b"\x04\x00", "malformed", "invalid_byte_count"),
        (b"\x04\x03\x00\x00\x00", "malformed", "invalid_byte_count"),
        (b"\x04\xfc", "malformed", "invalid_byte_count"),
        (b"\x04\x04\x00\x01", "incomplete", "values_missing"),
        (b"\x04\x02\x00\x01\x00\x02", "ambiguous", "values_extra"),
        (b"\x84", "malformed", "exception_size"),
        (b"\x84\x01\x02", "malformed", "exception_size"),
    ],
)
def test_pdu_shapes_fail_without_inventing_registers(pdu, status, reason):
    result = parse_data_updated(candidate(pdu))
    assert result.safe_report()["status"] == status
    assert result.safe_report()["reason"] == reason
    assert result.response is None


def test_largest_read_respects_the_documented_modbus_limit():
    result = parse_data_updated(candidate(b"\x03\xfa" + b"\xbe\xef" * 125))
    assert len(result.response.registers) == result.safe_report()["value_count"] == 125
    assert result.safe_report()["delivery_bytes"] == 264


@pytest.mark.parametrize(
    "delivery",
    [
        candidate(),
        candidate(b"\x06\x12\x34\xbe\xef"),
        candidate()[:8],
        candidate() + b"PRIVATE_PAYLOAD",
    ],
)
def test_every_outcome_has_safe_structured_and_rendered_logging(delivery, caplog):
    caplog.set_level(logging.DEBUG)
    result = parse_data_updated(delivery)
    emit_data_updated(result, generation=2, index=1)
    (record,) = [r for r in caplog.records if hasattr(r, "hoben_data_updated")]
    text = record.getMessage() + json.dumps(record.hoben_data_updated) + repr(result)
    for private in (
        "SECR",
        "PRIVATE_PAYLOAD",
        "cafe",
        "51966",
        "beef",
        "48879",
        "4660",
    ):
        assert private not in text
    assert len(record.getMessage()) < 2048
    assert record.exc_info is None


def test_forged_projection_and_identifier_objects_cannot_escape(caplog):
    caplog.set_level(logging.DEBUG)

    class Private:
        def __str__(self):
            raise AssertionError("private repr must never execute")

    result = DataUpdatedResult(
        {key: Private() for key in parse_data_updated(candidate()).safe_report()}
        | {"RX": b"PRIVATE_PAYLOAD"}
    )
    emit_data_updated(result, generation=Private(), index=Private())
    (record,) = [r for r in caplog.records if hasattr(r, "hoben_data_updated")]
    assert record.hoben_data_updated["generation"] == "unknown"
    assert record.hoben_data_updated["delivery_bytes"] is None
    assert "RX" not in record.hoben_data_updated
    assert "PRIVATE" not in record.getMessage()


def test_invalid_local_input_has_only_constant_errors_and_bounded_report():
    with pytest.raises(TypeError, match="DataUpdated delivery must be bytes"):
        parse_data_updated(bytearray(b"PRIVATE_PAYLOAD"))
    result = parse_data_updated(b"\x1b" * 4097)
    assert result.safe_report()["status"] == "malformed"
    assert result.safe_report()["delivery_bytes"] is None
