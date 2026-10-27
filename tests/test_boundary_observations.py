"""Synthetic #48 exploration with a virtual clock and one scripted RX reader."""

import asyncio
import json

import pytest

from custom_components.hoben.modbus import encode_mbap
from scripts.boundary_analysis import H2Framer, RxRead, analyze_capture
from scripts.boundary_capture import (
    RX_LIMIT,
    V4_REQUEST,
    PrivateCapture,
    collect_session,
    run_campaign,
)
from tests.test_post_open_handoff import FIELDS, OPENED_PREFIX

RESPONSE = b"\x0e" + encode_mbap(0xFFFF, 1, b"\x04\x28" + b"\x0a\x1b" * 20)
NOTIFICATION = b"\x1b\x0a\x0e\x1b\x04" + RESPONSE[1:]
PRIVATE = b"SYNTHETIC-PRIVATE-SUFFIX"


class VirtualStream:
    """Client time advances at scripted arrivals or timers, without real sleeps."""

    def __init__(self, script=(), *, replies=True, cancel_on_read=False):
        self.now = 0.0
        self.script = list(script)
        self.replies = replies
        self.cancel_on_read = cancel_on_read
        self.pending = None
        self.capacity = None
        self.writes = []
        self.received = []
        self.connects = 0
        self.closed = False
        self.active_reads = 0
        self.maximum_readers = 0

    def factory(self, **kwargs):
        assert kwargs == {"connect_timeout": 5, "read_timeout": 120, "write_timeout": 5}
        return self

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)

    async def connect(self):
        self.connects += 1

    async def write(self, payload):
        self.writes.append((self.now, payload))
        if payload == V4_REQUEST:
            if self.cancel_on_read:
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
            if self.replies:
                self.script.append((self.now + 0.25, RESPONSE))
                self.script.sort(key=lambda item: item[0])

    async def read(self, capacity):
        self.active_reads += 1
        self.maximum_readers = max(self.maximum_readers, self.active_reads)
        assert self.active_reads == 1
        self.pending = asyncio.get_running_loop().create_future()
        self.capacity = capacity
        try:
            return await self.pending
        finally:
            self.pending = None
            self.active_reads -= 1

    async def close(self):
        self.closed = True

    async def wait(self, task, timeout):
        await asyncio.sleep(0)
        if task.done():
            return True
        until = self.now + max(0, timeout)
        if not self.script or self.script[0][0] > until:
            self.now = until
            return False
        self.now = max(self.now, self.script[0][0])
        arrived = bytearray()
        while self.script and self.script[0][0] <= self.now:
            at, data = self.script.pop(0)
            if isinstance(data, Exception):
                if arrived:
                    self.script.insert(0, (at, data))
                    break
                self.pending.set_exception(data)
                break
            if not data:
                if arrived:
                    self.script.insert(0, (at, data))
                break
            available = self.capacity - len(arrived)
            arrived.extend(data[:available])
            if len(data) > available:
                self.script.insert(0, (at, data[available:]))
            if len(arrived) >= self.capacity:
                break
        if not self.pending.done():
            received = bytes(arrived)
            self.received.append(received)
            self.pending.set_result(received)
        await asyncio.sleep(0)
        return task.done()


def observe(tmp_path, world, *, mode="H2", pause=0.0, seconds=90.0, cancelled=False):
    capture = PrivateCapture(tmp_path / "session")

    async def run():
        return await collect_session(
            capture,
            mode=mode,
            user_guid=FIELDS["user_guid"],
            device_guid=FIELDS["device_guid"],
            pause=pause,
            repetition=1,
            seconds=seconds,
            transport_factory=world.factory,
            clock=world.clock,
            sleep=world.sleep,
            waiter=world.wait,
        )

    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())
        outcome = None
    else:
        outcome = asyncio.run(run())
    assert world.closed
    assert world.connects == 1
    assert world.maximum_readers <= 1
    assert world.active_reads == 0
    assert (capture.directory / "rx.bin").read_bytes() == b"".join(world.received)
    assert bytes(capture.data) == b"".join(world.received)
    journal = [
        json.loads(line)
        for line in (capture.directory / "journal.jsonl").read_text().splitlines()
    ]
    reads = [event for event in journal if event["kind"] == "rx"]
    assert [r["index"] for r in reads] == list(range(len(reads)))
    offset = 0
    for record in reads:
        assert record["offset"] == offset
        assert 0 <= record["returned"] <= record["requested"] <= 4096
        assert record["ended"] >= record["started"]
        offset += record["returned"]
    assert offset == len(capture.data)
    assert capture.directory.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in capture.directory.iterdir())
    public = json.dumps(outcome.report) + repr(outcome) if outcome else ""
    for secret in (
        PRIVATE.decode(),
        FIELDS["user_guid"],
        OPENED_PREFIX[14:46].decode(),
        repr(RESPONSE),
        repr(NOTIFICATION),
    ):
        assert secret not in public + repr(capture)
    return outcome, capture, journal


@pytest.mark.parametrize("split", range(49))
def test_capture_every_opening_split_and_two_timed_correlated_reads(tmp_path, split):
    chunks = [(0.01, OPENED_PREFIX[:split]), (0.02, OPENED_PREFIX[split:])]
    world = VirtualStream([(at, data) for at, data in chunks if data])
    result, capture, journal = observe(tmp_path, world)
    assert result.stop == "observation_budget"
    assert result.valid_responses == result.requests == 2
    assert result.report["boundary_proven"] is False
    writes = [at for at, packet in world.writes if packet == V4_REQUEST]
    assert writes[0] >= 5.01
    assert writes[1] >= writes[0] + 0.25 + 20
    assert len([e for e in journal if e["kind"] == "response_correlation"]) == 2
    assert all(r["same_framing"] for r in result.report["replay"])
    assert bytes(capture.data).startswith(OPENED_PREFIX)


@pytest.mark.parametrize("pause", [0.0, 0.1, 1.0])
def test_h1_preserves_delayed_suffix_and_never_sends_after_open(tmp_path, pause):
    world = VirtualStream(
        [
            (0.01, b"\x0a"),
            (1.01, OPENED_PREFIX),
            (2.5, b"\x0a" + NOTIFICATION + PRIVATE),
            (3, b""),
        ]
    )
    result, capture, journal = observe(tmp_path, world, mode="H1", pause=pause)
    assert [packet[0] for _, packet in world.writes] == [3, 11]
    assert result.pongs_before_open == 1
    assert result.requests == result.pongs_under_h2 == 0
    assert (
        bytes(capture.data)
        == b"\x0a" + OPENED_PREFIX + b"\x0a" + NOTIFICATION + PRIVATE
    )
    event = next(e for e in journal if e["kind"] == "reader_pause")
    assert event["requested_seconds"] == pause
    assert event["ended"] - event["started"] == pause
    assert result.report["h1"]["status"] == "compatible"
    assert result.report["h2"]["status"] == "contradicted"
    timing = result.report["timing_observations"]
    assert timing["basis"] == "client_monotonic_relative"
    assert [r["received"] for r in timing["reads"]] == [
        r.returned for r in capture.reads
    ]
    assert sum(r["received"] for r in timing["reads"]) == len(capture.data)
    assert any(r["state"] == "eof" for r in timing["reads"])
    assert timing["tx"][0]["category"] == "open_client"
    assert timing["close"]["state"] == "closed"
    assert all(f["confidence"] == "h2_hypothesis_only" for f in timing["h2_candidates"])
    assert result.stop == "peer_eof" and result.report["partial"]


@pytest.mark.parametrize(
    "suffix",
    [
        b"\xff" + PRIVATE,
        b"\x0a\xff" + PRIVATE,
        b"\x0e\xff\xff\x00\x01\x00\x2b",
        b"\x05\x02",
    ],
)
def test_bad_h2_batch_stops_tx_but_keeps_all_subsequent_rx(tmp_path, suffix):
    world = VirtualStream(
        [
            (0.01, OPENED_PREFIX + suffix),
            (2, NOTIFICATION + PRIVATE),
            (3, b"\x0a"),
            (4, b""),
        ]
    )
    result, capture, _ = observe(tmp_path, world)
    assert len(world.writes) == 1
    assert result.requests == result.pongs_under_h2 == 0
    assert result.emission_stop
    assert bytes(capture.data).endswith(NOTIFICATION + PRIVATE + b"\x0a")
    assert all(r["same_framing"] for r in result.report["replay"])


def test_h2_ping_and_notification_are_distinct_from_read_response(tmp_path):
    world = VirtualStream(
        [(0.01, OPENED_PREFIX + b"\x0a" + NOTIFICATION), (10, NOTIFICATION + b"\x0a")]
    )
    result, _, _ = observe(tmp_path, world)
    assert result.valid_responses == 2
    assert result.pongs_under_h2 == 2
    assert result.report["h2"]["frame_counts"] == {
        "notification_h2": 2,
        "ping_h2": 2,
        "response_h2": 2,
    }


def test_timed_out_ffff_closes_before_any_late_response_or_second_request(tmp_path):
    world = VirtualStream([(0.01, OPENED_PREFIX), (15.02, RESPONSE)], replies=False)
    result, capture, _ = observe(tmp_path, world)
    assert result.stop == "response_timeout"
    assert result.requests == 1 and result.valid_responses == 0
    assert bytes(capture.data) == OPENED_PREFIX
    assert world.script == [(15.02, RESPONSE)]


@pytest.mark.parametrize(
    "response",
    [
        b"\x0e" + encode_mbap(17, 1, b"\x04\x28" + bytes(40)),
        b"\x0e" + encode_mbap(0xFFFF, 2, b"\x04\x28" + bytes(40)),
        b"\x0e" + encode_mbap(0xFFFF, 1, b"\x03\x28" + bytes(40)),
        b"\x0e" + encode_mbap(0xFFFF, 1, b"\x04\x02\x00\x00"),
        b"\x0e" + encode_mbap(0xFFFF, 1, b"\x04\x00"),
    ],
)
def test_invalid_correlation_closes_pending_session(tmp_path, response):
    world = VirtualStream([(0.01, OPENED_PREFIX), (6, response)], replies=False)
    result, _, _ = observe(tmp_path, world)
    assert result.stop == "invalid_correlation"
    assert result.requests == 1 and result.valid_responses == 0


def test_correlated_exception_is_terminal_and_never_causes_second_read(tmp_path):
    exception = b"\x0e" + encode_mbap(0xFFFF, 1, b"\x84\x02")
    world = VirtualStream([(0.01, OPENED_PREFIX), (6, exception)], replies=False)
    result, _, _ = observe(tmp_path, world)
    assert result.stop == "modbus_exception"
    assert result.exception_responses == result.requests == 1


def test_cancelled_written_request_closes_and_keeps_private_capture(tmp_path):
    world = VirtualStream([(0.01, OPENED_PREFIX)], cancel_on_read=True)
    _, capture, _ = observe(tmp_path, world, cancelled=True)
    assert [packet[0] for _, packet in world.writes] == [3, 13]
    analysis = json.loads((capture.directory / "analysis.json").read_text())
    assert analysis["stop"] == "cancelled"


def test_exact_rx_cap_is_partial_with_no_silent_truncation(tmp_path):
    payload = OPENED_PREFIX + PRIVATE * (RX_LIMIT // len(PRIVATE) + 1)
    world = VirtualStream([(0.01, payload)])
    result, capture, _ = observe(tmp_path, world, mode="H1")
    assert result.stop == "rx_limit" and result.report["partial"]
    assert len(capture.data) == RX_LIMIT
    assert bytes(capture.data) == payload[:RX_LIMIT]
    assert world.script[0][1] == payload[RX_LIMIT:]


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"\x2f" + PRIVATE, "authorization_required"),
        (b"\x05\x04" + PRIVATE, "opening_rejected"),
        (b"\xff" + PRIVATE, "unexpected_opening_type"),
    ],
)
def test_rejection_keeps_entire_block_without_association(tmp_path, data, expected):
    world = VirtualStream([(0.01, data)])
    result, capture, _ = observe(tmp_path, world)
    assert result.stop == expected
    assert len(world.writes) == 1
    assert bytes(capture.data) == data


@pytest.mark.parametrize("data", [OPENED_PREFIX[:10], b""])
def test_eof_or_open_timeout_is_inconclusive(tmp_path, data):
    world = VirtualStream([(0.01, data), (1, b"")])
    result, _, _ = observe(tmp_path, world)
    assert not result.prefix_complete
    assert result.report["comparison"] == "insufficient_data"


@pytest.mark.parametrize("split", range(len(NOTIFICATION + RESPONSE) + 2))
def test_experimental_h2_replay_independent_of_all_split_points(split):
    data = NOTIFICATION + RESPONSE + b"\x0a"
    framer = H2Framer(48)
    framer.feed(data[:split])
    framer.feed(data[split:])
    assert [(f.category, f.offset, f.length) for f in framer.frames] == [
        ("notification_h2", 48, len(NOTIFICATION)),
        ("response_h2", 48 + len(NOTIFICATION), len(RESPONSE)),
        ("ping_h2", 48 + len(NOTIFICATION) + len(RESPONSE), 1),
    ]
    assert framer.report(len(data))["status"] == "compatible"
    assert repr(NOTIFICATION[1:5]) not in repr(framer.frames)


@pytest.mark.parametrize("length", [0, 1, 255, 65535])
def test_invalid_mbap_fails_once_without_scanning(length):
    data = b"\x0e\xff\xff\x00\x00" + length.to_bytes(2, "big") + PRIVATE
    framer = H2Framer(48)
    assert framer.feed(data) == []
    assert framer.error == "invalid_mbap_h2"
    assert framer.feed(RESPONSE) == []
    assert framer.report(len(data) + len(RESPONSE))["covered_bytes"] == 0


def test_pause_models_are_not_exhaustive_and_silence_proves_nothing():
    reads = [
        RxRead(0, 0, 4096, 48, 0, 0.01, None),
        RxRead(1, 48, 4096, len(RESPONSE), 0.01, 2, 0.01),
    ]
    report = analyze_capture(OPENED_PREFIX + RESPONSE, reads, 0)
    assert report["comparison"] == "compatible_with_both"
    assert all(item["same_framing"] for item in report["replay"])
    silent = analyze_capture(OPENED_PREFIX, reads[:1], 0)
    assert silent["comparison"] == "insufficient_data"
    assert silent["h2"]["status"] == "inconclusive"


def test_campaign_conditions_spacing_and_identity_reuse(tmp_path):
    calls = []
    spacings = []

    async def session(capture, **kwargs):
        calls.append(kwargs)
        world = VirtualStream([(0.01, OPENED_PREFIX), (1, b"")])
        return await collect_session(
            capture,
            **kwargs,
            transport_factory=world.factory,
            clock=world.clock,
            sleep=world.sleep,
            waiter=world.wait,
        )

    async def delay(seconds):
        spacings.append(seconds)

    report = asyncio.run(
        run_campaign(
            tmp_path,
            mode="both",
            user_guid=FIELDS["user_guid"],
            device_guid=FIELDS["device_guid"],
            session_runner=session,
            sleep=delay,
        )
    )
    assert report["executed_sessions"] == report["planned_sessions"] == 12
    assert [(k["mode"], k["pause"], k["repetition"]) for k in calls] == [
        (mode, pause, repeat)
        for mode in ("H1", "H2")
        for pause in (0.0, 0.1, 1.0)
        for repeat in (1, 2)
    ]
    assert spacings == [15.0] * 11
    assert calls[0]["device_guid"] == FIELDS["device_guid"]
    assert all(c["device_guid"] == OPENED_PREFIX[14:46].decode() for c in calls[1:])
    assert OPENED_PREFIX[14:46].decode() not in json.dumps(report)


@pytest.mark.parametrize(
    "script,executed",
    [[[(0, b"\x2f")], 1], [[(0, RuntimeError("PRIVATE failure"))], 2]],
)
def test_campaign_stops_on_auth_or_repeated_errors(tmp_path, script, executed):
    async def session(capture, **kwargs):
        world = VirtualStream(script)
        return await collect_session(
            capture,
            **kwargs,
            transport_factory=world.factory,
            clock=world.clock,
            sleep=world.sleep,
            waiter=world.wait,
        )

    async def delay(seconds):
        pass

    report = asyncio.run(
        run_campaign(
            tmp_path,
            mode="both",
            user_guid=FIELDS["user_guid"],
            device_guid=FIELDS["device_guid"],
            session_runner=session,
            sleep=delay,
        )
    )
    assert report["executed_sessions"] == executed and report["stopped_early"]
    assert "PRIVATE" not in json.dumps(report)


def test_offline_file_replay_matches_live_annotations_and_preserves_raw(tmp_path):
    from scripts.replay_opened_client_boundary import replay

    world = VirtualStream([(0.01, OPENED_PREFIX), (2, NOTIFICATION), (3, b"")])
    result, capture, _ = observe(tmp_path, world, mode="H1")
    before = (capture.directory / "rx.bin").read_bytes()
    replayed = replay(capture.directory)
    assert {k: replayed[k] for k in ("h1", "h2", "replay", "comparison")} == {
        k: result.report[k] for k in ("h1", "h2", "replay", "comparison")
    }
    assert replayed["boundary_proven"] is False
    assert (capture.directory / "rx.bin").read_bytes() == before


def test_completed_rx_anomaly_wins_over_a_simultaneously_due_tx(tmp_path):
    world = VirtualStream([(0.01, OPENED_PREFIX), (5.01, b"\xff" + PRIVATE), (6, b"")])
    original_wait = world.wait
    raced = False

    async def race(task, timeout):
        nonlocal raced
        done = await original_wait(task, timeout)
        # Simulate a timer awakening as the reader is already done.
        if world.now == 5.01 and done and not raced:
            raced = True
            return False
        return done

    world.wait = race
    result, _, _ = observe(tmp_path, world)
    assert result.requests == 0 and len(world.writes) == 1
    assert result.emission_stop == "unsupported_type_h2"


def test_late_completed_response_cannot_be_accepted_after_deadline(tmp_path):
    world = VirtualStream([(0.01, OPENED_PREFIX), (15.5, RESPONSE)], replies=False)
    original_wait = world.wait

    async def stalled(task, timeout):
        if world.now >= 5 and timeout <= 10:
            return await original_wait(task, timeout + 1)
        return await original_wait(task, timeout)

    world.wait = stalled
    result, _, _ = observe(tmp_path, world)
    assert result.stop == "response_timeout" and result.requests == 1
    assert result.valid_responses == 0


def test_blocked_request_drain_obeys_response_budget_and_closes(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.boundary_capture.RESPONSE_BUDGET", 0.01)
    world = VirtualStream([(0.01, OPENED_PREFIX)], replies=False)
    original_write = world.write
    drain_cancelled = False

    async def blocked_write(payload):
        nonlocal drain_cancelled
        await original_write(payload)
        if payload == V4_REQUEST:
            try:
                await asyncio.get_running_loop().create_future()
            finally:
                drain_cancelled = True

    world.write = blocked_write
    result, _, journal = observe(tmp_path, world)
    assert drain_cancelled
    assert result.stop == "response_timeout" and result.requests == 1
    assert result.valid_responses == 0
    assert len(world.writes) == 2
    assert not any(
        e["kind"] == "tx_complete" and e["category"] == "read_v4_h2" for e in journal
    )


def test_initial_opening_silence_is_bounded_and_no_reconnect_occurs(tmp_path):
    world = VirtualStream()
    result, _, _ = observe(tmp_path, world)
    assert result.stop == "opening_timeout" and world.now == 15
    assert len(world.writes) == 1 and world.connects == 1


@pytest.mark.parametrize(
    "prefix",
    [
        OPENED_PREFIX[:8] + b"\xff" + OPENED_PREFIX[9:],
        OPENED_PREFIX[:14] + b"\xff" + OPENED_PREFIX[15:],
        OPENED_PREFIX[:14] + b"0" * 32 + OPENED_PREFIX[46:],
    ],
)
def test_unsupported_or_invalid_prefix_never_allows_v4_requests(tmp_path, prefix):
    world = VirtualStream([(0.01, prefix + b"\x0a" + RESPONSE)])
    result, _, _ = observe(tmp_path, world)
    assert not result.prefix_complete and result.assigned_identity is None
    assert result.requests == 0 and len(world.writes) == 1


@pytest.mark.parametrize("at", range(1, len(RESPONSE)))
def test_h2_partial_response_at_eof_remains_unattributed(at):
    data = OPENED_PREFIX + RESPONSE[:at]
    reads = [RxRead(0, 0, 4096, len(data), 0, 1, None)]
    result = analyze_capture(data, reads, 0)
    assert result["h2"]["status"] == "inconclusive"
    assert result["h2"]["covered_bytes"] == 0
    assert result["h2"]["unattributed_bytes"] == at
    assert result["h2"]["partial_frame"]
    assert all(r["same_framing"] for r in result["replay"])
