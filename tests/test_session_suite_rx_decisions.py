"""L6ter contract proofs at real owner decisions; simulated TLS/time only.

No producer or runtime instrumentation is installed. These TEST wrappers record
scalar facts after original owner methods and advance the actual injected clock
between delivery and parsing. Projection never edits an observed timestamp.
"""

import asyncio
import copy
import json
from typing import NamedTuple

import pytest

from custom_components.hoben.exceptions import HobenError, HobenProtocolError
from custom_components.hoben.v4_experiment import (
    BudgetTransport,
    ExperimentalV4Framer,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import LifecycleExhaustedError
from custom_components.hoben.v4_session import SessionState, V4Session
from scripts.session_suite import validate_suite
from tests.test_session_300_runtime import response
from tests.test_session_no_pong import until
from tests.test_session_suite_v3 import CORPUS, PROOF, node, workflow_result
from tests.test_v4_lifecycle_quarantine import clean, connected


class Receipt(NamedTuple):
    generation: int
    eof: int
    consumed: int


class Facts:
    """Fixed scalar test facts. No bytes, identities or returned registers."""

    def __init__(self, monkeypatch, budget, pong, now):
        self.budget, self.pong, self.now = budget, pong, now
        self.t0 = self.ms(budget.accepted_at)
        self.cause = self.inhibition = self.receipt = self.cleanup = None
        self.accepted = self.generation = self.first_pong = self.first_read = None
        self.recovery_reads = self.reads_ok = self.recovery_pongs = 0
        self.window_offset = self.first_rx = self.last_rx = self.eof = None
        self.window_bytes = self.window_chunks = 0
        self.rejection_offset = self.rejection_size = None
        self.delivery_start = self.delivery_size = 0
        self.delay_next = 0
        original_read = BudgetTransport.read
        original_failure = SessionReconnect.note_failure
        original_consume = V4Session._consume_quarantine
        original_cleanup = V4Session._cleanup_quarantine
        original_connect = V4Session.connect
        original_response = V4Session._handle_delimited_data_response
        original_ping = V4Session._handle_delimited_ping

        async def delivered(transport, *args, **kwargs):
            data = await original_read(transport, *args, **kwargs)
            if transport._budget is budget:
                at = self.at()
                self.delivery_size = len(data)
                self.delivery_start = budget.rx_bytes - len(data)
                self.arm(self.delivery_start)
                if data and self.window_offset is not None:
                    if self.first_rx is None:
                        self.first_rx = at
                    self.last_rx = at
                    self.window_bytes += len(data)
                    self.window_chunks += 1
                if not data and self.eof is None:
                    self.eof = at
                if data and self.delay_next:
                    now[0] += self.delay_next / 1000
                    self.delay_next = 0
                    self.arm()  # Pre150 bytes stay outside the RX window.
            return data

        def failed(owner, phase, category, message="unclassified"):
            original_failure(owner, phase, category, message)
            if owner is budget and self.cause is None:
                self.cause = (self.at(), phase, category, message, budget.requests)
                # All rejection tests put the rejected head first in this
                # synthetic delivery; a coalesced suffix is counted, not parsed.
                self.rejection_offset = self.delivery_start
                self.rejection_size = 1

        def consumed(session, owner, generation):
            permit = original_consume(session, owner, generation)
            if session._experiment is budget:
                self.receipt = Receipt(
                    generation,
                    session._quarantine_observation.at_ms - self.t0,
                    session._quarantine_checked_at - self.t0,
                )
            return permit

        async def cleaned(session, owner, permit):
            await original_cleanup(session, owner, permit)
            if session._experiment is budget:
                self.cleanup = self.at()

        async def accepted(session):
            await original_connect(session)
            if session._experiment is budget and budget.opens > 1:
                self.accepted = self.ms(budget.accepted_at) - self.t0
                self.generation = budget.connected_generation

        async def validated(session, event):
            await original_response(session, event)
            if session._experiment is budget:
                self.reads_ok += 1
                if session._experiment_generation == self.generation:
                    self.recovery_reads += 1
                    if self.first_read is None:
                        self.first_read = self.at()

        async def ping(session, event):
            sent = await original_ping(session, event)
            if session._experiment is budget:
                if not sent and self.inhibition is None:
                    self.inhibition = self.at()
                if sent and session._experiment_generation == self.generation:
                    self.recovery_pongs += 1
                    if self.first_pong is None:
                        self.first_pong = self.at()
            return sent

        monkeypatch.setattr(BudgetTransport, "read", delivered)
        monkeypatch.setattr(SessionReconnect, "note_failure", failed)
        monkeypatch.setattr(V4Session, "_consume_quarantine", consumed)
        monkeypatch.setattr(V4Session, "_cleanup_quarantine", cleaned)
        monkeypatch.setattr(V4Session, "connect", accepted)
        monkeypatch.setattr(V4Session, "_handle_delimited_data_response", validated)
        monkeypatch.setattr(V4Session, "_handle_delimited_ping", ping)

    @staticmethod
    def ms(seconds):
        return V4Session._quarantine_time(seconds)

    def at(self):
        return self.ms(self.now[0]) - self.t0

    def arm(self, offset=None):
        if self.at() >= 150000 and self.window_offset is None:
            self.window_offset = self.budget.rx_bytes if offset is None else offset

    def report(self, cap, end, *, stopped=False, prior_refused=False):
        """Only the unchanged first-scenario envelope is a synthetic reference."""
        r = copy.deepcopy(CORPUS["reports"]["not_run"])
        r["session_300"] = copy.deepcopy(CORPUS["reports"]["success"]["session_300"])
        r.update(result="not_successful", duration_ms=300000 + end)
        s = r["session_reconnect_no_pong"]
        b, p = self.budget, self.pong
        s.update(
            result="interrupted" if stopped else "inconclusive",
            terminal="stability_lost" if stopped else "reopen_failed",
            duration_ms=end,
            opens=b.opens,
            reconnections=b.opens - 1,
            pings=b.pings,
            pongs=b.pongs,
            reads=b.requests,
            responses=b.responses,
            reads_ok=self.reads_ok,
            reads_failed=b.requests - self.reads_ok,
            rx_bytes_total=b.rx_bytes,
            rx_chunks_total=b.rx_chunks,
            pongs_suppressed=p.suppressed,
            peer_eofs=p.peer_eofs,
            eofs_after_suppression=p.peer_eofs_after_suppression,
            recovery_generation=self.generation or 0,
            recovery_reads_ok=self.recovery_reads,
            recovery_pongs=self.recovery_pongs,
            stable_ms=0 if self.accepted is None else end - self.accepted,
            causal_ms=self.cause[0],
            failure_phase=self.cause[1],
            failure_category=self.cause[2],
            message_category=self.cause[3],
            read_slot=self.cause[4],
        )
        observation, process, suite = cap._initial._deadlines
        s["timing"].update(
            t0_observed=True,
            functional_end_ms=end,
            observation_deadline_ms=observation - self.t0,
            process_deadline_ms=process - self.t0,
            suite_deadline_ms=suite - self.t0,
            inhibition_ms=self.inhibition,
        )
        s["quarantine"].update(
            outcome="consumed",
            entered_ms=self.cause[0],
            eof_ms=self.receipt.eof,
            consumed_ms=self.receipt.consumed,
            cleanup_ms=self.cleanup,
            origin_generation=self.receipt.generation,
            eof_origin="transport_read",
            receipt="valid_at_consumption",
            accepted_ms=self.accepted,
            accepted_generation=self.generation,
            stop="cancel_after_consumption" if stopped else "none",
            stop_ms=end if stopped else None,
        )
        if self.accepted is not None:
            s["stability"].update(
                start_ms=self.accepted,
                end_ms=end,
                generation=self.generation,
                first_pong_ms=self.first_pong,
                first_read_ok_ms=self.first_read,
                interrupted=True,
            )
        if self.window_offset is not None:
            has_rejection = self.cause[0] >= 150000
            s["rx_diagnostic"].update(
                observed=True,
                start_ms=150000,
                end_ms=end,
                bytes=self.window_bytes,
                chunks=self.window_chunks,
                start_offset=self.window_offset,
                end_offset=self.window_offset + self.window_bytes,
                first_rx_ms=self.first_rx,
                last_rx_ms=self.last_rx,
                rejection_ms=self.cause[0] if has_rejection else None,
                rejection_offset=self.rejection_offset if has_rejection else None,
                rejection_size=self.rejection_size if has_rejection else None,
                framer="refused" if has_rejection or prior_refused else "empty",
                phase=self.cause[1] if has_rejection else "none",
                category=self.cause[2] if has_rejection else "none",
                message=self.cause[3] if has_rejection else "unclassified",
                eof_ms=self.eof
                if self.eof is not None and self.eof >= 150000
                else None,
            )
        return r


def assert_both_and_failure(report):
    assert validate_suite(report, PROOF) == report
    actual = node(
        """
const [r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require('./.github/scripts/session-suite-report.cjs');
process.stdout.write(JSON.stringify({r:api.validate(r,p),
 completed:api.completed(r,p,'success','success')}));
""",
        [report, PROOF],
    )
    assert actual == {"r": report, "completed": False}
    statuses = workflow_result(report)
    assert [r["state"] for r in statuses] == ["failure"] * 5
    assert "synthetic-private" not in json.dumps(statuses)


@pytest.mark.parametrize(
    "delivery_ms,delay_ms",
    [
        (151000, 0),
        (151000, 1),
        (149999, 0),
        (149999, 1),
        (149999, 2),
        (150000, 0),
        (150000, 1),
        (150001, 0),
    ],
)
@pytest.mark.parametrize("suffix", [b"", b"\x7f\x0a" + response()])
def test_delivery_then_rejection_real_owners_failed_reopens(
    monkeypatch, delivery_ms, delay_ms, suffix
):
    async def scenario():
        life, f, backoff, budget, pong, now, cap = await connected()
        facts = Facts(monkeypatch, budget, pong, now)
        now[0] = 130
        f.streams[0].queue.put_nowait(b"\x0a")
        await until(lambda: pong.suppressed == 1)
        now[0] = (facts.t0 + delivery_ms) / 1000
        facts.delay_next = delay_ms
        f.streams[0].queue.put_nowait(b"\x05" + suffix)
        await until(lambda: life.state is SessionState.QUARANTINED)
        assert facts.cause[0] == delivery_ms + delay_ms
        assert cap._origin._quarantine_observation.at_ms - facts.t0 == facts.cause[0]
        now[0] = 170
        f.streams[0].queue.put_nowait(b"")
        assert await backoff.entered.get() == 1
        assert facts.receipt is not None
        f.fail_open = {1, 2}
        now[0] = 171
        backoff.release.put_nowait(None)
        assert await backoff.entered.get() == 2
        now[0] = 173
        backoff.release.put_nowait(None)
        with pytest.raises(LifecycleExhaustedError):
            await life.wait_stopped()
        end = facts.at()
        report = facts.report(cap, end, prior_refused=facts.cause[0] < 150000)
        d = report["session_reconnect_no_pong"]["rx_diagnostic"]
        if delivery_ms < 150000:
            assert d["bytes"] == d["chunks"] == 0 and d["first_rx_ms"] is None
            assert d["start_offset"] == d["end_offset"]
            if facts.cause[0] < 150000:
                assert d["rejection_ms"] is d["rejection_offset"] is None
                assert d["framer"] == "refused" and cap._origin._quarantine_latched
            else:
                assert d["rejection_offset"] < d["start_offset"]
        else:
            assert d["last_rx_ms"] == delivery_ms
            assert d["bytes"] == len(suffix) + 1
        assert d["end_offset"] == budget.rx_bytes  # Empty EOF/reopens add no bytes.
        await clean(life, f)
        return report

    assert_both_and_failure(asyncio.run(scenario()))


@pytest.mark.parametrize("split", range(1, 7))
def test_fragmented_pre150_prefix_rejected_after_final_delivery(monkeypatch, split):
    async def scenario():
        life, f, _, budget, pong, now, cap = await connected()
        facts = Facts(monkeypatch, budget, pong, now)
        feed = ExperimentalV4Framer.feed

        def framing(framer, data, exchange):
            start = budget.rx_bytes - len(data) - len(framer._buffer)
            try:
                return feed(framer, data, exchange)
            except HobenProtocolError:
                # Actual retained prefix and failing decision, not a new scan.
                facts.rejection_offset = start
                facts.rejection_size = len(framer._buffer)
                raise

        monkeypatch.setattr(ExperimentalV4Framer, "feed", framing)
        now[0] = 130
        f.streams[0].queue.put_nowait(b"\x0a")
        await until(lambda: pong.suppressed == 1)
        invalid_header = b"\x0e\xff\xff\x00\x01\x00\x03"
        now[0] = 159.999
        f.streams[0].queue.put_nowait(invalid_header[:split])
        await until(lambda: budget.rx_bytes == 49 + split)
        now[0] = 161
        facts.delay_next = 1
        f.streams[0].queue.put_nowait(invalid_header[split:])
        with pytest.raises(HobenError):
            await life.wait_stopped()
        end = facts.at()
        report = copy.deepcopy(CORPUS["reports"]["early"])
        report.update(result="not_successful", duration_ms=300000 + end)
        s = report["session_reconnect_no_pong"]
        s.update(
            duration_ms=end,
            result="inconclusive",
            terminal="protocol",
            opens=budget.opens,
            reconnections=0,
            pings=budget.pings,
            pongs=budget.pongs,
            reads=0,
            reads_ok=0,
            reads_failed=0,
            responses=0,
            read_slot=0,
            rx_bytes_total=budget.rx_bytes,
            rx_chunks_total=budget.rx_chunks,
            pongs_suppressed=pong.suppressed,
            failure_phase=facts.cause[1],
            failure_category=facts.cause[2],
            message_category=facts.cause[3],
            causal_ms=facts.cause[0],
        )
        observation, process, suite = cap._initial._deadlines
        s["timing"].update(
            t0_observed=True,
            functional_end_ms=end,
            observation_deadline_ms=observation - facts.t0,
            process_deadline_ms=process - facts.t0,
            suite_deadline_ms=suite - facts.t0,
            inhibition_ms=facts.inhibition,
        )
        s["rx_diagnostic"].update(
            observed=True,
            start_ms=150000,
            end_ms=end,
            first_rx_ms=facts.first_rx,
            last_rx_ms=facts.last_rx,
            bytes=facts.window_bytes,
            chunks=facts.window_chunks,
            start_offset=facts.window_offset,
            end_offset=budget.rx_bytes,
            rejection_ms=facts.cause[0],
            rejection_offset=facts.rejection_offset,
            rejection_size=facts.rejection_size,
            framer="refused",
            phase=facts.cause[1],
            category=facts.cause[2],
            message=facts.cause[3],
        )
        assert s["rx_diagnostic"]["last_rx_ms"] == 151000 < facts.cause[0] == 151001
        assert facts.rejection_offset == 49 < facts.window_offset
        assert facts.rejection_size == 7 and facts.window_bytes == 7 - split
        await clean(life, f)
        return report

    assert_both_and_failure(asyncio.run(scenario()))


@pytest.mark.parametrize(
    "before150,two_reads", [(True, False), (False, False), (False, True)]
)
def test_correlated_validation_after_delivery_and_request_cadence(
    monkeypatch, before150, two_reads
):
    async def scenario():
        life, f, backoff, budget, pong, now, cap = await connected()
        facts = Facts(monkeypatch, budget, pong, now)
        now[0] = 130
        f.streams[0].queue.put_nowait(b"\x0a")
        await until(lambda: pong.suppressed == 1)
        now[0] = 131 if before150 else 161
        f.streams[0].queue.put_nowait(b"\x05")
        await until(lambda: life.state is SessionState.QUARANTINED)
        now[0] = 140 if before150 else 170
        f.streams[0].queue.put_nowait(b"")
        assert await backoff.entered.get() == 1
        now[0] = 142 if before150 else 172
        backoff.release.put_nowait(None)
        await life.wait_connected()
        f.streams[1].queue.put_nowait(b"\x0a")
        await until(lambda: facts.recovery_pongs == 1)
        request_times = []
        for index in range(2 if two_reads else 1):
            now[0] = (159.999 if before150 else 190) + index * 60
            request_times.append(now[0])
            read = asyncio.create_task(life.request_v4_data())
            await until(
                lambda: budget.requests == index + 1 and not f.sessions[1]._tx_in_flight
            )
            facts.delay_next = (2 if before150 else 1) if index == 0 else 0
            f.streams[1].queue.put_nowait(response())
            await read  # Registers deliberately discarded.
        end = facts.at()
        assert all(b - a >= 60 for a, b in zip(request_times, request_times[1:]))
        await life.close()  # A real public stop, recorded at this actual clock.
        report = facts.report(cap, end, stopped=True)
        d = report["session_reconnect_no_pong"]["rx_diagnostic"]
        if before150:
            assert d["bytes"] == 0 and d["first_rx_ms"] is d["last_rx_ms"] is None
        elif two_reads:
            assert (
                facts.first_read + 60000 > end
            )  # Validation gaps are not request gaps.
        else:
            assert d["last_rx_ms"] < facts.first_read
        await clean(life, f)
        return report

    assert_both_and_failure(asyncio.run(scenario()))
