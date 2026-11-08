"""Closed verdicts over real V4Session evidence; never a framer-only success."""

import ast
import asyncio
import copy
import logging
from pathlib import Path

import pytest

from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportTlsError,
)
from scripts.info_delivery_scenario import (
    InfoDeliveryScenario,
    InvalidInfoEvidence,
    OfflineTransportLedger,
    encode_report,
    validate_report,
)
from tests.info_delivery_fixture_186 import run_case
from tests.test_info_delivery_drop_186 import owner
from tests.test_session_ignored_rx import ignored_frame
from tests.tls_read_candidate_186 import PING, RESPONSE


def test_controlled_info_ping_read_and_cleanup_are_proven(monkeypatch):
    result = asyncio.run(run_case(monkeypatch))
    report = result.report
    assert report["result"] == "SUCCESS"
    assert report["info_discarded"] == report["reads_after_drop"] == 1
    assert report["pings_after_drop"] == report["pongs_after_drop"] == 1
    assert report["openings"] == 1 and report["reconnections"] == 0
    assert report["cleanup_attested"] and report["rx_reaped"]
    assert result.session.cleanup_succeeded and result.wire.close_count == 1
    assert result.factory.call_count == 1
    assert report["steps"]["drop"] < report["steps"]["ping"] < report["steps"]["pong"]
    assert (
        report["steps"]["pong"] < report["steps"]["request"] < report["steps"]["read"]
    )
    assert len(encode_report(report).encode()) <= 8192


def test_info_absent_is_inconclusive_despite_a_valid_v4_read(monkeypatch):
    result = asyncio.run(run_case(monkeypatch, deliveries=()))
    assert result.session.verified_read_sequence == 1
    assert result.report["result"] == "INCONCLUSIVE"
    assert result.report["reason"] == "info_absent"
    assert result.report["reads_after_drop"] == result.report["info_discarded"] == 0


def test_contradictory_post_drop_counter_is_refused_even_if_inconclusive(monkeypatch):
    report = copy.deepcopy(asyncio.run(run_case(monkeypatch, deliveries=())).report)
    report["reads_after_drop"] = report["requests_after_drop"] = 1
    with pytest.raises(InvalidInfoEvidence):
        validate_report(report)


@pytest.mark.parametrize("code", [None, *range(8), 255])
def test_opaque_info_subcode_does_not_change_the_proof(monkeypatch, code):
    info = b"\x0c" + (b"" if code is None else bytes((code,)))
    result = asyncio.run(run_case(monkeypatch, deliveries=(info, PING)))
    assert result.report["result"] == "SUCCESS"
    assert result.report["info_delivery_bytes"] == [len(info)]
    assert result.report["boundary_proven"] is False
    assert result.report["info_framing"] == "INCONCLUSIVE"


@pytest.mark.parametrize("split", [1, 7, 9, 49])
def test_fragmented_correlated_response_and_other_mbap_messages(monkeypatch, split):
    result = asyncio.run(
        run_case(
            monkeypatch,
            replies=(
                ignored_frame(7),
                ignored_frame(27),
                RESPONSE[:split],
                RESPONSE[split:],
            ),
        )
    )
    assert result.report["result"] == "SUCCESS"
    assert result.session.verified_read_sequence == 1


@pytest.mark.parametrize("limit", [1, 3, 16])
def test_multiple_drops_are_bounded_and_require_proof_after_last(monkeypatch, limit):
    result = asyncio.run(
        run_case(
            monkeypatch,
            deliveries=(b"\x0c",) * limit + (PING,),
            limit=limit,
        )
    )
    assert result.report["result"] == "SUCCESS"
    assert result.report["info_discarded"] == limit
    assert result.report["info_delivery_bytes"] == [1] * limit
    assert result.factory.call_count == result.wire.close_count == 1


@pytest.mark.parametrize(
    "case",
    [
        "fragment",
        "lost-ping",
        "lost-response",
        "unsolicited",
        "wrong-correlation",
        "invalid-mbap",
        "eof",
        "tls",
        "certificate",
        "auth",
        "internal",
        "close-client",
        "timeout",
        "cancel",
        "default-off",
        "opening-suffix",
        "cached",
        "double-open",
        "exhausted",
        "cleanup",
        "cleanup-timeout",
        "collection-timeout",
    ],
)
def test_fail_closed_matrix(monkeypatch, case):
    options = {
        "fragment": {"deliveries": (b"\x0c", b"\x02", PING)},
        "lost-ping": {"deliveries": (b"\x0c" + PING,)},
        "lost-response": {"replies": (b"\x0c" + RESPONSE,)},
        "unsolicited": {"deliveries": (b"\x0c", PING, RESPONSE)},
        "wrong-correlation": {"replies": (RESPONSE[:1] + b"\x00\x01" + RESPONSE[3:],)},
        "invalid-mbap": {"replies": (bytes.fromhex("0effff00010003"),)},
        "eof": {"replies": (TransportEOF(),)},
        "tls": {"replies": (TransportTlsError("PRIVATE_186C"),)},
        "certificate": {"replies": (TransportCertificateError("PRIVATE_186C"),)},
        "auth": {"replies": (b"\x2f",)},
        "internal": {"replies": (RuntimeError("PRIVATE_186C"),)},
        "close-client": {"replies": (b"\x05\x03",)},
        "timeout": {"replies": ()},
        "cancel": {"replies": (), "cancel": True},
        "default-off": {"enabled": False},
        "opening-suffix": {"suffix": b"\x0c"},
        "cached": {"before_drop_read": True},
        "double-open": {"duplicate_open": True},
        "exhausted": {"limit": 1, "deliveries": (b"\x0c", b"\x0c", PING)},
        "cleanup": {"close_error": TransportTlsError("PRIVATE_186C")},
        "cleanup-timeout": {"close_delay": 6},
        "collection-timeout": {"delivery_delay": 31},
    }[case]
    result = asyncio.run(run_case(monkeypatch, **options))
    report = result.report
    assert report["result"] == "FAILURE"
    assert result.factory.call_count == 1
    assert result.session._rx_task.done()
    assert not result.session._tx_operations
    assert result.wire.active_reads == result.wire.active_tx == 0
    assert "PRIVATE_186C" not in encode_report(report)
    if case == "cached":
        assert result.session.verified_read_sequence == 1
        assert report["reads_after_drop"] == 0
    if case in ("timeout", "lost-response"):
        assert 5000 <= report["collection_ms"] < 6000
        assert report["first_error"] == "timeout"
    if case in ("cleanup", "cleanup-timeout"):
        assert not report["cleanup_attested"]


def test_never_started_has_no_attested_cleanup_or_success():
    session, wire, factory = owner()
    scenario = InfoDeliveryScenario(
        session, OfflineTransportLedger(wire), clock=lambda: 0
    )
    report = scenario.finish()
    assert report["result"] == "NOT RUN"
    assert not report["started"] and not report["cleanup_attested"]
    factory.assert_not_called()


@pytest.mark.parametrize(
    "mutation",
    [
        "key",
        "private-reason",
        "bool-counter",
        "boundary",
        "framing",
        "size",
        "drops",
        "sequence",
        "reconnections",
        "verdict",
        "cleanup",
        "limit",
        "age",
        "nested-key",
    ],
)
def test_report_tampering_is_refused(monkeypatch, mutation):
    report = copy.deepcopy(asyncio.run(run_case(monkeypatch)).report)
    if mutation == "key":
        report["payload"] = "PRIVATE_186C"
    elif mutation == "private-reason":
        report["first_error"] = "PRIVATE_186C"
    elif mutation == "bool-counter":
        report["reads_after_drop"] = True
    elif mutation == "boundary":
        report["boundary_proven"] = True
    elif mutation == "framing":
        report["info_framing"] = "proven"
    elif mutation == "size":
        report["info_delivery_bytes"] = [4097]
    elif mutation == "drops":
        report["info_discarded"] = 17
    elif mutation == "sequence":
        report["steps"]["read"] = report["steps"]["request"]
    elif mutation == "reconnections":
        report["reconnections"] = 1
    elif mutation == "verdict":
        report["result"] = "FAILURE"
    elif mutation == "cleanup":
        report["cleanup_attested"] = False
    elif mutation == "limit":
        report["limits"]["max_drops"] = 17
    elif mutation == "age":
        report["elapsed_ms"] = 35001
    else:
        report["steps"]["traceback"] = "PRIVATE_186C"
    with pytest.raises(InvalidInfoEvidence, match="^invalid_offline_info_evidence$"):
        encode_report(report)


def test_private_delivery_and_exception_never_escape_report_or_logs(
    monkeypatch, caplog
):
    caplog.set_level(logging.DEBUG, logger="custom_components.hoben.v4_session")
    result = asyncio.run(
        run_case(
            monkeypatch,
            deliveries=(b"\x0cPRIVATE_186C_DELIVERY", PING),
            replies=(RuntimeError("PRIVATE_186C_EXCEPTION"),),
        )
    )
    assert result.report["result"] == "FAILURE"
    assert result.report["first_error"] == "internal"
    assert "PRIVATE_186C" not in encode_report(result.report) + caplog.text


def test_offline_observer_has_no_io_driver_cli_or_capability_supplier():
    source = Path("scripts/info_delivery_scenario.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                "connect",
                "read",
                "write",
                "abort",
                "request_v4_data",
                "close",
                "run",
                "create_task",
                "open_connection",
            }
    assert "__main__" not in source
    assert "_InfoDeliveryDropExperiment" not in source
    assert not any(
        isinstance(node, ast.keyword) and node.arg == "_info_delivery_drop"
        for node in ast.walk(tree)
    )


def test_last_drop_cannot_reuse_an_earlier_ping_pong(monkeypatch):
    result = asyncio.run(run_case(monkeypatch, deliveries=(b"\x0c", PING, b"\x0c")))
    assert result.report["result"] == "FAILURE"
    assert result.report["pings_after_drop"] == result.report["pongs_after_drop"] == 0
    assert result.report["info_discarded"] == 2
    assert result.report["reads_after_drop"] == 1


def test_collected_sizes_are_delivery_sizes_not_info_frame_lengths(monkeypatch):
    result = asyncio.run(
        run_case(
            monkeypatch,
            deliveries=(b"\x0c" + PING + RESPONSE, PING),
        )
    )
    assert result.report["result"] == "SUCCESS"
    assert result.report["info_delivery_bytes"] == [1 + len(PING) + len(RESPONSE)]
    assert result.report["pings_after_drop"] == 1
    assert result.session.verified_read_sequence == 1  # Only the NEW response.


@pytest.mark.parametrize("value", [-1, True, float("inf"), float("nan"), "PRIVATE"])
def test_invalid_clock_refused_before_any_session_action(value):
    session, wire, factory = owner()
    with pytest.raises(InvalidInfoEvidence):
        InfoDeliveryScenario(session, OfflineTransportLedger(wire), clock=lambda: value)
    factory.assert_not_called()


def test_clock_rollback_fails_closed_without_inventing_elapsed_time():
    session, wire, factory = owner()
    now = [1.0]
    scenario = InfoDeliveryScenario(
        session, OfflineTransportLedger(wire), clock=lambda: now[0]
    )
    now[0] = 0
    scenario.sample()
    report = scenario.finish()
    assert report["result"] == "FAILURE" and report["first_error"] == "clock"
    assert report["elapsed_ms"] == 0
    factory.assert_not_called()


def test_submillisecond_clock_rollback_cannot_pass_by_rounding():
    session, wire, _ = owner()
    now = [1.0]
    scenario = InfoDeliveryScenario(
        session, OfflineTransportLedger(wire), clock=lambda: now[0]
    )
    now[0] -= 0.0001
    scenario.sample()
    assert scenario.finish()["first_error"] == "clock"


def test_fixture_ledger_has_strict_event_and_delivery_caps():
    ledger = OfflineTransportLedger(object())
    for _ in range(128):
        ledger.note("other", 4096)
    with pytest.raises(InvalidInfoEvidence):
        ledger.note("other", 1)
    for kind, size in (("PRIVATE", 1), ("other", 4097), ("other", True)):
        with pytest.raises(InvalidInfoEvidence):
            OfflineTransportLedger(object()).note(kind, size)


@pytest.mark.parametrize("field", ["started", "opened_validated", "same_session"])
def test_success_cannot_be_detached_from_its_session(monkeypatch, field):
    report = copy.deepcopy(asyncio.run(run_case(monkeypatch)).report)
    report[field] = False
    with pytest.raises(InvalidInfoEvidence):
        validate_report(report)


def test_nested_limit_types_are_strict_not_numeric_coercions(monkeypatch):
    report = copy.deepcopy(asyncio.run(run_case(monkeypatch)).report)
    report["limits"]["max_drops"] = 16.0
    with pytest.raises(InvalidInfoEvidence):
        validate_report(report)


def test_observer_evidence_rejection_cannot_skip_final_cleanup(monkeypatch):
    def reject(self):
        raise InvalidInfoEvidence()

    monkeypatch.setattr(InfoDeliveryScenario, "sample", reject)
    result = asyncio.run(run_case(monkeypatch))
    assert result.report["result"] == "FAILURE"
    assert result.report["cleanup_attested"]
    assert result.wire.close_count == result.factory.call_count == 1
    assert result.session._rx_task.done()
