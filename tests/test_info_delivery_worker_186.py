"""Real persistent RX, deterministic memory-only worker and truthful reports."""

import asyncio
import json

import pytest

from scripts.info_delivery_supervisor import validate_supervision_report
from tests.info_delivery_worker_fixture_186 import run_worker_case


def case(monkeypatch, **options):
    result = asyncio.run(run_worker_case(monkeypatch, **options))
    report, wire, session = result.report, result.wire, result.session
    assert validate_supervision_report(report) == report
    assert len(json.dumps(report).encode()) <= 8192
    assert result.factory.calls == 1
    assert wire.connect_count == wire.close_count == 1
    assert wire.active_reads == wire.active_tx == 0
    assert session._rx_task.done()
    assert not session._operations and not session._tx_operations
    assert not result.clock._waiters
    assert report["mode"] == "offline" and not report["boundary_proven"]
    assert report["info_framing"] == "INCONCLUSIVE"
    assert report["live_provenance"] == "not_proven"
    return result


def test_real_drop_ping_fresh_read_same_session_cleanup(monkeypatch):
    out = case(monkeypatch)
    report, wire = out.report, out.wire
    assert report["result"] == "SUCCESS"
    assert report["observation"]["result"] == "SUCCESS"
    assert not report["pending_observation"]["cleanup_attested"]
    assert wire.closed and wire.requests == wire.pongs == 1
    assert out.session.verified_read_sequence == 1
    assert (
        report["transport_closed"] and report["rx_reaped"] and report["worker_reaped"]
    )


def test_no_info_observes_entire_window_then_closes(monkeypatch):
    plan = tuple((t * 1000, b"\x0a") for t in range(10, 3540, 60))
    out = case(monkeypatch, plan=plan, close_ms=4999)
    assert out.report["result"] == "INCONCLUSIVE"
    assert out.report["cleanup_started_ms"] == 3_540_000
    assert out.report["elapsed_ms"] == 3_544_999
    assert out.wire.requests == 0
    assert out.report["observation"]["info_discarded"] == 0


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": False},
        {"plan": ((1000, b"\x0c\x0a"),)},
        {"plan": ((1000, b"\x0c"), (1100, b"\x01"))},
        {"replies": ()},
        {"close_fails": True},
        {"close_ack": False},
        {"plan": (), "close_fails": True},
        {"close_ms": 5001},
        {"cancel_at": 500},
        {"cancel_at": 1200, "replies": (), "repeat_cancel": True},
    ],
)
def test_no_success_for_missing_proof_or_cleanup(monkeypatch, options):
    out = case(monkeypatch, **options)
    assert out.report["result"] == "FAILURE"


@pytest.mark.parametrize("split", range(1, 50))
def test_fragmented_correlated_response_is_real_RX_proof(monkeypatch, split):
    from tests.tls_read_candidate_186 import RESPONSE

    out = case(monkeypatch, replies=(RESPONSE[:split], RESPONSE[split:]))
    assert out.report["result"] == "SUCCESS"
    assert out.session.verified_read_sequence == 1


@pytest.mark.parametrize("code", [None, *range(8), 255])
def test_opaque_info_delivery_no_subcode_interpretation(monkeypatch, code):
    data = b"\x0c" + (b"" if code is None else bytes((code,)))
    out = case(monkeypatch, plan=((1000, data), (1100, b"\x0a")))
    assert out.report["result"] == "SUCCESS"
    assert out.report["observation"]["info_delivery_bytes"] == [len(data)]


@pytest.mark.parametrize(
    "kind",
    [
        "wrong-correlation",
        "unsolicited",
        "lost-response",
        "invalid-mbap",
        "opening-suffix",
        "partial-header",
        "eof",
        "tls",
        "authentication",
        "local-error",
        "close-client",
        "excess-drops",
    ],
)
def test_adversarial_RX_matrix(monkeypatch, kind):
    from custom_components.hoben.transport import (
        TransportCertificateError,
        TransportEOF,
        TransportTlsError,
    )
    from tests.tls_read_candidate_186 import RESPONSE

    options = {
        "wrong-correlation": {"replies": (RESPONSE[:1] + b"\x00\x01" + RESPONSE[3:],)},
        "unsolicited": {
            "plan": ((1000, RESPONSE), (1100, b"\x0c"), (1200, b"\x0a")),
            "replies": (),
        },
        "lost-response": {"replies": (b"\x0c" + RESPONSE,)},
        "invalid-mbap": {"replies": (bytes.fromhex("0effff00010003"),)},
        "opening-suffix": {"suffix": b"\x0c"},
        "partial-header": {
            "plan": ((1000, RESPONSE[:3]), (1100, b"\x0c"), (1200, b"\x0a"))
        },
        "eof": {"replies": (TransportEOF(),)},
        "tls": {"replies": (TransportTlsError("PRIVATE_WORKER"),)},
        "authentication": {"replies": (TransportCertificateError("PRIVATE_WORKER"),)},
        "local-error": {"replies": (RuntimeError("PRIVATE_WORKER"),)},
        "close-client": {"replies": (b"\x05\x03",)},
        "excess-drops": {"plan": tuple((t, b"\x0c") for t in (1000, 1100, 1200, 1300))},
    }[kind]
    out = case(monkeypatch, **options)
    assert out.report["result"] == "FAILURE"


@pytest.mark.parametrize("at", [1000, 3_539_990])
def test_success_at_beginning_or_end_reserves_actual_cleanup(monkeypatch, at):
    out = case(monkeypatch, plan=((at, b"\x0c"), (at + 1, b"\x0a")), close_ms=4999)
    assert out.report["result"] == "SUCCESS"
    assert out.report["elapsed_ms"] == at + 5000
    assert out.report["elapsed_ms"] < out.report["cleanup_deadline_ms"] <= 3_600_000


@pytest.mark.parametrize("at", [3_540_000, 3_540_001])
def test_info_at_or_after_deadline_cannot_create_success(monkeypatch, at):
    out = case(monkeypatch, plan=((at, b"\x0c"),))
    assert out.report["result"] != "SUCCESS"
    assert out.wire.requests == 0


@pytest.mark.parametrize("at", [1001, 1101, 1200])
def test_repeated_cancellation_during_observation_read_or_close(monkeypatch, at):
    out = case(
        monkeypatch,
        cancel_at=at,
        repeat_cancel=True,
        close_ms=4000,
        replies=(),
    )
    assert out.report["result"] == "FAILURE"
    assert out.report["first_error"] == "cancelled"
    assert out.report["cleanup_started_ms"] == at


def test_no_orphan_helpers_and_real_memory_cleanup(monkeypatch):
    async def check():
        before = asyncio.all_tasks()
        out = await run_worker_case(monkeypatch)
        assert out.session.cleanup_succeeded and out.wire.closed
        assert asyncio.all_tasks() == before
        return out

    asyncio.run(check())


def test_bounded_ports_reject_network_factory_and_reused_session(monkeypatch):
    from custom_components.hoben.v4_session import V4Session, V4SessionMode
    from scripts.info_delivery_memory import (
        MemoryFactory,
        MemoryTransport,
        OfflineClock,
    )
    from scripts.info_delivery_scenario import InvalidInfoEvidence
    from scripts.info_delivery_worker import run_offline_worker
    from tests.test_v4_session import opened_prefix

    async def check():
        loop = asyncio.get_running_loop()
        clock = OfflineClock(origin=loop.time())
        monkeypatch.setattr(loop, "time", clock.loop_time)
        forbidden_calls = []

        def forbidden():
            forbidden_calls.append(1)
            raise AssertionError("network_factory_must_not_run")

        session = V4Session(
            user_guid="b" * 32,
            mode=V4SessionMode.PERSISTENT,
            transport_factory=forbidden,
        )
        with pytest.raises(InvalidInfoEvidence):
            await run_offline_worker(session=session, clock=clock)
        assert not forbidden_calls
        wire = MemoryTransport(opening=opened_prefix())
        factory = MemoryFactory(wire)
        factory()  # Reusing another worker's memory port is forbidden.
        session = V4Session(
            user_guid="b" * 32, mode=V4SessionMode.PERSISTENT, transport_factory=factory
        )
        with pytest.raises(InvalidInfoEvidence):
            await run_offline_worker(session=session, clock=clock)
        assert wire.connect_count == 0
        with pytest.raises(InvalidInfoEvidence):
            wire.feed(b"x" * 4097)
        for _ in range(32):
            wire.feed(b"\x0a")
        with pytest.raises(InvalidInfoEvidence):
            wire.feed(b"\x0a")
        clock.advance_to(1)
        with pytest.raises(InvalidInfoEvidence):
            clock.advance_to(0)

    asyncio.run(check())


def test_python_Node_contract_live_refusal_and_privacy(monkeypatch, caplog):
    import copy
    import logging
    import subprocess

    from scripts.info_delivery_supervisor import InvalidSupervision
    from tests.test_info_delivery_manual_report_186 import ROOT, node_reports

    caplog.set_level(logging.DEBUG, logger="custom_components.hoben.v4_session")
    out = case(monkeypatch, plan=((1000, b"\x0cPRIVATE_WORKER"), (1100, b"\x0a")))
    report = out.report
    assert report["result"] == "SUCCESS"
    assert node_reports([report["observation"]])[0]["accepted"]
    driver = """
const api=require('./.github/scripts/info-delivery-manual-report.cjs');
const r=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
try {api.validateForLivePublication(r);process.exit(2);}
catch(e){if(e.message!=='info_live_provenance_not_proven')process.exit(3);}
"""
    proc = subprocess.run(
        ["node", "-e", driver],
        input=json.dumps(report),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=10,
    )
    assert proc.returncode == 0
    for key in report:
        bad = copy.deepcopy(report)
        del bad[key]
        with pytest.raises(InvalidSupervision):
            validate_supervision_report(bad)
    for key, value in (
        ("mode", "live"),
        ("boundary_proven", True),
        ("payload", "PRIVATE_WORKER"),
        ("worker_reaped", False),
        ("elapsed_ms", True),
        ("events", report["events"] * 100),
    ):
        bad = {**report, key: value}
        with pytest.raises(InvalidSupervision):
            validate_supervision_report(bad)
    text = json.dumps(report) + caplog.text
    assert "PRIVATE_WORKER" not in text
    assert "Traceback" not in text and "b" * 32 not in text
    assert "raw_rx" not in text


def test_late_correlated_fragments_before_deadline_and_other_mbap(monkeypatch):
    from tests.test_session_ignored_rx import ignored_frame
    from tests.tls_read_candidate_186 import RESPONSE

    out = case(
        monkeypatch,
        replies=(),
        plan=(
            (1000, b"\x0c"),
            (1100, b"\x0a"),
            (2000, ignored_frame(7) + ignored_frame(27) + RESPONSE[:7]),
            (2500, RESPONSE[7:]),
        ),
    )
    assert out.report["result"] == "SUCCESS"
    assert out.report["elapsed_ms"] == 2500
    assert out.wire.requests == 1


def test_missing_info_after_terminal_error_is_failure_not_inconclusive(monkeypatch):
    from custom_components.hoben.transport import TransportEOF

    out = case(monkeypatch, plan=((1000, TransportEOF()),))
    assert out.report["result"] == "FAILURE"
    assert out.report["observation"]["info_discarded"] == 0


def test_worker_entry_refuses_uninstalled_clock_before_connect():
    from custom_components.hoben.v4_session import V4Session, V4SessionMode
    from scripts.info_delivery_memory import (
        MemoryFactory,
        MemoryTransport,
        OfflineClock,
    )
    from scripts.info_delivery_scenario import InvalidInfoEvidence
    from scripts.info_delivery_worker import run_offline_worker
    from tests.test_v4_session import opened_prefix

    async def check():
        clock = OfflineClock(origin=0)
        wire = MemoryTransport(opening=opened_prefix())
        factory = MemoryFactory(wire)
        session = V4Session(
            user_guid="b" * 32, mode=V4SessionMode.PERSISTENT, transport_factory=factory
        )
        with pytest.raises(InvalidInfoEvidence):
            await run_offline_worker(session=session, clock=clock)
        assert wire.connect_count == factory.calls == 0

    asyncio.run(check())


def test_late_ping_never_rearms_C_collection_or_cleanup_budget(monkeypatch):
    out = case(
        monkeypatch, replies=(), close_ms=4999, plan=((1000, b"\x0c"), (30998, b"\x0a"))
    )
    assert out.report["result"] == "FAILURE"
    assert out.report["observation"]["first_error"] in {"timeout", "budget"}
    assert out.report["elapsed_ms"] <= 36000
    assert out.report["observation"]["elapsed_ms"] <= 35000


def test_read_error_auto_cleanup_is_bounded_and_never_erased(monkeypatch):
    out = case(
        monkeypatch,
        replies=(),
        close_ms=60000,
        plan=((3_539_990, b"\x0c"), (3_539_991, b"\x0a")),
    )
    assert out.report["result"] == "FAILURE"
    assert out.report["elapsed_ms"] <= 3_545_010 < 3_600_000
    assert not out.wire.closed and not out.report["cleanup_attested"]
    assert not out.session.cleanup_succeeded
    assert out.report["observation"]["first_error"] == "timeout"
    assert out.report["cleanup_started_ms"] == 3_540_000
