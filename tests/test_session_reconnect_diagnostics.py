"""Synthetic diagnostics, never a reconstruction of the real failed run."""

import asyncio
import copy
import json
import subprocess

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.v4_experiment import (
    RECONNECT_DIAGNOSTIC_MESSAGES,
    ExperimentalV4Framer,
    Session300,
    Session300BudgetError,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from scripts.session_suite import (
    SECOND_DIAGNOSTIC_KEYS,
    observe_suite,
    validate_suite,
)
from tests.test_session_300_probe import PROOF
from tests.test_session_300_runtime import Stream, response
from tests.test_session_suite import Harness, run_harness


class DiagnosticHarness(Harness):
    """Three successful reads and a rejected head at simulated T+181 s.

    Synthetic Ping every 36 s: three Pong, then two inhibited after T+120.
    A two-second scheduler tick spans T+180, before any fourth read is started.
    These choices exercise the code path; they explain no real server behavior.
    """

    def __init__(self, rejected=b"\xff"):
        super().__init__("no_disconnect")
        self.rejected = rejected
        self.sent = False

    def make(self, budget, policy):
        life = super().make(budget, policy)
        if policy is not None:
            self.next_ping = self.now + 36
        return life

    async def sleep(self, delay):
        if self.policy is None:
            return await super().sleep(delay)
        elapsed = self.now - self.policy.first_opened_at
        self.now += 2 if elapsed == 179 else delay
        if self.now >= self.next_ping:
            self.second_streams[-1].queue.put_nowait(b"\x0a")
            self.next_ping += 36
        await self.spin()
        if self.now - self.policy.first_opened_at >= 181 and not self.sent:
            self.sent = True
            self.second_streams[-1].queue.put_nowait(self.rejected)
        await self.spin()


async def diagnostic_report(rejected=b"\xff"):
    h = DiagnosticHarness(rejected)
    report = await observe_suite(h.make, PROOF, clock=h.clock, sleep=h.sleep)
    h.assert_closed()
    return h, report


@pytest.mark.parametrize(
    "rejected,phase,message",
    [
        (b"\x05", "message_classification", "close_client"),
        (b"\x1b", "message_classification", "data_updated"),
        (b"\x00", "message_classification", "other_known"),
        (b"\xff", "message_classification", "unknown"),
        (b"\x19", "message_classification", "unknown"),
        (bytes.fromhex("0e00010000ffff"), "frame_boundary", "ambiguous"),
        (response(), "request_correlation", "data_response"),
    ],
)
def test_real_shared_owners_report_existing_refusals_after_three_reads(
    rejected, phase, message
):
    h, report = asyncio.run(diagnostic_report(rejected))
    second = report["session_reconnect_no_pong"]
    assert report["schema"] == second["schema"] == 2
    assert report["session_300"]["schema"] == 1
    assert report["result"] == "not_successful"
    assert second["result"] == "inconclusive"
    assert second["terminal"] == second["failure_category"] == "protocol"
    assert (second["failure_phase"], second["message_category"]) == (phase, message)
    assert second["duration_ms"] == 181000
    assert second["reads"] == second["reads_ok"] == second["responses"] == 3
    assert second["read_slot"] == 3 and second["reads_failed"] == 0
    assert (second["pings"], second["pongs"], second["pongs_suppressed"]) == (5, 3, 2)
    assert second["opens"] == 1 and second["reconnections"] == 0
    assert second["peer_eofs"] == second["eofs_after_suppression"] == 0
    assert second["eof_after_threshold_ms"] is None
    assert second["stable_ms"] == second["recovery_generation"] == 0
    assert second["recovery_reads_ok"] == second["recovery_pongs"] == 0
    assert second["boundary_proven"] is False
    assert len(h.second_streams) == 1


def test_all_rejected_heads_keep_refusal_and_historical_diagnostics():
    known = set(range(25)) | set(range(26, 49)) | set(range(80, 89)) | {96}
    for discriminator in set(range(256)) - {10, 14}:
        expected = (
            "close_client"
            if discriminator == 5
            else "data_updated"
            if discriminator == 27
            else "other_known"
            if discriminator in known
            else "unknown"
        )
        for kind, category in [(Session300, "unknown"), (SessionReconnect, expected)]:
            budget = kind()
            framer = ExperimentalV4Framer(diagnostic=budget)
            with pytest.raises(HobenProtocolError):
                # No subcode, payload, trailing Ping or resynchronization is read.
                framer.feed(bytes([discriminator]) + b"private\x0a", object())
            assert len(framer._buffer) == 1
            assert budget.failure == ("message_classification", "protocol", category)
            assert budget.pings == budget.pongs == budget.responses == 0


def test_correlated_invalid_response_keeps_response_validation(monkeypatch):
    original = Stream.write
    h = Harness("no_disconnect")

    async def write(stream, payload):
        if h.policy is not None and payload[0] == 13 and h.budget.requests == 3:
            stream.chunks = [b"\x0e\x00\x01" + response()[3:]]
        await original(stream, payload)

    monkeypatch.setattr(Stream, "write", write)

    async def scenario():
        r = await observe_suite(h.make, PROOF, clock=h.clock, sleep=h.sleep)
        h.assert_closed()
        s = r["session_reconnect_no_pong"]
        assert s["terminal"] == "protocol"
        assert s["failure_phase"] == "response_validation"
        assert s["message_category"] == "data_response"
        assert s["reads_ok"] == 2 and s["reads_failed"] == 1
        assert s["peer_eofs"] == s["reconnections"] == 0

    asyncio.run(scenario())


def test_actual_rx_budget_refusal_remains_bounded_and_does_not_forge_eof():
    _, report = asyncio.run(diagnostic_report(b"x" * 4097))
    s = report["session_reconnect_no_pong"]
    assert s["terminal"] == s["failure_category"] == "budget"
    assert s["failure_phase"] == "tls_read"
    assert s["message_category"] == "unclassified"
    assert s["reads_ok"] == 3 and s["rx_bytes_total"] <= 1048576
    assert s["rx_chunks_total"] <= s["rx_bytes_total"]
    assert s["peer_eofs"] == s["reconnections"] == 0


def test_secondary_teardown_cannot_replace_causal_protocol_diagnostic(monkeypatch):
    close = V4Lifecycle.close

    async def secondary_failure(life):
        await close(life)
        if life in h.lives[1:]:
            h.budget.note_failure("tls_read", "transport")
            raise RuntimeError("synthetic-private-exception")

    h = DiagnosticHarness(b"\x05")
    monkeypatch.setattr(V4Lifecycle, "close", secondary_failure)

    async def scenario():
        r = await observe_suite(h.make, PROOF, clock=h.clock, sleep=h.sleep)
        h.assert_closed()
        s = r["session_reconnect_no_pong"]
        assert s["result"] == "interrupted" and s["terminal"] == "closed"
        assert (s["failure_phase"], s["failure_category"], s["message_category"]) == (
            "message_classification",
            "protocol",
            "close_client",
        )
        assert "synthetic-private" not in json.dumps(r)

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["opening", "scheduled_read", "lifecycle_transition"])
@pytest.mark.parametrize(
    "error,terminal",
    [(TimeoutError, "timeout"), (Session300BudgetError, "budget")],
)
def test_fallbacks_use_closed_phase_and_category_without_exception_text(
    monkeypatch, stage, error, terminal
):
    h = Harness("no_disconnect")
    original_connect, original_read = V4Lifecycle.connect, V4Lifecycle.request_v4_data

    async def connect(life):
        if h.policy is not None and stage == "opening":
            raise error()
        return await original_connect(life)

    async def read(life, **kwargs):
        if h.policy is not None and stage == "scheduled_read":
            raise error()
        return await original_read(life, **kwargs)

    async def sleep(delay):
        if h.policy is not None and stage == "lifecycle_transition":
            raise error()
        await h.sleep(delay)

    monkeypatch.setattr(V4Lifecycle, "connect", connect)
    monkeypatch.setattr(V4Lifecycle, "request_v4_data", read)

    async def scenario():
        r = await observe_suite(h.make, PROOF, clock=h.clock, sleep=sleep)
        # The synthetic opening refusal acquired no stream or owner task.
        if stage == "opening":
            h.lives.pop()
        h.assert_closed()
        s = r["session_reconnect_no_pong"]
        assert s["terminal"] == s["failure_category"] == terminal
        assert s["failure_phase"] == stage and s["message_category"] == "unclassified"
        assert s["peer_eofs"] == s["reconnections"] == 0
        assert "synthetic-private" not in json.dumps(r)

    asyncio.run(scenario())


def legacy(report):
    """Explicit historical shape: no diagnostic invented for a v1 report."""
    r = copy.deepcopy(report)
    r["schema"] = r["session_reconnect_no_pong"]["schema"] = 1
    for key in SECOND_DIAGNOSTIC_KEYS:
        del r["session_reconnect_no_pong"][key]
    return r


def test_python_node_versioned_diagnostics_are_closed_and_legacy_not_backfilled():
    good = asyncio.run(run_harness())[1]
    bad = asyncio.run(diagnostic_report())[1]
    skipped = asyncio.run(run_harness("first_invalid"))[1]
    valid = [good, bad, skipped, legacy(good), legacy(bad), legacy(skipped)]
    for phase, messages in RECONNECT_DIAGNOSTIC_MESSAGES.items():
        if phase == "none":
            continue
        for message in messages:
            changed = copy.deepcopy(bad)
            category = (
                "closed"
                if phase == "teardown"
                else "transport"
                if phase == "tls_read"
                else "protocol"
            )
            changed["session_reconnect_no_pong"].update(
                failure_phase=phase, failure_category=category, message_category=message
            )
            if phase == "teardown":
                changed["session_reconnect_no_pong"].update(
                    terminal="closed", result="interrupted"
                )
            valid.append(changed)
    cases = copy.deepcopy(valid)
    for source in (good, bad, skipped, legacy(bad)):
        for key in source["session_reconnect_no_pong"]:
            changed = copy.deepcopy(source)
            del changed["session_reconnect_no_pong"][key]
            cases.append(changed)
    for key in SECOND_DIAGNOSTIC_KEYS:
        for value in (
            None,
            True,
            [],
            {},
            1.5,
            "private/path\nexception",
            "05",
            1048577,
        ):
            changed = copy.deepcopy(bad)
            changed["session_reconnect_no_pong"][key] = value
            cases.append(changed)
    for source, change in [
        (legacy(bad), {"failure_phase": "unclassified"}),
        (bad, {"schema": 1}),
        (bad, {"schema": 3}),
        (bad, {"failure_phase": "none"}),
        (bad, {"failure_category": "verified"}),
        (bad, {"message_category": "ping"}),
        (bad, {"read_slot": 4}),
        (skipped, {"failure_category": "protocol"}),
        (bad, {"raw_rx": "private"}),
        (bad, {"payload": "private"}),
        (bad, {"exception": "private"}),
        (bad, {"registers": [17]}),
        (bad, {"guid": "private"}),
        (bad, {"temperature": 17}),
        (bad, {"merge_sha": "c" * 40}),
        (bad, {"run_id": True}),
        (bad, {"run_attempt": 2}),
    ]:
        changed = copy.deepcopy(source)
        changed["session_reconnect_no_pong"].update(change)
        cases.append(changed)
    for change in ({"schema": 1}, {"schema": True}, {"result": "success"}):
        cases.append(bad | change)
    expected = [True] * len(valid) + [False] * (len(cases) - len(valid))
    for report, allowed in zip(cases, expected):
        if allowed:
            assert validate_suite(report, PROOF) == report
        else:
            with pytest.raises((ValueError, TypeError)):
                validate_suite(report, PROOF)
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const api=require('./.github/scripts/session-suite-report.cjs');
const [cases,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(r=>{
  try {const v=api.validate(r,p);
    return JSON.stringify(v)===JSON.stringify(api.validate(v,p));}
  catch(_){return false;}
})));
""",
        ],
        input=json.dumps([cases, PROOF]),
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    assert json.loads(result.stdout) == expected and result.stderr == ""
    historical = legacy(bad)
    assert not (
        SECOND_DIAGNOSTIC_KEYS
        & set(validate_suite(historical, PROOF)["session_reconnect_no_pong"])
    )
    assert historical["result"] == "not_successful"
