"""Bounded exploratory RX collection, isolated from the integration's lifecycle.

The only allowed TX are OpenClient, documented Pong and two fixed V4 reads under
H2. One reader saves bytes before any interpretation, even when H2 fails.
"""

import asyncio
import json
import os
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from custom_components.hoben.client import DEFAULT_BUILD, DEFAULT_DEVICE_INFO
from custom_components.hoben.modbus import (
    ModbusExceptionResponse,
    build_read_input_registers,
    decode_read_response,
)
from custom_components.hoben.myhoben import (
    INITIAL_DEVICE_GUID,
    decode_opened_client,
    encode_data_request_client,
    encode_open_client,
)
from custom_components.hoben.profiles import StoveProfile, select_stove_profile
from custom_components.hoben.transport import (
    AsyncTlsTransport,
    TransportEOF,
    TransportError,
)
from scripts.boundary_analysis import H2Framer, RxRead, analyze_capture, distribution
from scripts.boundary_timeline import metadata_timeline

READ_CAPACITY = 4096
RX_LIMIT = 1024 * 1024
OPENING_BUDGET = 15.0
RESPONSE_BUDGET = 10.0
FIRST_READ_DELAY = 5.0
SECOND_READ_DELAY = 20.0
SESSION_SPACING = 15.0
PAUSES = (0.0, 0.1, 1.0)
V4_REQUEST = encode_data_request_client(build_read_input_registers(0xFFFF, 1024, 20))


class CollectionBudgetExpired(Exception):
    """The experimental budget expired while draining an allowed TX."""


def private_json(path: Path, value: object) -> None:
    """Create private metadata without overwriting files or following symlinks."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, separators=(",", ":"))


class PrivateCapture:
    """Append-only raw stream plus a replay journal; all files stay outside Git."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(mode=0o700)
        self.directory = directory
        self.data = bytearray()
        self.reads: list[RxRead] = []
        self.events: list[dict] = []
        self._raw = os.fdopen(
            os.open(directory / "rx.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
            "wb",
        )
        self._journal = os.fdopen(
            os.open(
                directory / "journal.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            ),
            "w",
            encoding="utf-8",
        )

    def __repr__(self) -> str:
        return f"PrivateCapture(received_bytes={len(self.data)})"

    def event(self, value: dict) -> None:
        self.events.append(value)
        self._journal.write(json.dumps(value, separators=(",", ":")) + "\n")
        self._journal.flush()

    async def read(self, transport, clock: Callable[[], float]) -> bytes:
        """Persist every returned byte before making it available to the analyzer.

        The final capacity may be reduced to keep the exact 1 MiB ceiling; every
        other read requests 4096. EOF/errors/cancellation also get timed records.
        """
        capacity = min(READ_CAPACITY, RX_LIMIT - len(self.data))
        started = clock()
        data, status = b"", "received"
        try:
            data = await transport.read(capacity)
            if not data:
                status = "eof"
                raise TransportEOF("Peer closed")
            return data
        except TransportEOF:
            status = "eof"
            raise
        except asyncio.CancelledError:
            status = "cancelled_read"
            raise
        except Exception:
            status = "read_error"
            raise
        finally:
            # No awaited operation between read completion and saving its data.
            record = RxRead(
                len(self.reads),
                len(self.data),
                capacity,
                len(data),
                started,
                clock(),
                self.reads[-1].ended if self.reads else None,
            )
            self._raw.write(data)
            self._raw.flush()
            self.data.extend(data)
            self.reads.append(record)
            self.event({"kind": "rx", "status": status, **record.metadata()})

    def close(self) -> None:
        self._raw.close()
        self._journal.close()


@dataclass
class SessionOutcome:
    """Public experimental metadata, with identity excluded from repr/export."""

    mode: str
    pause: float
    repetition: int
    stop: str = "interrupted"
    opening_offset: int | None = None
    prefix_complete: bool = False
    requests: int = 0
    valid_responses: int = 0
    exception_responses: int = 0
    pongs_before_open: int = 0
    pongs_under_h2: int = 0
    emission_stop: str | None = None
    assigned_identity: str | None = field(default=None, repr=False)
    report: dict = field(default_factory=dict)


async def wait_read(task: asyncio.Task, delay: float) -> bool:
    """A timer never cancels or replaces the one live stream reader."""
    done, _ = await asyncio.wait({task}, timeout=max(0, delay))
    return task in done


async def collect_session(
    capture: PrivateCapture,
    *,
    mode: str,
    user_guid: str,
    device_guid: str,
    pause: float,
    repetition: int,
    seconds: float = 90.0,
    transport_factory: Callable = AsyncTlsTransport,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable] = asyncio.sleep,
    waiter: Callable = wait_read,
) -> SessionOutcome:
    """One connection, no retry; H1 is passive from the first opening byte.

    H2 schedules writes while the same timed read remains pending. Invalid input
    disables all later emissions. If a received batch is invalid, none of that
    batch's Ping candidates cause a Pong. An abandoned FFFF waiter terminates
    this session, so it can never satisfy a subsequent request.
    """
    if mode not in ("H1", "H2") or pause not in PAUSES or not 30 <= seconds <= 90:
        raise ValueError("Invalid experimental parameters")
    outcome = SessionOutcome(mode, pause, repetition)
    transport = transport_factory(connect_timeout=5, read_timeout=120, write_timeout=5)
    read_task = None
    prefix = bytearray()
    leading_offset = 0
    opening_started = None
    prefix_ready = None
    first_response = None
    pending_since = None
    active_deadline = None
    emissions = True
    framer = None

    async def send(category: str, payload: bytes) -> None:
        started = clock()
        capture.event(
            {
                "kind": "tx_attempt",
                "category": category,
                "started": started,
                "request_index": outcome.requests,
            }
        )
        deadline = active_deadline
        if pending_since is not None:
            deadline = min(deadline, pending_since + RESPONSE_BUDGET)
        if deadline is None:
            await transport.write(payload)
        else:
            remaining = deadline - clock()
            if remaining <= 0:
                raise CollectionBudgetExpired()
            budget = asyncio.timeout(remaining)
            try:
                async with budget:
                    await transport.write(payload)
            except TimeoutError:
                if budget.expired():
                    raise CollectionBudgetExpired() from None
                raise
        capture.event(
            {
                "kind": "tx_complete",
                "category": category,
                "started": started,
                "ended": clock(),
                "request_index": outcome.requests,
            }
        )

    try:
        await transport.connect()
        await send(
            "open_client",
            encode_open_client(
                user_guid,
                DEFAULT_BUILD,
                device_guid,
                DEFAULT_DEVICE_INFO,
            ),
        )
        opening_deadline = clock() + OPENING_BUDGET
        active_deadline = opening_deadline
        pause_start = clock()
        await sleep(pause)
        capture.event(
            {
                "kind": "reader_pause",
                "requested_seconds": pause,
                "started": pause_start,
                "ended": clock(),
            }
        )
        while True:
            now = clock()
            completed_read = read_task is not None and read_task.done()
            deadline = (
                opening_started + seconds
                if opening_started is not None
                else opening_deadline
            )
            # Persisted RX may have finished in time while this coroutine was
            # waiting to be scheduled. Drain it before enforcing current time;
            # its recorded completion time below decides budget admissibility.
            if now >= deadline and not completed_read:
                outcome.stop = (
                    "response_timeout"
                    if pending_since is not None
                    else "observation_budget"
                    if opening_started is not None
                    else "opening_timeout"
                )
                break
            if len(capture.data) >= RX_LIMIT and not completed_read:
                outcome.stop = "rx_limit"
                break
            if (
                pending_since is not None
                and now >= pending_since + RESPONSE_BUDGET
                and not completed_read
            ):
                outcome.stop = "response_timeout"
                break
            due = None
            if (
                mode == "H2"
                and emissions
                and prefix_ready is not None
                and pending_since is None
                and not framer.partial_frame
            ):
                # A frame begun before this request is not its response. While
                # it is incomplete, remove the due timer as well as the TX so
                # an expired scheduling deadline cannot spin the reader loop.
                if outcome.requests == 0:
                    due = prefix_ready + FIRST_READ_DELAY
                elif outcome.requests == 1 and first_response is not None:
                    due = first_response + SECOND_READ_DELAY
            if due is not None and now >= due and not completed_read:
                # Mark pending before drain: a failed drain may follow a write.
                outcome.requests += 1
                pending_since = clock()
                await send("read_v4_h2", V4_REQUEST)
                continue
            wake = min(
                deadline,
                pending_since + RESPONSE_BUDGET
                if pending_since is not None
                else deadline,
                due if due is not None else deadline,
            )
            if read_task is None:
                read_task = asyncio.create_task(capture.read(transport, clock))
            if not read_task.done() and not await waiter(read_task, wake - clock()):
                continue
            completed = read_task
            read_task = None
            error = completed.exception()  # Drain exceptions even for late RX.
            received_at = capture.reads[-1].ended
            if received_at > deadline:
                outcome.stop = (
                    "response_timeout"
                    if pending_since is not None
                    else "observation_budget"
                    if opening_started is not None
                    else "opening_timeout"
                )
                break
            if (
                pending_since is not None
                and received_at > pending_since + RESPONSE_BUDGET
            ):
                outcome.stop = "response_timeout"
                break
            if error is not None:
                raise error
            data = completed.result()
            if outcome.opening_offset is None:
                cursor = 0
                while cursor < len(data) and data[cursor] == 0x0A:
                    cursor += 1
                opening_in_batch = cursor < len(data) and data[cursor] == 0x04
                if mode == "H1" and opening_in_batch:
                    if cursor:
                        capture.event(
                            {
                                "kind": "h1_pongs_suppressed",
                                "count": cursor,
                                "received_at": received_at,
                            }
                        )
                else:
                    for _ in range(cursor):
                        await send("pong_before_open", b"\x0b")
                        outcome.pongs_before_open += 1
                leading_offset += cursor
                data = data[cursor:]
                if not data:
                    continue
                if data[0] == 0x2F:
                    outcome.stop = "authorization_required"
                    break
                if data[0] == 0x05:
                    outcome.stop = "opening_rejected"
                    break
                if data[0] != 0x04:
                    outcome.stop = "unexpected_opening_type"
                    break
                outcome.opening_offset = leading_offset
                opening_started = received_at
                active_deadline = opening_started + seconds
            if not outcome.prefix_complete:
                needed = 48 - len(prefix)
                prefix.extend(data[:needed])
                data = data[needed:]
                if len(prefix) < 48:
                    continue
                try:
                    opened = decode_opened_client(bytes(prefix))
                    if (
                        select_stove_profile(opened) is not StoveProfile.V4
                        or opened.device_guid == INITIAL_DEVICE_GUID
                    ):
                        outcome.stop = "unsupported_opening"
                        break
                except (TypeError, ValueError):
                    outcome.stop = "invalid_opening_prefix"
                    break
                outcome.assigned_identity = opened.device_guid
                outcome.prefix_complete = True
                capture.event(
                    {
                        "kind": "opening_accepted",
                        "offset": outcome.opening_offset,
                        "read_index": capture.reads[-1].index,
                        "received_at": received_at,
                    }
                )
                prefix_ready = received_at
                framer = H2Framer(outcome.opening_offset + 48)
            if mode == "H1" or not emissions:
                continue
            events = framer.feed(data)
            for event in events:
                capture.event(
                    {
                        "kind": "candidate_frame",
                        "received_at": received_at,
                        "attribution": "under_h2_only",
                        **event.annotation(),
                    }
                )
            if framer.error or framer.terminal:
                emissions = False
                outcome.emission_stop = framer.error or "terminal_close_h2"
                if pending_since is not None:
                    outcome.stop = "unusable_pending_session"
                    break
                continue
            # Validate the whole delivery without emitting or committing a
            # response first. Only one response can consume the existing FFFF
            # waiter; a duplicate later in the same batch invalidates it all.
            responses = []
            candidate_pending = pending_since is not None
            try:
                for event in events:
                    if event.category == "response_h2":
                        response = decode_read_response(event.adu)
                        if not candidate_pending or (
                            response.transaction_id,
                            response.unit_id,
                            response.function_code,
                        ) != (0xFFFF, 1, 4):
                            raise ValueError
                        if (
                            not isinstance(response, ModbusExceptionResponse)
                            and len(response.registers) != 20
                        ):
                            raise ValueError
                        candidate_pending = False
                        responses.append((event, response))
            except (TypeError, ValueError):
                emissions = False
                outcome.emission_stop = "invalid_correlation"
                capture.event(
                    {
                        "kind": "response_correlation",
                        "offset": event.offset,
                        "request_index": outcome.requests,
                        "received_at": received_at,
                        "result": "invalid_correlation",
                    }
                )
                if pending_since is not None:
                    outcome.stop = "invalid_correlation"
                    return outcome
                continue
            for event, response in responses:
                pending_since = None
                exception = isinstance(response, ModbusExceptionResponse)
                if exception:
                    outcome.exception_responses += 1
                else:
                    outcome.valid_responses += 1
                capture.event(
                    {
                        "kind": "response_correlation",
                        "offset": event.offset,
                        "request_index": outcome.requests,
                        "received_at": received_at,
                        "result": "correlated_exception"
                        if exception
                        else "correlated_response",
                    }
                )
                if exception:
                    outcome.stop = "modbus_exception"
                    return outcome
                if first_response is None:
                    first_response = received_at
            for event in events:
                if event.category == "ping_h2":
                    await send("pong_h2", b"\x0b")
                    outcome.pongs_under_h2 += 1
    except TransportEOF:
        outcome.stop = (
            "pending_response_eof" if pending_since is not None else "peer_eof"
        )
    except CollectionBudgetExpired:
        outcome.stop = (
            "response_timeout"
            if pending_since is not None
            else "observation_budget"
            if opening_started is not None
            else "opening_timeout"
        )
    except asyncio.CancelledError:
        outcome.stop = "cancelled"
        raise
    except Exception:
        # No arbitrary exception, payload or traceback enters public output.
        outcome.stop = "transport_or_capture_error"
    finally:
        if read_task is not None:
            read_task.cancel()
            await asyncio.gather(read_task, return_exceptions=True)
        capture.event({"kind": "close_attempt", "at": clock()})
        try:
            await transport.close()
            capture.event({"kind": "close_complete", "at": clock()})
        except TransportError:
            capture.event({"kind": "close_error", "at": clock()})
        finally:
            try:
                analysis = analyze_capture(
                    bytes(capture.data),
                    capture.reads,
                    outcome.opening_offset,
                    prefix_accepted=outcome.prefix_complete,
                )
                outcome.report = {
                    "mode": mode,
                    "pause_seconds": pause,
                    "repetition": repetition,
                    "stop": outcome.stop,
                    "partial": outcome.stop != "observation_budget"
                    or not outcome.prefix_complete,
                    "rx_bytes": len(capture.data),
                    "read_calls": len(capture.reads),
                    "opening_offset": outcome.opening_offset,
                    "prefix_complete": outcome.prefix_complete,
                    "v4_requests": outcome.requests,
                    "correlated_responses": outcome.valid_responses,
                    "exception_responses": outcome.exception_responses,
                    "pongs_before_open": outcome.pongs_before_open,
                    "pongs_under_h2": outcome.pongs_under_h2,
                    "emission_stop": outcome.emission_stop,
                    "boundary_proven": False,
                    **analysis,
                    "timing_observations": metadata_timeline(
                        capture.events,
                        capture.reads,
                        rx_bytes=len(capture.data),
                        opening_offset=outcome.opening_offset
                        if analysis["opening_context"]["eligible"]
                        else None,
                        h2=analysis["h2"],
                    ),
                }
                private_json(capture.directory / "analysis.json", outcome.report)
                if outcome.assigned_identity is not None:
                    private_json(
                        capture.directory / "assigned-identity.json",
                        {"device_guid": outcome.assigned_identity},
                    )
            finally:
                capture.close()
    return outcome


async def run_campaign(
    directory: Path,
    *,
    mode: str,
    user_guid: str,
    device_guid: str,
    seconds: float = 90,
    session_runner: Callable = collect_session,
    sleep: Callable = asyncio.sleep,
) -> dict:
    """Six sequential sessions per selected model; no reconnect or retry loop."""
    if mode not in ("H1", "H2", "both") or not 30 <= seconds <= 90:
        raise ValueError("Invalid campaign parameters")
    sessions = []
    errors = 0
    modes = ("H1", "H2") if mode == "both" else (mode,)
    planned = len(modes) * 6
    stop_campaign = False
    for selected in modes:
        for pause in PAUSES:
            for repetition in (1, 2):
                if sessions:
                    await sleep(SESSION_SPACING)
                capture = PrivateCapture(directory / f"session-{len(sessions) + 1:02d}")
                outcome = await session_runner(
                    capture,
                    mode=selected,
                    user_guid=user_guid,
                    device_guid=device_guid,
                    pause=pause,
                    repetition=repetition,
                    seconds=seconds,
                )
                sessions.append(outcome.report)
                if outcome.assigned_identity is not None:
                    device_guid = outcome.assigned_identity
                # Finishing passive RX cannot erase an earlier H2 failure.
                # An opaque terminal CloseClient is an observation limit, not
                # a framing/correlation error; a pending waiter still fails.
                errors = (
                    errors + 1
                    if not outcome.report["opening_context"]["eligible"]
                    or outcome.stop not in ("observation_budget", "peer_eof")
                    or outcome.emission_stop not in (None, "terminal_close_h2")
                    else 0
                )
                if (
                    outcome.stop in ("authorization_required", "opening_rejected")
                    or errors >= 2
                ):
                    stop_campaign = True
                    break
            if stop_campaign:
                break
        if stop_campaign:
            break
    eligible = [s for s in sessions if s["opening_context"]["eligible"]]
    gaps = [
        t["h1"]["completion_gaps_seconds"]["median"]
        for t in eligible
        if t["h1"]["completion_gaps_seconds"]["median"] is not None
    ]
    report = {
        "schema": 2,
        "campaign_mode": mode,
        "planned_sessions": planned,
        "executed_sessions": len(sessions),
        "eligible_sessions": len(eligible),
        "excluded_sessions": len(sessions) - len(eligible),
        "opening_context_counts": dict(
            Counter(s["opening_context"]["status"] for s in sessions)
        ),
        "complete_windows": sum(not s["partial"] for s in eligible),
        "stopped_early": stop_campaign,
        "boundary_proven": False,
        "median_client_gap_distribution_seconds": distribution(gaps),
        "received_size_distribution_bytes": distribution(
            [s["rx_bytes"] for s in eligible]
        ),
        "h1_status_counts": dict(Counter(s["h1"]["status"] for s in eligible)),
        "h2_status_counts": dict(Counter(s["h2"]["status"] for s in eligible)),
        "comparison_counts": dict(Counter(s["comparison"] for s in eligible)),
        "sessions": sessions,
    }
    private_json(directory / "campaign.json", report)
    return report
