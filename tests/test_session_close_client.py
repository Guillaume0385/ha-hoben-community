"""Owner-authorized experimental two-byte CloseClient, entirely offline."""

import asyncio
import copy
import json

import pytest

from custom_components.hoben.exceptions import HobenProtocolError, HobenTransportError
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_experiment import (
    ExperimentalCloseClientError,
    ExperimentalV4Framer,
    Session300,
    SessionReconnect,
)
from custom_components.hoben.v4_lifecycle import V4Lifecycle
from custom_components.hoben.v4_no_pong import NoPongAfter120
from custom_components.hoben.v4_session import SessionState, V4Session
from scripts.run_session_300 import observe, validate_report
from scripts.session_suite import observe_suite, validate_suite
from tests.test_session_300_probe import PROOF
from tests.test_session_300_runtime import Stream, response
from tests.test_session_ignored_rx import ignored_frame
from tests.test_session_suite import Harness
from tests.test_session_suite_publication import node


@pytest.mark.parametrize("subcode", range(256))
@pytest.mark.parametrize("fragmented", [False, True])
def test_exact_two_bytes_for_every_subcode_and_origin(subcode, fragmented):
    framer = ExperimentalV4Framer()
    origin, later = object(), object()
    frame = bytes((5, subcode))
    if fragmented:
        assert framer.feed(frame[:1], origin) == [] and framer.partial
        events = framer.feed(frame[1:], later)
    else:
        events = framer.feed(frame, origin)
    assert len(events) == 1 and events[0].payload == frame
    assert events[0].exchange is origin and not framer.partial
    assert repr(events[0]) == "ExperimentalFrame()"
    error = ExperimentalCloseClientError(subcode)
    assert error.safe_report() == {
        "state": "closed",
        "error": "experimental_close_client",
        "reason": {
            2: "invalid_identifier",
            3: "stove_connection_required",
            4: "authorization_rejected",
            5: "authorization_timeout",
            6: "server_maintenance",
        }.get(subcode, "unknown"),
        "subcode": subcode,
        "phase": "post_open",
    }


@pytest.mark.parametrize("prefix", [b"", ignored_frame(7), ignored_frame(27)])
def test_coalesced_tail_is_retained_and_drained_with_original_exchange(prefix):
    framer = ExperimentalV4Framer()
    origin = object()
    tail = b"\x0a" + response()
    events = framer.feed(prefix + b"\x05\xff" + tail, origin)
    assert [e.payload for e in events] == [b"\x05\xff"]
    assert framer._tail == (tail, origin) and framer.partial
    with pytest.raises(HobenProtocolError):
        framer.feed(b"new delivery", object())  # Never overgrow retained RX.
    events = framer.feed(b"", object())
    assert [e.payload for e in events] == [b"\x0a", response()]
    assert all(e.exchange is origin for e in events) and not framer.partial


def test_unknown_after_close_does_not_erase_close_or_resynchronize():
    framer = ExperimentalV4Framer()
    assert framer.feed(b"\x05\x06\xff\x0a", object())[0].payload == b"\x05\x06"
    assert framer._tail[0] == b"\xff\x0a"
    with pytest.raises(HobenProtocolError):
        framer.feed(b"", object())
    assert framer._buffer == b"\xff"


def test_fragmented_close_tail_keeps_the_later_delivery_exchange():
    framer = ExperimentalV4Framer()
    first, later = object(), object()
    assert framer.feed(b"\x05", first) == []
    assert framer.feed(b"\x06" + response()[:7], later)[0].exchange is first
    assert framer.feed(b"", object()) == [] and framer.partial
    events = framer.feed(response()[7:], object())
    assert events[0].payload == response() and events[0].exchange is later


@pytest.mark.parametrize("subcode", [0, 2, 3, 4, 5, 6, 10, 255])
def test_waiter_gets_typed_close_and_no_suffix_tx_or_eof(subcode, caplog):
    async def scenario():
        stream = Stream([b"\x05", bytes((subcode,)) + b"\x0a" + response()])
        budget, policy = SessionReconnect(), NoPongAfter120()
        session = V4Session(
            user_guid="b" * 32,
            session_300=budget,
            no_pong_after_120=policy,
            transport_factory=lambda: stream,
        )
        await session.connect()
        with pytest.raises(ExperimentalCloseClientError) as caught:
            await session.request_v4_data()
        assert caught.value.subcode == subcode and session.close_client_received
        assert not session.loss_is_retryable and session.loss_monotonic_ms is None
        assert budget.close_client_subcodes == [subcode] and policy.peer_eofs == 0
        assert budget.pings == budget.pongs == budget.responses == 0
        assert [p[0] for p in stream.writes] == [3, 13]
        await session.abort()
        assert stream.close_count == 1 and stream.active_reads == stream.active_tx == 0
        assert session._rx_task.done() and not session._operations
        assert session._pending_read is None and not session._framer.partial
        assert session.state is SessionState.CLOSED
        assert "bbbbbbbb" not in str(caught.value.safe_report()) + caplog.text

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "ending", [b"", TransportEOF("synthetic"), TransportTlsError("synthetic")]
)
def test_partial_close_is_never_promoted_to_complete_close(ending):
    async def scenario():
        stream = Stream([b"\x05", ending])
        budget, policy = SessionReconnect(), NoPongAfter120()
        session = V4Session(
            user_guid="b" * 32,
            session_300=budget,
            no_pong_after_120=policy,
            transport_factory=lambda: stream,
        )
        await session.connect()
        with pytest.raises((HobenProtocolError, HobenTransportError)):
            await session.request_v4_data()
        assert not session.close_client_received and not budget.close_client_subcodes
        assert policy.peer_eofs == int(not isinstance(ending, TransportTlsError))
        await session.abort()
        assert stream.close_count == 1 and not session._operations
        assert stream.active_reads == stream.active_tx == 0

    asyncio.run(scenario())


def test_cancel_partial_waiter_never_creates_close_or_eof():
    async def scenario():
        stream, budget, policy = Stream([b"\x05"]), SessionReconnect(), NoPongAfter120()
        session = V4Session(
            user_guid="b" * 32,
            session_300=budget,
            no_pong_after_120=policy,
            transport_factory=lambda: stream,
        )
        await session.connect()
        pending = asyncio.create_task(session.request_v4_data())
        while not budget.partial:
            await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await session.abort()
        assert not session.close_client_received and not budget.close_client_subcodes
        assert policy.peer_eofs == 0 and session._pending_read is None
        assert stream.close_count == 1 and stream.active_reads == stream.active_tx == 0

    asyncio.run(scenario())


def test_fresh_transport_never_inherits_coalesced_old_session_bytes():
    async def scenario():
        streams = [Stream(), Stream([response()])]
        factory = iter(streams)
        budget = Session300()
        session = V4Session(
            user_guid="b" * 32,
            session_300=budget,
            transport_factory=lambda: next(factory),
        )
        await session.connect()
        streams[0].queue.put_nowait(b"\x05\xff\x0a" + response())
        with pytest.raises(ExperimentalCloseClientError):
            await session.wait_rx_stopped()
        assert session._framer._tail[0] == b"\x0a" + response()
        await session.connect()
        assert (await session.request_v4_data()).registers == (17,) * 20
        assert budget.responses == 1 and budget.pings == budget.pongs == 0
        await session.abort()
        assert all(
            s.close_count == 1 and s.active_reads == s.active_tx == 0 for s in streams
        )

    asyncio.run(scenario())


def test_lifecycle_aborts_blocked_tx_before_bounded_close_recovery():
    async def scenario():
        now, streams, sessions, delays = [0.0], [], [], []
        budget = Session300(clock=lambda: now[0])
        gate, started = asyncio.Event(), asyncio.Event()

        def factory(**kwargs):
            stream = Stream([response()])
            if not streams:
                original = stream.write

                async def blocked(payload):
                    if payload[0] == 13:
                        started.set()
                        await gate.wait()
                    await original(payload)

                stream.write = blocked
            streams.append(stream)
            session = V4Session(
                **kwargs, session_300=budget, transport_factory=lambda: stream
            )
            sessions.append(session)
            return session

        async def backoff(delay):
            delays.append(delay)
            await asyncio.sleep(0)

        life = V4Lifecycle(
            user_guid="b" * 32,
            session_factory=factory,
            retry_delays=(1.0, 2.0),
            sleep=backoff,
        )
        async with asyncio.timeout(2):
            await life.connect()
            read = asyncio.create_task(life.request_v4_data())
            await started.wait()
            streams[0].queue.put_nowait(b"\x05\x06")
            while len(streams) < 2:
                await asyncio.sleep(0)
            await life.wait_connected()
            await asyncio.gather(read, return_exceptions=True)
            assert read.done() and streams[0].close_count == 1 and delays == [1.0]
            now[0] = 60
            assert (await life.request_v4_data()).registers == (17,) * 20
            assert life.witness.verified_read_generation == 2
            assert life.witness.lost_generation is None
            await life.close()
        assert all(
            s.close_count == 1 and s.active_reads == s.active_tx == 0 for s in streams
        )
        assert all(s._rx_task.done() and not s._operations for s in sessions)
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    asyncio.run(scenario())


class CloseHarness(Harness):
    def __init__(self, *, subcode=255, at=160, mode="recovered"):
        super().__init__("no_disconnect")  # Base fixture must never inject an EOF.
        self.subcode, self.at, self.close_mode = subcode, at, mode
        self.closed_streams = set()

    def make(self, budget, policy):
        life = super().make(budget, policy)
        original = life._factory

        def factory(**kwargs):
            session = original(**kwargs)
            if self.close_mode == "close_failure" and policy is not None:
                original_close = self.streams[-1].close

                async def failed_close():
                    await original_close()
                    raise RuntimeError("synthetic-private")

                self.streams[-1].close = failed_close
            if budget.opens >= 1 and policy is not None:
                if self.close_mode == "bad_response":
                    self.streams[-1].chunks = [b"\xff"]
                if self.close_mode == "reopen_failed":

                    async def fail():
                        raise TransportTlsError("synthetic-private")

                    self.streams[-1].connect = fail
            return session

        life._factory = factory
        return life

    async def sleep(self, delay):
        if self.policy is not None and not self.closed_streams:
            delay = min(delay, max(0, self.policy.first_opened_at + self.at - self.now))
        await super().sleep(delay)
        anchor = self.policy.first_opened_at if self.policy is not None else 0
        enabled = self.policy is not None or self.close_mode == "first"
        if enabled and self.now - anchor >= self.at:
            stream = self.streams[-1]
            if stream not in self.closed_streams and (
                not self.closed_streams or self.close_mode == "repeated"
            ):
                self.closed_streams.add(stream)
                stream.queue.put_nowait(b"\x05")
                await self.spin()
                assert (
                    not self.budget.close_client_subcodes
                    or len(self.closed_streams) > 1
                )
                stream.queue.put_nowait(bytes((self.subcode,)) + b"\xff\x0a")
                await self.spin()


async def run_close_harness(**kwargs):
    h = CloseHarness(**kwargs)
    r = await observe_suite(h.make, PROOF, clock=h.clock, sleep=h.sleep)
    h.assert_closed()
    return h, r


def test_session_300_report_records_close_and_only_claims_recovery_after_valid_read():
    async def scenario():
        h = CloseHarness(mode="first", at=60)
        budget = Session300(clock=h.clock)
        r = await observe(
            h.make(budget, None), budget, PROOF, clock=h.clock, sleep=h.sleep
        )
        h.assert_closed()
        return r

    r = asyncio.run(scenario())
    assert r["result"] == "reconnected" and r["reads_ok"] > 0
    assert r["close_client"] == {
        "phase": "post_open",
        "subcodes": [255],
        "after_threshold_ms": None,
    }
    assert validate_report(r, PROOF) == r
    assert (
        node(
            """
const [r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(require('./.github/scripts/session-300-report.cjs').validate(r,p)));
""",
            [r, PROOF],
        )
        == r
    )


@pytest.mark.parametrize("subcode", [0, 2, 3, 4, 5, 6, 255])
def test_real_suite_recovers_after_close_without_fabricating_eof(subcode):
    h, r = asyncio.run(run_close_harness(subcode=subcode))
    s = r["session_reconnect_no_pong"]
    assert r["result"] == "success" and s["result"] == "recovered_120s"
    assert s["close_client"] == {
        "phase": "post_open",
        "subcodes": [subcode],
        "after_threshold_ms": 40000,
    }
    assert s["peer_eofs"] == s["eofs_after_suppression"] == 0
    assert s["eof_after_threshold_ms"] is None
    assert s["recovery_generation"] == 2 and s["recovery_reads_ok"] > 0
    assert s["stable_ms"] == 120000 and s["recovery_pongs"] > 0
    assert h.lives[-1].witness.lost_generation is None
    assert validate_suite(r, PROOF) == r


@pytest.mark.parametrize("at,success", [(238.5, True), (239, False), (240, False)])
def test_close_and_new_acceptance_must_precede_240(at, success):
    _, r = asyncio.run(run_close_harness(at=at))
    s = r["session_reconnect_no_pong"]
    assert (s["result"] == "recovered_120s") is success
    assert s["duration_ms"] <= 360000 and s["peer_eofs"] == 0


@pytest.mark.parametrize(
    "mode", ["bad_response", "reopen_failed", "repeated", "early", "close_failure"]
)
def test_close_alone_cannot_claim_success_and_retries_stay_bounded(mode):
    h, r = asyncio.run(run_close_harness(at=60 if mode == "early" else 160, mode=mode))
    s = r["session_reconnect_no_pong"]
    assert r["result"] == "not_successful" and s["result"] != "recovered_120s"
    assert s["peer_eofs"] == 0 and s["opens"] <= 3
    assert len(s["close_client"]["subcodes"]) <= 3
    if mode == "early":
        assert s["close_client"]["after_threshold_ms"] is None
    if mode == "reopen_failed":
        assert s["opens"] == 3 and s["terminal"] == "reopen_failed"
    if mode == "repeated":
        assert s["terminal"] == "stability_lost"
    if mode == "close_failure":
        assert s["opens"] == 1 and s["terminal"] == "closed"


@pytest.fixture(scope="module")
def close_report():
    return asyncio.run(run_close_harness())[1]


@pytest.mark.parametrize(
    "change",
    [
        {"phase": "opening"},
        {"subcodes": []},
        {"subcodes": [True]},
        {"subcodes": [256]},
        {"subcodes": [-1]},
        {"subcodes": [1, 2, 3, 4]},
        {"subcodes": "private"},
        {"payload": "private"},
        {"after_threshold_ms": True},
        {"after_threshold_ms": 480001},
        {"after_threshold_ms": None},
        {"after_threshold_ms": 120000},
        {"after_threshold_ms": 180000},
    ],
)
def test_python_and_node_refuse_malformed_close_metadata(close_report, change):
    bad = copy.deepcopy(close_report)
    bad["session_reconnect_no_pong"]["close_client"].update(change)
    with pytest.raises(ValueError):
        validate_suite(bad, PROOF)
    result = node(
        """
const [r,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let allowed=true;
try{require('./.github/scripts/session-suite-report.cjs').validate(r,p);}
catch(_){allowed=false;}process.stdout.write(JSON.stringify(allowed));
""",
        [bad, PROOF],
    )
    assert result is False


def test_real_close_report_passes_separate_node_publication(close_report, tmp_path):
    folder = tmp_path / "hoben-session-suite-exports"
    folder.mkdir()
    (folder / "report.json").write_text(json.dumps(close_report))
    result = node(
        """
const [root,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.env.RUNNER_TEMP=root;
const api=require('./.github/scripts/session-suite-report.cjs');
let outputs={},errors=[];
const core={setOutput:(k,v)=>outputs[k]=v,setFailed:v=>errors.push(v)};
api.prepare({core,proof:p});const encoded=outputs.report_b64;outputs={};
api.publish({core,proof:p,encoded});
const r=api.readReport(root+'/hoben-session-suite-public/report.json',p);
process.stdout.write(JSON.stringify({errors,outputs,r}));
""",
        [str(tmp_path), PROOF],
    )
    assert result["errors"] == [] and result["outputs"] == {"report": "true"}
    assert result["r"] == close_report
    missing = copy.deepcopy(close_report)
    del missing["session_reconnect_no_pong"]["close_client"]
    with pytest.raises(ValueError):
        validate_suite(missing, PROOF)  # No success from zero EOF without close proof.
