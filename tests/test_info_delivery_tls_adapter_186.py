"""D6 strict offline delivery proofs over D4's real persistent session."""

import asyncio
import copy
import json

import pytest

from custom_components.hoben.transport import (
    TransportEOF,
    TransportTlsError,
)
from scripts.info_delivery_tls_adapter import InvalidTlsAdapter, validate_adapter_report
from tests.info_delivery_worker_fixture_186 import run_worker_case
from tests.tls_read_candidate_186 import RESPONSE


def test_unproven_delivery_is_refused_before_new_v4(monkeypatch):
    result = asyncio.run(run_worker_case(monkeypatch, adapter=True))
    assert result.adapter_report["result"] == "FAILURE"
    assert result.wire.requests == 0


def test_separate_fixture_deliveries_correlate_in_same_memory_session(monkeypatch):
    result = asyncio.run(
        run_worker_case(
            monkeypatch,
            adapter=True,
            delivery_layout="isolated_fixture",
            replies=(),
            plan=((1000, b"\x0c"), (1100, b"\x0a"), (1200, RESPONSE)),
        )
    )
    assert result.adapter_report["result"] == "SUCCESS"
    assert result.session.verified_read_sequence == 1
    assert result.adapter_report["boundary_proven"] is False
    assert result.adapter_report["tls_provenance"] == "not_proven"


PLAN = ((1000, b"\x0c"), (1100, b"\x0a"), (1200, RESPONSE))


def case(monkeypatch, **options):
    settings = dict(
        adapter=True, delivery_layout="isolated_fixture", replies=(), plan=PLAN
    )
    settings.update(options)
    result = asyncio.run(run_worker_case(monkeypatch, **settings))
    report = result.adapter_report
    assert validate_adapter_report(report) == report
    assert len(json.dumps(report).encode()) <= 8192
    assert report["mode"] == "offline" and report["tls_provenance"] == "not_proven"
    assert report["process_reap"] == "not_proven" and not report["boundary_proven"]
    assert report["info_framing"] == "INCONCLUSIVE"
    assert (
        result.factory.calls
        == result.wire.connect_count
        == result.wire.close_count
        == 1
    )
    assert result.wire.active_reads == result.wire.active_tx == 0
    assert not result.session._operations and not result.session._tx_operations
    assert result.session._rx_task.done() and not result.clock._waiters
    assert result.wire._delivery_port is result.wire._ports_claim is None
    return result


@pytest.mark.parametrize(
    "layout", ["unknown", "fragmented_fixture", "coalesced_fixture"]
)
def test_ambiguous_delivery_never_authorizes_new_request(monkeypatch, layout):
    result = case(monkeypatch, delivery_layout=layout)
    assert result.adapter_report["result"] == "FAILURE"
    assert result.wire.requests == result.session.verified_read_sequence == 0
    assert result.adapter_report["first_error"] == "ambiguous_delivery"


@pytest.mark.parametrize("generation", [0, 2])
def test_generation_changed_before_request_is_refused(monkeypatch, generation):
    result = case(monkeypatch, delivery_generation=generation)
    assert result.adapter_report["result"] == "FAILURE"
    assert result.adapter_report["first_error"] == "generation_changed"
    assert result.wire.requests == 0


@pytest.mark.parametrize(
    "layout", ["unknown", "fragmented_fixture", "coalesced_fixture"]
)
def test_ambiguous_response_is_not_credited_even_if_codec_decodes(monkeypatch, layout):
    result = case(
        monkeypatch, delivery_layouts=("isolated_fixture", "isolated_fixture", layout)
    )
    assert result.wire.requests == 1
    assert result.adapter_report["result"] == "FAILURE"
    assert result.adapter_report["first_error"] == "ambiguous_delivery"


def test_generation_changed_on_response_cannot_credit_the_old_session(monkeypatch):
    out = case(monkeypatch, delivery_generations=(1, 1, 2))
    assert out.adapter_report["result"] == "FAILURE"
    assert out.adapter_report["first_error"] == "generation_changed"


def test_whole_coalesced_info_is_never_scanned_for_ping_or_response(monkeypatch):
    out = case(
        monkeypatch,
        plan=((1000, b"\x0c\x0a" + RESPONSE),),
        delivery_layout="coalesced_fixture",
    )
    assert out.adapter_report["result"] == "FAILURE"
    assert (
        out.wire.requests == out.wire.pongs == out.session.verified_read_sequence == 0
    )


def test_info_absent_still_waits_full_window_and_is_inconclusive(monkeypatch):
    out = case(monkeypatch, plan=(), close_ms=4999)
    assert out.adapter_report["result"] == "INCONCLUSIVE"
    assert out.adapter_report["delivery_count"] == 0
    assert out.adapter_report["worker"]["cleanup_started_ms"] == 3540000
    assert out.adapter_report["worker"]["elapsed_ms"] == 3544999
    assert out.wire.requests == 0


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": False},
        {"suffix": b"\x0c"},
        {"plan": ((1000, b"\x0c"), (1100, b"\x01"))},
        {"plan": ((1000, RESPONSE[:3]), (1100, b"\x0c"))},
        {"plan": ((1000, b"\x0c"), (1100, b"\x0a"))},
        {"plan": ((1000, b"\x0c"), (1100, b"\x0a"), (1200, TransportEOF()))},
        {
            "plan": (
                (1000, b"\x0c"),
                (1100, b"\x0a"),
                (1200, TransportTlsError("PRIVATE_D6_ERROR")),
            )
        },
        {
            "plan": (
                (1000, b"\x0c"),
                (1100, b"\x0a"),
                (1200, RESPONSE[:1] + b"\x00\x01" + RESPONSE[3:]),
            )
        },
        {"close_fails": True},
        {"close_ack": False},
        {"close_ms": 5001},
        {"cancel_at": 1101, "repeat_cancel": True},
        {"cancel_at": 1201, "repeat_cancel": True, "close_ms": 3000},
        {"replies": (RESPONSE,), "plan": ((1000, b"\x0c"), (1100, b"\x0a"))},
    ],
)
def test_errors_default_off_and_cleanup_missing_never_succeed(monkeypatch, options):
    out = case(monkeypatch, **options)
    assert out.adapter_report["result"] == "FAILURE"
    if not options.get("enabled", True):
        assert out.session._info_delivery_drop is None


def test_sealed_adapter_cannot_be_repaired_after_failure(monkeypatch):
    out = case(monkeypatch, delivery_layout="unknown")
    before = out.adapter_report
    assert out.ports.finish(out.report) == before
    with pytest.raises(InvalidTlsAdapter):
        out.ports.feed_memory(RESPONSE, layout="isolated_fixture")
    with pytest.raises(InvalidTlsAdapter):
        out.ports.bind(out.session, out.clock)


def test_protocols_cannot_substitute_a_network_factory_or_port(monkeypatch):
    from custom_components.hoben.v4_session import V4Session, V4SessionMode
    from scripts.info_delivery_memory import OfflineClock
    from scripts.info_delivery_scenario import InvalidInfoEvidence
    from scripts.info_delivery_tls_adapter import MemoryInfoPorts
    from scripts.info_delivery_worker import run_offline_worker

    calls = []

    def forbidden():
        calls.append(1)
        raise AssertionError("network_factory_must_not_run")

    async def check():
        loop = asyncio.get_running_loop()
        clock = OfflineClock(origin=0)
        monkeypatch.setattr(loop, "time", clock.loop_time)
        session = V4Session(
            user_guid="b" * 32,
            transport_factory=forbidden,
            mode=V4SessionMode.PERSISTENT,
        )
        with pytest.raises(InvalidTlsAdapter):
            MemoryInfoPorts(session=session, clock=clock)
        with pytest.raises(InvalidInfoEvidence):
            await run_offline_worker(session=session, clock=clock, _tls_ports=object())

    asyncio.run(check())
    assert calls == []


def test_scalar_report_forgery_and_private_data_are_rejected(monkeypatch, caplog):
    out = case(monkeypatch)
    r = out.adapter_report
    for key in r:
        changed = copy.deepcopy(r)
        del changed[key]
        with pytest.raises(InvalidTlsAdapter):
            validate_adapter_report(changed)
    for key, value in (
        ("boundary_proven", True),
        ("tls_provenance", "proven"),
        ("mode", "live"),
        ("cleanup_attested", False),
        ("delivery_count", 0),
        ("read_permits", 0),
        ("verified_reads", True),
        ("first_error", "PRIVATE_D6"),
        ("raw_rx", "PRIVATE_D6"),
        ("process_reap", "proven"),
    ):
        changed = {**r, key: value}
        with pytest.raises(InvalidTlsAdapter):
            validate_adapter_report(changed)
    changed = copy.deepcopy(r)
    changed["delivery_count"] = changed["delivery_bytes"] = changed[
        "max_delivery_bytes"
    ] = 0
    changed["layouts"] = dict.fromkeys(changed["layouts"], 0)
    with pytest.raises(InvalidTlsAdapter):
        validate_adapter_report(changed)
    text = json.dumps(r) + caplog.text
    assert "PRIVATE_D6" not in text and "b" * 32 not in text
    assert "Traceback" not in text


def test_regular_isolated_pings_do_not_shorten_no_info_window(monkeypatch):
    plan = tuple((t * 1000, b"\x0a") for t in range(10, 3540, 60))
    out = case(monkeypatch, plan=plan)
    assert out.adapter_report["result"] == "INCONCLUSIVE"
    assert out.adapter_report["delivery_count"] == len(plan)
    assert out.adapter_report["worker"]["cleanup_started_ms"] == 3540000
    assert out.wire.pongs == len(plan) and out.wire.requests == 0


@pytest.mark.parametrize("at", [3_539_990, 3_540_000, 3_540_001])
def test_global_window_is_not_rearmed_by_adapter_receipts(monkeypatch, at):
    out = case(monkeypatch, plan=((at, b"\x0c"), (at + 1, b"\x0a"), (at + 2, RESPONSE)))
    assert (out.adapter_report["result"] == "SUCCESS") == (at < 3_540_000)
    assert out.adapter_report["worker"]["cleanup_deadline_ms"] <= 3600000
    if at >= 3540000:
        assert out.wire.requests == 0


def test_native_error_cannot_be_erased_by_a_good_D4_report(monkeypatch):
    from custom_components.hoben.exceptions import HobenTimeoutError

    out = asyncio.run(
        run_worker_case(
            monkeypatch,
            adapter=True,
            finalize_adapter=False,
            delivery_layout="isolated_fixture",
            replies=(),
            plan=PLAN,
        )
    )
    assert out.report["result"] == "SUCCESS"
    out.session._rx_error = HobenTimeoutError()
    r = out.ports.finish(out.report)
    assert r["result"] == "FAILURE" and r["first_error"] == "worker_failed"
    assert r["verified_reads"] == 1  # A previous read is not terminal success.


def test_declaration_without_receive_and_wrong_owner_cannot_authorize_V4(monkeypatch):
    from custom_components.hoben.v4_session import V4Session, V4SessionMode
    from scripts.info_delivery_memory import (
        MemoryFactory,
        MemoryTransport,
        OfflineClock,
    )
    from scripts.info_delivery_tls_adapter import MemoryInfoPorts
    from tests.test_v4_session import opened_prefix

    async def check():
        loop = asyncio.get_running_loop()
        c = OfflineClock(origin=0)
        monkeypatch.setattr(loop, "time", c.loop_time)
        wire = MemoryTransport(opening=opened_prefix())
        factory = MemoryFactory(wire)
        session = V4Session(
            user_guid="b" * 32, transport_factory=factory, mode=V4SessionMode.PERSISTENT
        )
        ports = MemoryInfoPorts(session=session, clock=c)
        with pytest.raises(InvalidTlsAdapter):
            MemoryInfoPorts(session=session, clock=c)  # Already claimed.
        ports.feed_memory(b"\x0c", layout="isolated_fixture")
        assert not ports.allow_v4_read() and ports.failed
        assert ports._count == 0 and factory.calls == 0
        with pytest.raises(InvalidTlsAdapter):
            ports.bind(object(), c)
        assert repr(ports) == "MemoryInfoPorts()"

    asyncio.run(check())


def test_no_orphan_helpers_or_second_transport_with_adapter(monkeypatch):
    async def check():
        before = asyncio.all_tasks()
        out = await run_worker_case(
            monkeypatch,
            adapter=True,
            delivery_layout="isolated_fixture",
            replies=(),
            plan=PLAN,
        )
        assert out.adapter_report["result"] == "SUCCESS"
        assert asyncio.all_tasks() == before
        assert out.session.cleanup_succeeded and out.factory.calls == 1

    asyncio.run(check())


def test_D1_rejects_adapter_as_live_and_accepts_only_nested_C_offline(monkeypatch):
    import subprocess

    from tests.test_info_delivery_manual_report_186 import node_reports

    out = case(monkeypatch)
    r = out.adapter_report
    assert node_reports([r["worker"]["observation"]])[0]["accepted"]
    assert not node_reports([r])[0]["accepted"]
    driver = """
const api=require('./.github/scripts/info-delivery-manual-report.cjs');
const r=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
try {api.validateForLivePublication(r);process.exit(2);}
catch(e){if(e.message!=='info_live_provenance_not_proven')process.exit(3);}
"""
    proc = subprocess.run(
        ["node", "-e", driver],
        input=json.dumps(r),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert proc.returncode == 0


def test_a_report_from_another_worker_cannot_hide_observed_info(monkeypatch):
    info = asyncio.run(
        run_worker_case(
            monkeypatch,
            adapter=True,
            finalize_adapter=False,
            delivery_layout="isolated_fixture",
            replies=(),
            plan=PLAN,
        )
    )
    absent = case(monkeypatch, plan=())
    r = info.ports.finish(absent.report)
    assert r["result"] == "FAILURE" and r["first_error"] == "correlation_unproven"


def test_retained_or_unverified_value_is_not_a_fresh_sample(monkeypatch):
    out = asyncio.run(
        run_worker_case(
            monkeypatch,
            adapter=True,
            finalize_adapter=False,
            delivery_layout="isolated_fixture",
            replies=(),
            plan=PLAN,
        )
    )
    out.session._verified_read_sequence = 0
    r = out.ports.finish(out.report)
    assert r["result"] == "FAILURE" and r["read_permits"] == 1
    assert r["verified_reads"] == 0


def test_fragmented_MBAP_is_refused_even_with_wrong_fixture_declaration(monkeypatch):
    out = case(
        monkeypatch,
        plan=(
            (1000, b"\x0c"),
            (1100, b"\x0a"),
            (1200, RESPONSE[:7]),
            (1300, RESPONSE[7:]),
        ),
    )
    assert out.adapter_report["result"] == "FAILURE"
    assert out.adapter_report["first_error"] == "partial_frame"


def test_opaque_fixture_candidate_never_exports_private_bytes(monkeypatch, caplog):
    out = case(
        monkeypatch,
        plan=((1000, b"\x0cPRIVATE_D6_PAYLOAD"), (1100, b"\x0a"), (1200, RESPONSE)),
    )
    assert out.adapter_report["result"] == "SUCCESS"
    assert "PRIVATE_D6_PAYLOAD" not in json.dumps(out.adapter_report) + caplog.text
    assert out.adapter_report["boundary_proven"] is False


def test_adapter_has_no_network_supplier_CLI_or_capability_constructor():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("scripts/info_delivery_tls_adapter.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(
                x.name.split(".")[0] in {"socket", "ssl", "http", "urllib"}
                for x in node.names
            )
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            assert name not in {
                "connect",
                "open_connection",
                "create_connection",
                "V4Session",
                "_InfoDeliveryDropExperiment",
            }
