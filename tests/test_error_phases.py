"""Closed provenance preserves exception classes, privacy and cancellation."""

import asyncio

import pytest

from custom_components.hoben.error_phases import (
    PHASES,
    error_boundary,
    phase_of,
    with_phase,
)
from custom_components.hoben.exceptions import HobenProtocolError, HobenTransportError
from custom_components.hoben.malformed import MalformedDiagnostic
from custom_components.hoben.v4_experiment import ExperimentalCloseClientError


@pytest.mark.parametrize("phase", sorted(PHASES))
def test_local_phase_is_a_scalar_without_changing_the_typed_failure(phase):
    error = HobenTransportError()
    assert with_phase(error, phase) is error
    assert type(error) is HobenTransportError
    assert error.safe_report() == {
        "state": "error",
        "error": "transport_unavailable",
        "phase": phase,
    }


def test_nested_boundaries_keep_the_innermost_proof_and_original_exception():
    error = RuntimeError("PRIVATE_PAYLOAD")
    with pytest.raises(RuntimeError) as caught:
        with error_boundary("frame_boundary"), error_boundary("mbap_header"):
            raise error
    assert caught.value is error and phase_of(error) == "mbap_header"


@pytest.mark.parametrize("private", ["PRIVATE_PAYLOAD", True, 17, {}, [], object()])
def test_metadata_is_validated_again_at_every_export(private):
    error = with_phase(HobenTransportError(), "tls_read")
    error._hoben_error_phase = private
    assert phase_of(error) is None
    assert error.safe_report() == {"state": "error", "error": "transport_unavailable"}
    assert phase_of(with_phase(error, private)) == "unknown"


def test_informative_malformed_and_close_diagnostics_are_not_overwritten():
    error = HobenProtocolError(MalformedDiagnostic(phase="request_correlation"))
    with_phase(error, "pdu_decode")
    assert error.safe_report()["phase"] == "request_correlation"
    closed = ExperimentalCloseClientError(3)
    with_phase(closed, "frame_boundary")
    assert closed.safe_report()["phase"] == "post_open"
    assert closed.safe_report()["reason"] == "stove_connection_required"


def test_cancellation_and_unset_provenance_remain_unannotated():
    cancelled = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        with error_boundary("tls_read"):
            raise cancelled
    assert phase_of(cancelled) is None
    assert phase_of(RuntimeError("PRIVATE_PAYLOAD")) is None


def test_broken_metadata_access_cannot_mask_the_primary_exception():
    class OpaqueError(Exception):
        def __getattribute__(self, name):
            if name in {
                "_hoben_error_phase",
                "args",
                "__traceback__",
                "__cause__",
                "__context__",
            }:
                raise RuntimeError("PRIVATE_PAYLOAD")
            return super().__getattribute__(name)

        def __setattr__(self, *_):
            raise RuntimeError("PRIVATE_PAYLOAD")

    error = OpaqueError()
    with pytest.raises(OpaqueError) as caught:
        with error_boundary("model_decode"):
            raise error
    assert caught.value is error and phase_of(error) is None
