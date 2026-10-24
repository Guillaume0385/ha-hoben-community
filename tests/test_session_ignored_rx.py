"""Only synthetic RX: bounded headers, opaque bodies and strict publication."""

import asyncio
import copy
import json
import re
import subprocess
from pathlib import Path

import pytest

from custom_components.hoben.exceptions import HobenProtocolError, HobenTransportError
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_experiment import (
    IGNORED_PREFIXES,
    KNOWN_TYPE_DISCRIMINANTS,
    UNSUPPORTED_MESSAGE_TYPES,
    ExperimentalV4Framer,
    Session300,
    UnsupportedMessageTypeError,
)
from custom_components.hoben.v4_session import V4Session
from scripts.run_session_300 import validate_report
from scripts.session_suite import observe_suite, validate_suite
from tests.test_session_300_probe import PROOF
from tests.test_session_300_runtime import Stream, response
from tests.test_session_suite import Harness
from tests.test_session_suite_publication import node


def ignored_frame(kind, length=43):
    """Payload deliberately contains fake boundaries and invalid Modbus data."""
    metadata = b"\xff\x05\x0a\x0e" if kind == 27 else b""
    header = bytes([kind]) + metadata + b"\xff\xff\x00\x00" + length.to_bytes(2)
    return header + (b"\x05\xff\x0a\x0e" * 64)[:length]


@pytest.mark.parametrize("kind", [7, 27])
@pytest.mark.parametrize("split", range(1, 317))
def test_every_split_ignores_exact_body_and_preserves_following_exchange(kind, split):
    frame = ignored_frame(kind, 254)
    data = frame + b"\x0a" + response()
    budget = Session300()
    framer = ExperimentalV4Framer(diagnostic=budget)
    first, later = object(), object()
    events = framer.feed(data[:split], first) + framer.feed(data[split:], later)
    assert [event.payload for event in events] == [b"\x0a", response()]
    assert events[-1].exchange is (first if split > len(frame) + 1 else later)
    assert not framer.partial and budget.failure is None
    bins = budget.ignored_messages[str(kind)]
    assert sum(bins) == bins[252] == 1
    assert sum(budget.ignored_messages[str(34 - kind)]) == 0


@pytest.mark.parametrize("kind", [7, 27])
@pytest.mark.parametrize("length", [2, 43, 254])
def test_bytewise_retains_headers_only_and_counts_only_complete_messages(kind, length):
    budget = Session300()
    framer = ExperimentalV4Framer(diagnostic=budget)
    frame = ignored_frame(kind, length)
    for index, byte in enumerate(frame):
        assert framer.feed(bytes([byte]), object()) == []
        assert len(framer._buffer) <= IGNORED_PREFIXES[kind] + 5
        assert sum(budget.ignored_messages[str(kind)]) == int(index == len(frame) - 1)
        assert framer.partial is (index < len(frame) - 1)
    assert budget.ignored_messages[str(kind)][length - 2] == 1
    assert budget.ignored_diagnostic()["ignored_messages"] == budget.ignored_messages
    framer.clear()
    assert not framer.partial and not framer._buffer


@pytest.mark.parametrize("kind", [7, 27])
@pytest.mark.parametrize(
    "protocol,length", [(1, 2), (0, 0), (0, 1), (0, 255), (0, 65535)]
)
def test_invalid_mbap_rejected_at_header_without_consuming_body(kind, protocol, length):
    prefix = bytes([kind]) + (b"\x00" * 4 if kind == 27 else b"")
    header = prefix + b"\xff\xff" + protocol.to_bytes(2) + length.to_bytes(2)
    budget = Session300()
    framer = ExperimentalV4Framer(diagnostic=budget)
    with pytest.raises(HobenProtocolError):
        framer.feed(header + b"opaque\x0a" + response(), object())
    assert bytes(framer._buffer) == header
    assert not any(any(bins) for bins in budget.ignored_messages.values())
    assert budget.failure == ("frame_boundary", "protocol", "ambiguous")


def test_known_registry_matches_documented_types_and_typed_error_never_reads_payload():
    table = (
        Path("protocol.md")
        .read_text()
        .split("## 3. Types de messages MyHOBEN", 1)[1]
        .split("### Keepalive", 1)[0]
    )
    assert KNOWN_TYPE_DISCRIMINANTS == {
        int(number) for number in re.findall(r"^\| (\d+) \|", table, re.MULTILINE)
    }
    assert 25 not in KNOWN_TYPE_DISCRIMINANTS
    for kind in UNSUPPORTED_MESSAGE_TYPES:
        framer = ExperimentalV4Framer()
        with pytest.raises(UnsupportedMessageTypeError) as caught:
            framer.feed(bytes([kind]) + b"opaque\x0a" + response(), object())
        assert caught.value.message_type == kind
        assert caught.value.safe_report() == {
            "state": "error",
            "error": "unsupported_message_type",
            "message_type": kind,
        }
        assert bytes(framer._buffer) == bytes([kind])
        assert "opaque" not in repr(caught.value)
    for kind in (25, 255):
        with pytest.raises(HobenProtocolError) as caught:
            ExperimentalV4Framer().feed(bytes([kind]) + b"\x0a", object())
        assert type(caught.value) is HobenProtocolError


def test_known_rejection_does_not_issue_another_transport_read():
    async def scenario():
        stream = Stream([b"\x00", b"opaque\x0a" + response()])
        session = V4Session(
            user_guid="b" * 32,
            session_300=Session300(),
            transport_factory=lambda: stream,
        )
        await session.connect()
        with pytest.raises(UnsupportedMessageTypeError) as caught:
            await session.request_v4_data()
        assert caught.value.message_type == 0
        assert stream.queue.qsize() == 1  # The payload chunk was never fetched.
        await session.abort()
        assert stream.close_count == 1 and not session._operations

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", [7, 27])
def test_ignored_valid_modbus_response_cannot_satisfy_pending_read(kind):
    async def scenario():
        prefix = bytes([kind]) + (b"\x00" * 4 if kind == 27 else b"")
        stream = Stream([prefix + response()[1:]])
        budget = Session300()
        session = V4Session(
            user_guid="b" * 32, session_300=budget, transport_factory=lambda: stream
        )
        await session.connect()
        pending = asyncio.create_task(session.request_v4_data())
        for _ in range(30):
            await asyncio.sleep(0)
        assert sum(budget.ignored_messages[str(kind)]) == 1
        assert not pending.done() and budget.responses == 0
        assert session.verified_read_sequence == 0 and stream.close_count == 0
        stream.queue.put_nowait(response())
        await pending
        assert budget.responses == session.verified_read_sequence == 1
        await session.abort()
        assert stream.close_count == 1 and not session._operations

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", [7, 27])
def test_real_rx_continues_on_same_transport_without_matching_ignored_body_to_waiter(
    kind,
):
    async def scenario():
        frame = ignored_frame(kind)
        stream = Stream([frame[:3], frame[3:-1], frame[-1:] + b"\x0a" + response()])
        budget = Session300()
        session = V4Session(
            user_guid="b" * 32, session_300=budget, transport_factory=lambda: stream
        )
        await session.connect()
        await session.request_v4_data()
        assert budget.opens == budget.responses == budget.requests == 1
        assert budget.pings == budget.pongs == session.verified_read_sequence == 1
        assert stream.close_count == 0 and session._experiment_generation == 1
        assert budget.ignored_messages[str(kind)][41] == 1
        assert budget.failure is None and budget.usable
        await session.abort()
        assert stream.close_count == 1 and not session._operations

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", [7, 27])
@pytest.mark.parametrize("cut", [1, 6, 12, -1])
@pytest.mark.parametrize(
    "ending", [b"", TransportEOF("synthetic"), TransportTlsError("synthetic")]
)
def test_partial_ignored_frame_never_completes_pending_read_on_eof_or_tls(
    kind, cut, ending
):
    async def scenario():
        stream = Stream([ignored_frame(kind)[:cut], ending])
        budget = Session300()
        session = V4Session(
            user_guid="b" * 32, session_300=budget, transport_factory=lambda: stream
        )
        await session.connect()
        with pytest.raises((HobenProtocolError, HobenTransportError)):
            await session.request_v4_data()
        assert not any(any(bins) for bins in budget.ignored_messages.values())
        assert budget.responses == 0 and session.verified_read_sequence == 0
        await session.abort()
        assert stream.close_count == 1 and not session._operations

    asyncio.run(scenario())


class IgnoredHarness(Harness):
    def make(self, budget, policy):
        life = super().make(budget, policy)
        factory = life._factory

        def with_ignored(**kwargs):
            session = factory(**kwargs)
            self.streams[-1].chunks = [
                ignored_frame(7),
                ignored_frame(27) + b"\x0a" + response(),
            ]
            return session

        life._factory = with_ignored
        return life


async def observed_suite():
    harness = IgnoredHarness()
    report = await observe_suite(
        harness.make, PROOF, clock=harness.clock, sleep=harness.sleep
    )
    harness.assert_closed()
    return report


def node_results(cases):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const api=require('./.github/scripts/session-suite-report.cjs');
const [cases,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(r=>{
  try{return api.validate(r,p);}catch(_){return null;}
})));
""",
        ],
        input=json.dumps([cases, PROOF]),
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    return json.loads(result.stdout)


def test_real_suite_publishes_bounded_histograms_in_both_scenarios_and_retains_legacy():
    report = asyncio.run(observed_suite())
    assert report["result"] == "success"
    for key in ("session_300", "session_reconnect_no_pong"):
        scenario = report[key]
        hist = scenario["ignored_messages"]
        assert sum(hist["7"]) == sum(hist["27"]) == scenario["reads_ok"]
        assert hist["7"][41] == hist["27"][41] == scenario["reads_ok"]
    assert validate_suite(report, PROOF) == report
    assert node_results([report]) == [report]
    assert len(json.dumps(report).encode()) <= 8192
    assert len(json.dumps(report["session_300"]).encode()) <= 4096
    assert not any(
        token in json.dumps(report)
        for token in ("opaque", "payload", "register", "guid")
    )
    legacy = copy.deepcopy(report)
    for key in ("session_300", "session_reconnect_no_pong"):
        del legacy[key]["ignored_messages"]
    assert validate_suite(legacy, PROOF) == legacy
    assert node_results([legacy]) == [legacy]


def test_python_node_reject_malformed_histograms_and_overstated_bytes():
    report = asyncio.run(observed_suite())
    invalid = [None, [], {}, {"raw": "private"}, {"7": [0] * 253, "27": [0] * 254}]
    for value in (True, -1, 0.5, "1", 1048577):
        hist = copy.deepcopy(report["session_300"]["ignored_messages"])
        hist["7"][0] = value
        invalid.append(hist)
    hist = copy.deepcopy(report["session_300"]["ignored_messages"])
    hist["7"][252] = 1048576
    invalid.append(hist)
    cases = []
    for key in ("session_300", "session_reconnect_no_pong"):
        for hist in invalid:
            changed = copy.deepcopy(report)
            changed[key]["ignored_messages"] = hist
            with pytest.raises(ValueError):
                validate_suite(changed, PROOF)
            cases.append(changed)
    assert node_results(cases) == [None] * len(cases)
    first = report["session_300"]
    assert validate_report(first, PROOF) == first


def test_all_permitted_lengths_fit_existing_export_caps_at_the_rx_budget():
    report = asyncio.run(observed_suite())
    for key in ("session_300", "session_reconnect_no_pong"):
        scenario = report[key]
        scenario["rx_bytes_total"] = 1048576
        scenario["ignored_messages"] = {"7": [10] * 253, "27": [10] * 253}
        remaining = 1048576 - 10 * (sum(range(9, 262)) + sum(range(13, 266)))
        for kind, minimum in (("7", 9), ("27", 13)):
            for index in range(253):
                extra = min(90, remaining // (minimum + index))
                scenario["ignored_messages"][kind][index] += extra
                remaining -= extra * (minimum + index)
    assert validate_suite(report, PROOF) == report
    assert node_results([report]) == [report]
    assert len(json.dumps(report).encode()) <= 8192
    assert len(json.dumps(report["session_300"]).encode()) <= 4096


@pytest.mark.parametrize("suite", [False, True])
def test_histograms_survive_existing_export_and_isolated_publication(tmp_path, suite):
    report = asyncio.run(observed_suite())
    if not suite:
        report = report["session_300"]
    scenario = "session-suite" if suite else "session-300"
    folder = tmp_path / f"hoben-{scenario}-exports"
    folder.mkdir()
    (folder / "report.json").write_text(json.dumps(report))
    result = node(
        """
const [dir,r,p,scenario]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const api=require(`./.github/scripts/${scenario}-report.cjs`);
process.env.RUNNER_TEMP=dir;
let outputs={},errors=[];
const core={setOutput:(k,v)=>outputs[k]=v,setFailed:m=>errors.push(m)};
api.prepare({core,proof:p});
const encoded=outputs.report_b64;outputs={};
api.publish({core,proof:p,encoded});
const materialized=api.readReport(`${dir}/hoben-${scenario}-public/report.json`,p);
process.stdout.write(JSON.stringify({outputs,errors,materialized}));
""",
        [str(tmp_path), report, PROOF, scenario],
    )
    assert result == {
        "outputs": {"report": "true"},
        "errors": [],
        "materialized": report,
    }
