"""#186: distinguish an APK candidate decision from framed/verified RX."""

import asyncio
import copy
import json

import pytest

from custom_components.hoben.exceptions import (
    HobenClosedError,
    HobenProtocolError,
    HobenTransportError,
)
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_experiment import ExperimentalV4Framer, Session300
from custom_components.hoben.v4_session import V4Session
from tests.test_session_300_runtime import Stream
from tests.tls_read_candidate_186 import (
    INVALID_UPDATED,
    PING,
    RESPONSE,
    ApkCandidateModel,
    MemoryCompletions,
    bounded_json,
    compare,
)


def observe(*deliveries):
    report = asyncio.run(compare(deliveries))
    bounded_json(report)  # Every matrix case must also satisfy the report contract.
    return report


@pytest.mark.parametrize("code", [*range(8), 255])
def test_info_subcodes_are_synthetic_observations_never_length_proof(code):
    report = observe(bytes((12, code)))
    apk, ha = report["apk"], report["ha"]
    event = apk["events"][0]
    assert event["synthetic_subcode"] == code
    assert event["event"] == (
        "logical_read_decision_no_tx"
        if code in (2, 4)
        else "forward_entire_delivery"
        if code in (0, 1, 5, 6)
        else "info_fallthrough"
    )
    assert ha["guard"] == "unsupported_type" and ha["dispatch_count"] == 0
    assert report["info_total_bytes"] == "not_proven"
    assert report["boundary_proven"] is False
    assert apk["correlated_reads"] == ha["correlated_reads"] == "not_executed"


@pytest.mark.parametrize("code", [*range(8), 255])
def test_split_info_is_not_reassembled_or_skipped(code):
    report = observe(b"\x0c", bytes((code,)))
    assert [e["event"] for e in report["apk"]["events"]] == [
        "fallthrough",
        "fallthrough",
    ]
    assert report["apk"]["delivery_bytes"] == [1, 1]
    assert report["ha"]["delivery_bytes"] == [1]  # RX stops before another read.
    assert report["ha"]["guard"] == "unsupported_type"


def test_lone_info_does_not_imply_a_two_byte_message():
    report = observe(b"\x0c")
    assert report["apk"]["events"] == [{"event": "fallthrough", "delivery_bytes": 1}]
    assert report["ha"]["guard"] == "unsupported_type"


@pytest.mark.parametrize("code", [*range(8), 255])
def test_concat_info_loses_separate_ping_and_response_dispatch(code):
    for suffix in (PING, RESPONSE):
        report = observe(bytes((12, code)) + suffix)
        assert report["apk"]["pings"] == 0
        assert report["apk"]["decoder_attempts"] == 0
        assert report["apk"]["events"][0]["delivery_bytes"] == 2 + len(suffix)
        assert report["ha"]["dispatch_count"] == 0
        assert report["ha"]["guard"] == "unsupported_type"
    reverse = observe(PING + bytes((12, code)))
    assert reverse["apk"]["pings"] == 1
    assert len(reverse["apk"]["events"]) == 1  # Info suffix never dispatched.
    # Framer rejects before returning its earlier accumulated Ping event.
    assert reverse["ha"]["pings"] == 0
    assert reverse["ha"]["guard"] == "unsupported_type"


@pytest.mark.parametrize("split", range(1, len(RESPONSE)))
def test_every_response_partition_has_one_ha_frame_but_no_apk_reassembly(split):
    report = observe(RESPONSE[:split], RESPONSE[split:])
    assert report["ha"]["complete_responses"] == 1
    assert report["ha"]["dispatch_count"] == 1 and not report["ha"]["partial"]
    assert report["apk"]["decoder_attempts"] == int(split > 2)
    assert report["apk"]["complete_responses"] == 0
    assert report["apk"]["delivery_bytes"] == report["ha"]["delivery_bytes"]


def test_concat_and_ping_partitions_disprove_one_read_one_message():
    whole = observe(PING + RESPONSE + PING)
    assert whole["apk"]["pings"] == 1 and whole["apk"]["decoder_attempts"] == 0
    assert whole["ha"]["pings"] == 2 and whole["ha"]["complete_responses"] == 1
    for deliveries in ((PING * 2,), (PING, PING)):
        report = observe(*deliveries)
        assert report["ha"]["pings"] == 2
        assert report["apk"]["pings"] == len(deliveries)
    responses = observe(RESPONSE * 2)
    assert responses["apk"]["decoder_attempts"] == 1
    assert responses["ha"]["complete_responses"] == 2


@pytest.mark.parametrize("cut", [1, 2, 3, 6, 7, 8, 9, 49])
@pytest.mark.parametrize("ending", [b"", TransportEOF(), TransportTlsError()])
def test_truncation_eof_and_tls_never_invent_completion(cut, ending):
    report = observe(RESPONSE[:cut], ending)
    assert report["ha"]["complete_responses"] == 0
    if type(ending) is TransportTlsError:
        assert "partial_eof_provenance" not in report["ha"]
    else:
        assert report["ha"]["partial_eof_provenance"] == "partial_eof"
    assert report["ha"]["guard"] in ("eof", "tls_error")
    if isinstance(ending, Exception):
        event = report["apk"]["events"][-1]
        assert event["event"] == "local_server_timeout"
        assert event["synthetic_subcode"] == 3 and event["delivery_bytes"] == 0
    else:
        assert report["apk"]["events"][-1]["event"] == "zero_read_fallthrough"
        assert report["apk"]["rx_state"] == "not_established"


def test_valid_invalid_mbap_dataupdated_close_and_unknown_have_distinct_guards():
    good = observe(RESPONSE)
    assert good["apk"]["decoder_attempts"] == good["ha"]["complete_responses"] == 1
    assert good["apk"]["correlated_reads"] == "not_executed"
    assert observe(bytes.fromhex("0effff0000ffff"))["ha"]["guard"] == "invalid_mbap"
    updated = observe(INVALID_UPDATED, PING)
    assert updated["apk"]["decoder_attempts"] == 1
    assert updated["ha"]["guard"] == "data_updated_policy_not_executed"
    close = observe(b"\x05\x03" + PING + RESPONSE)
    assert close["apk"]["events"][0]["delivery_bytes"] == 53
    assert close["ha"]["events"] == [{"event": "close_client", "frame_bytes": 2}]
    assert close["ha"]["guard"] == "close_client_post_open_hypothesis"
    assert observe(b"\xff")["ha"]["guard"] == "unknown_type"


def test_close_fragments_and_empty_eof_do_not_prove_a_live_session():
    close = observe(b"\x05", b"\x03")
    assert close["apk"]["dispatch_count"] == 0
    assert close["ha"]["events"] == [{"event": "close_client", "frame_bytes": 2}]
    for ending in (b"", TransportEOF(), TransportTlsError()):
        report = observe(ending)
        assert report["ha"]["dispatch_count"] == 0
        assert report["ha"]["guard"] in ("eof", "tls_error")
        assert report["apk"]["rx_state"] != "connected"


def test_info_timeout_limit_is_cumulative_and_retry_is_observation_only():
    model = ApkCandidateModel()
    for _ in range(4):
        model.delivery(b"\x0c\x02")
        model.delivery(RESPONSE)  # Not evidence of an APK counter reset.
    assert model.expected_read_attempts == 3 and model.timeout_count == 4
    assert model.report["events"][-2]["event"] == "forward_entire_delivery"
    for _ in range(5):
        model.delivery(b"\x0c\x04")
    assert model.expected_read_attempts == 8  # No TX or native retry execution.


def test_report_has_only_closed_scalars_and_sizes_not_exception_text_or_payload(caplog):
    secret_marker = "PRIVATE_186_PAYLOAD"
    report = observe(
        b"\x0c\x05" + secret_marker.encode(), TransportTlsError(secret_marker)
    )
    encoded = bounded_json(report)
    assert len(encoded.encode()) <= 8192 and json.loads(encoded) == report
    assert secret_marker not in encoded + caplog.text
    assert RESPONSE.hex() not in encoded and "traceback" not in encoded.lower()
    assert set(report) == {
        "synthetic",
        "source",
        "size_unit",
        "re_head",
        "info_total_bytes",
        "boundary_proven",
        "apk",
        "ha",
    }
    assert report["source"] == "prescribed_plaintext_read_completion"
    too_large = copy.deepcopy(report)
    too_large["apk"]["events"] *= 64
    with pytest.raises(ValueError, match="synthetic_report_budget"):
        bounded_json(too_large)
    with pytest.raises(ValueError, match="invalid_synthetic_deliveries"):
        MemoryCompletions([b"x"] * 65)
    with pytest.raises(ValueError, match="invalid_synthetic_deliveries"):
        MemoryCompletions([b"x" * 4097])
    with pytest.raises(ValueError, match="synthetic_event_budget"):
        observe(PING * 4096)


@pytest.mark.parametrize("mutation", ["extra", "text", "counter", "proof", "event"])
def test_report_refuses_untrusted_extensions_and_false_proof(mutation):
    report = observe(PING)
    if mutation == "extra":
        report["raw"] = "PRIVATE_186"
    elif mutation == "text":
        report["ha"]["guard"] = "PRIVATE_186"
    elif mutation == "counter":
        report["apk"]["pings"] = True
    elif mutation == "proof":
        report["boundary_proven"] = True
    else:
        report["apk"]["events"][0]["event"] = "PRIVATE_186"
    with pytest.raises(ValueError, match="invalid_synthetic_report"):
        bounded_json(report)


def test_framer_keeps_first_byte_exchange_across_fragmented_header():
    framer, first, later = ExperimentalV4Framer(), object(), object()
    assert framer.feed(RESPONSE[:3], first) == []
    (event,) = framer.feed(RESPONSE[3:], later)
    assert event.exchange is first and event.exchange is not later


@pytest.mark.parametrize(
    "fault", [b"\x0c\x00", b"\x05\x03", TransportEOF(), TransportTlsError()]
)
def test_real_session_failure_never_becomes_a_verified_read_and_cleans_once(fault):
    async def scenario():
        wire, budget = Stream([fault]), Session300()
        session = V4Session(
            user_guid="b" * 32, transport_factory=lambda: wire, session_300=budget
        )
        await session.connect()
        try:
            with pytest.raises(
                (HobenProtocolError, HobenTransportError, HobenClosedError)
            ):
                await session.request_v4_data()
            assert session.verified_read_sequence == budget.responses == 0
            assert wire.active_reads == 0
        finally:
            await session.abort()
        assert session.cleanup_succeeded and wire.close_count == 1
        assert not session._operations and session._rx_task.done()

    asyncio.run(scenario())


def test_opening_suffix_is_not_a_separate_read_completion_or_boundary():
    async def scenario():
        # One opening delivery has a Ping suffix; the following TLS read has
        # the response. Never feed the suffix to the APK as a separate delivery.
        wire, budget = Stream([RESPONSE[:7], RESPONSE[7:]], suffix=PING), Session300()
        original_read, read_sizes = wire.read, []

        async def measured_read(max_bytes=4096, *, bounded=True):
            result = await original_read(max_bytes, bounded=bounded)
            read_sizes.append((bounded, len(result)))
            return result

        wire.read = measured_read
        session = V4Session(
            user_guid="b" * 32, transport_factory=lambda: wire, session_300=budget
        )
        await session.connect()
        await session.request_v4_data()
        assert budget.pings == budget.pongs == session.verified_read_sequence == 1
        assert budget.responses == 1 and session.snapshot.boundary_proven is False
        assert read_sizes == [(True, 49), (False, 7), (False, 43)]
        await session.abort()
        assert session.cleanup_succeeded and wire.close_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "deliveries,suffix",
    [
        ([PING, TransportEOF()], b""),
        ([RESPONSE[:1] + b"\x00\x01" + RESPONSE[3:]], b""),
        ([], RESPONSE),  # Opening suffix cannot correlate a future request.
    ],
    ids=["ping-not-read", "wrong-transaction", "unsolicited-opening-suffix"],
)
def test_real_session_cannot_credit_stale_or_uncorrelated_data(deliveries, suffix):
    async def scenario():
        wire, budget = Stream(deliveries, suffix=suffix), Session300()
        session = V4Session(
            user_guid="b" * 32, transport_factory=lambda: wire, session_300=budget
        )
        await session.connect()
        try:
            with pytest.raises((HobenProtocolError, HobenTransportError)):
                await session.request_v4_data()
            assert session.verified_read_sequence == budget.responses == 0
        finally:
            await session.abort()
        assert session.cleanup_succeeded and wire.close_count == 1

    asyncio.run(scenario())
