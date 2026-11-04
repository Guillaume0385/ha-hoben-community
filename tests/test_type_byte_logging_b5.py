"""B5 discloses one classified discriminator in WARNING text, never a tail."""

import json
import logging

import pytest

from custom_components.hoben.exceptions import HobenError, HobenProtocolError
from custom_components.hoben.frame_diagnostic import FrameDiagnostic, FrameEvidence
from custom_components.hoben.v4_experiment import (
    ExperimentalCloseClientError,
    ExperimentalV4Framer,
)
from tests.test_frame_logging import LOGGER, records
from tests.test_session_300_runtime import response

PRIVATE = b"PRIVATE_PAYLOAD\xab\xcd\xef"


@pytest.mark.parametrize("head", [0xFE, 0x2A, 0x01, 0x00])
@pytest.mark.parametrize("classified", [False, True])
@pytest.mark.parametrize("suffix", [b"", PRIVATE])
def test_exact_discriminator_only_in_single_warning_text(
    caplog, head, classified, suffix
):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    framer = ExperimentalV4Framer(classify_frame_boundary=classified)
    with pytest.raises(HobenProtocolError) as caught:
        framer.feed(bytes([head]) + suffix, None)
    warnings = [r for r in caplog.records if r.name == LOGGER]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert f"message_type_byte=0x{head:02X}" in warnings[0].getMessage()
    (error,) = records(caplog, "error")
    assert error["received_bytes"] == 1 and error["expected_total_bytes"] == "unknown"
    assert error["length_scope"] == error["provenance"] == "unproven"
    assert "message_type_byte" not in error
    assert "message_type_byte" not in json.dumps(caught.value.safe_report())
    assert "message_type_byte" not in repr(framer.frame_log.evidence)
    assert "PRIVATE_PAYLOAD" not in caplog.text + repr(caught.value)
    for suffix in ("0xAB", "0xCD", "0xEF"):
        assert suffix not in caplog.text


@pytest.mark.parametrize("split", range(1, 51))
def test_fragmented_valid_message_then_rejected_type_has_one_warning(caplog, split):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    data = response() + b"\xfe" + PRIVATE
    framer.feed(data[:split], None)
    with pytest.raises(HobenProtocolError):
        framer.feed(data[split:], None)
    assert caplog.text.count("message_type_byte=0xFE") == 1
    assert len(records(caplog, "error")) == 1
    assert "PRIVATE_PAYLOAD" not in caplog.text


@pytest.mark.parametrize("prefix", [b"\x05", b"\x0e", b"\x07", b"\x1bSECR"])
def test_partial_eof_does_not_disclose_a_type_byte(caplog, prefix):
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    framer.feed(prefix, None)
    framer.incomplete_error()
    assert len(records(caplog, "error")) == 1
    assert "message_type_byte" not in caplog.text


@pytest.mark.parametrize("prefix", [b"\x0e", b"\x07", b"\x1bSECR"])
def test_invalid_mbap_and_dataupdated_recovery_have_no_type_disclosure(caplog, prefix):
    framer = ExperimentalV4Framer(
        classify_frame_boundary=True, recover_data_updated=True
    )
    try:
        framer.feed(prefix + b"\xff\xff\x00\x00\xff\xff" + PRIVATE, None)
    except HobenProtocolError:
        pass
    assert "message_type_byte" not in caplog.text
    assert "PRIVATE_PAYLOAD" not in caplog.text
    if prefix[0] == 27:
        assert framer.invalid_data_updated == (65535, "invalid_length")


def test_known_bodies_metadata_ping_and_close_never_disclose_an_octet(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    frame = response()[:10] + b"\xfe\x2a" * 20
    data = (
        b"\x0a"
        + frame
        + b"\x07"
        + frame[1:]
        + b"\x1b\xfe\x2aAB"
        + frame[1:]
        + b"\x05\x03"
    )
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    frames = []
    for byte in data:
        frames.extend(framer.feed(bytes([byte]), None))
    frames[-1].evidence.failure(ExperimentalCloseClientError(3), status="complete")
    assert len(records(caplog, "error")) == 1
    assert "message_type_byte" not in caplog.text
    assert all(
        "message_type_byte" not in r.hoben_frame
        for r in caplog.records
        if r.name == LOGGER
    )


@pytest.mark.parametrize("head", [0x2F, 0x30])
def test_authorization_markers_keep_their_existing_permanent_path(caplog, head):
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    with pytest.raises(HobenError):
        framer.feed(bytes([head]) + PRIVATE, None)
    assert (
        "message_type_byte" not in caplog.text and "PRIVATE_PAYLOAD" not in caplog.text
    )
    assert framer.boundary_failure is None


@pytest.mark.parametrize("drain", [b"", b"\x0a"])
def test_terminal_close_tail_is_never_a_proven_new_discriminator(caplog, drain):
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    framer.feed(b"\x05\x03\xfe" + PRIVATE, None)
    with pytest.raises(HobenProtocolError):
        framer.feed(drain, None)
    assert "message_type_byte" not in caplog.text
    assert "PRIVATE_PAYLOAD" not in caplog.text


def test_local_exception_at_classification_is_not_a_disclosed_wire_rejection(caplog):
    class Broken:
        def note_failure(self, *args):
            raise RuntimeError("PRIVATE_PAYLOAD")

        def rejected_type_category(self, _):
            return "unknown"

    framer = ExperimentalV4Framer(classify_frame_boundary=True, diagnostic=Broken())
    with pytest.raises(RuntimeError):
        framer.feed(b"\xfe" + PRIVATE, None)
    assert (
        "message_type_byte" not in caplog.text and "PRIVATE_PAYLOAD" not in caplog.text
    )


def test_phase_and_single_byte_count_without_framer_proof_do_not_disclose(caplog):
    FrameEvidence(received_bytes=1).emit(
        "error", category="protocol", phase="message_classification", status="invalid"
    )
    log = FrameDiagnostic()
    log.start(0xFE)
    log.rejected_type(0xFE)  # No examined byte yet: the proof must not be armed.
    log.received()
    log.failure_phase = "message_classification"
    log.failure(HobenProtocolError(), status="invalid")
    assert "message_type_byte" not in caplog.text


def test_mismatched_known_message_evidence_cannot_disclose_an_unrelated_byte(caplog):
    log = FrameDiagnostic()
    log.start(14)
    log.received()
    log.rejected_type(0xFE)
    log.failure_phase = "message_classification"
    log.failure(HobenProtocolError(), status="invalid")
    assert "message_type_byte" not in caplog.text


class IntSubclass(int):
    pass


@pytest.mark.parametrize(
    "value", [None, True, False, -1, 256, 1.0, "0xFE", b"\xfe", {}, IntSubclass(254)]
)
def test_non_exact_or_out_of_range_scalar_cannot_be_logged(caplog, value):
    log = FrameDiagnostic()
    log.start(0xFE)
    log.received()
    log.failure_phase = "message_classification"
    log.rejected_type(value)
    log.failure(HobenProtocolError(), status="invalid")
    assert "message_type_byte" not in caplog.text


@pytest.mark.parametrize("count", [0, 2, 48])
def test_only_one_examined_byte_is_admissible(caplog, count):
    log = FrameDiagnostic()
    log.start(0xFE)
    for _ in range(count):
        log.received()
    log.failure_phase = "message_classification"
    log.rejected_type(0xFE)
    log.failure(HobenProtocolError(), status="invalid")
    assert "message_type_byte" not in caplog.text


def test_one_warning_per_rejection_and_no_stale_marker_after_clear(caplog):
    framer = ExperimentalV4Framer(classify_frame_boundary=True)
    with pytest.raises(HobenProtocolError) as caught:
        framer.feed(b"\xfe", None)
    framer.frame_log.failure(caught.value, status="invalid")
    assert caplog.text.count("message_type_byte=0xFE") == 1
    framer.clear()
    framer.feed(b"\x0e", None)
    framer.incomplete_error()
    assert len(records(caplog, "error")) == 2
    assert caplog.text.count("message_type_byte=") == 1
