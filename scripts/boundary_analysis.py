"""Offline H1/H2 annotations for #48; never a production boundary detector.

H2 deliberately assumes a 48-byte opening. Even complete suffix coverage cannot
prove that assumption. Raw captures are owned separately and never modified.
"""

from collections import Counter
from dataclasses import dataclass, field
from statistics import median

from custom_components.hoben.modbus import decode_mbap, modbus_tcp_frame_size
from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, decode_opened_client
from custom_components.hoben.profiles import StoveProfile, select_stove_profile

PAUSE_THRESHOLDS = (0.05, 0.2, 1.0)
REPLAY_SIZES = (1, 48, 257)


@dataclass(frozen=True)
class RxRead:
    """Client-observed times and actual stream ranges, without captured bytes."""

    index: int
    offset: int
    requested: int
    returned: int
    started: float
    ended: float
    previous_end: float | None

    def metadata(self) -> dict:
        """Record reader inactivity and completion spacing, never server time."""
        return {
            "index": self.index,
            "offset": self.offset,
            "requested": self.requested,
            "returned": self.returned,
            "started": self.started,
            "ended": self.ended,
            "reader_gap": None
            if self.previous_end is None
            else self.started - self.previous_end,
            "completion_gap": None
            if self.previous_end is None
            else self.ended - self.previous_end,
        }


@dataclass(frozen=True)
class CandidateFrame:
    """An attribution under H2 only; bytes/PDU are private, including in repr."""

    category: str
    offset: int
    length: int
    adu: bytes = field(default=b"", repr=False)

    def annotation(self) -> dict:
        """Byte coverage without metadata, register values or arbitrary payloads."""
        return {"category": self.category, "offset": self.offset, "length": self.length}


class H2Framer:
    """Experimental framing at an explicitly assumed offset, without resynchronization.

    Completed frames preceding an error are retained as annotations. An error
    permanently stops interpretation; the independent collector still saves RX.
    CloseClient is terminal, not a universal two-byte frame: all its remaining
    bytes stay opaque. No runtime client imports this tool.
    """

    def __init__(self, offset: int) -> None:
        self.offset = offset
        self.buffer = bytearray()
        self.frames: list[CandidateFrame] = []
        self.error: str | None = None
        self.terminal = False

    def __repr__(self) -> str:
        return f"H2Framer(offset={self.offset}, error={self.error!r})"

    @property
    def partial_frame(self) -> bool:
        """An already received candidate must finish before any new request."""
        return bool(self.buffer) and not self.error and not self.terminal

    def feed(self, data: bytes) -> list[CandidateFrame]:
        """Use existing bounded MBAP codecs; never search for a plausible marker."""
        if self.error or self.terminal:
            return []
        self.buffer.extend(data)
        emitted = []
        while self.buffer:
            kind = self.buffer[0]
            if kind == 0x05:
                self.terminal = True
                break
            if kind == 0x0A:
                length, prefix, category = 1, 1, "ping_h2"
            elif kind in (0x0E, 0x1B):
                prefix = 1 if kind == 0x0E else 5
                category = "response_h2" if kind == 0x0E else "notification_h2"
                if len(self.buffer) < prefix + 6:
                    break
                try:
                    length = prefix + modbus_tcp_frame_size(bytes(self.buffer[prefix:]))
                except (TypeError, ValueError):
                    self.error = "invalid_mbap_h2"
                    break
                if len(self.buffer) < length:
                    break
                try:
                    decode_mbap(bytes(self.buffer[prefix:length]))
                except (TypeError, ValueError):
                    self.error = "invalid_mbap_h2"
                    break
            else:
                self.error = "unsupported_type_h2"
                break
            event = CandidateFrame(
                category,
                self.offset,
                length,
                bytes(self.buffer[prefix:length]) if kind != 0x0A else b"",
            )
            del self.buffer[:length]
            self.offset += length
            self.frames.append(event)
            emitted.append(event)
        return emitted

    def report(self, suffix_size: int) -> dict:
        """Report compatibility, never confirmed framing or a proven boundary."""
        covered = sum(f.length for f in self.frames)
        status = (
            "contradicted"
            if self.error
            else "compatible"
            if suffix_size and covered == suffix_size
            else "inconclusive"
        )
        return {
            "attribution": "under_h2_only",
            "status": status,
            "covered_bytes": covered,
            "unattributed_bytes": suffix_size - covered,
            "frame_counts": dict(
                sorted(Counter(f.category for f in self.frames).items())
            ),
            "anomaly": self.error or ("terminal_close_h2" if self.terminal else None),
            "anomaly_offset": self.offset if self.error or self.terminal else None,
            "partial_frame": self.partial_frame,
        }


def distribution(values: list[float]) -> dict:
    """Bounded numeric client timing summary; no untrusted strings."""
    return {
        "count": len(values),
        "min": round(min(values), 6) if values else None,
        "median": round(median(values), 6) if values else None,
        "max": round(max(values), 6) if values else None,
    }


def h1_analysis(reads: list[RxRead], opening_offset: int | None) -> dict:
    """Annotate all preselected pause thresholds using original client timings.

    A regrouped read or no later bytes is inconclusive about a server pause.
    Synthetic re-chunking must not fabricate times or improve this evidence.
    """
    populated = [r for r in reads if r.returned]
    gaps = [max(0.0, b.ended - a.ended) for a, b in zip(populated, populated[1:])]
    result = {
        "status": "inconclusive",
        "timing_source": "client_read_completions",
        "completion_gaps_seconds": distribution(gaps),
        "first_read_bytes": populated[0].returned if populated else 0,
        "prefix_fragment_bytes": [],
        "thresholds": [],
    }
    if opening_offset is None:
        return result
    prefix_end = opening_offset + 48
    result["prefix_fragment_bytes"] = [
        overlap
        for r in populated
        if (
            overlap := min(r.offset + r.returned, prefix_end)
            - max(r.offset, opening_offset)
        )
        > 0
    ]
    for threshold in PAUSE_THRESHOLDS:
        groups: list[list[RxRead]] = []
        for read in populated:
            if not groups or read.ended - groups[-1][-1].ended >= threshold:
                groups.append([read])
            else:
                groups[-1].append(read)
        candidate = next(
            (
                i
                for i, group in enumerate(groups)
                if group[0].offset
                <= opening_offset
                < group[-1].offset + group[-1].returned
            ),
            None,
        )
        end = (
            groups[candidate][-1].offset + groups[candidate][-1].returned
            if candidate is not None
            else opening_offset
        )
        later_group = candidate is not None and candidate + 1 < len(groups)
        compatible = end >= prefix_end and later_group
        result["thresholds"].append(
            {
                "seconds": threshold,
                "group_count": len(groups),
                "opening_group_bytes": end - opening_offset,
                "bytes_after_prefix_in_group": max(0, end - prefix_end),
                "later_group_observed": later_group,
                "status": "compatible" if compatible else "inconclusive",
            }
        )
    if any(t["status"] == "compatible" for t in result["thresholds"]):
        result["status"] = "compatible"
    return result


def opening_context(
    data: bytes, opening_offset: int | None, *, prefix_accepted: bool
) -> dict:
    """Check the collector's V4 context independently, without exposing identity.

    A valid prefix is necessary but does not establish its total length. No
    marker search or suffix interpretation can turn a rejected context into
    evidence. Acceptance must also have occurred before collection stopped.
    """
    status = "missing_opening"
    if opening_offset is not None:
        if (
            type(opening_offset) is not int
            or not 0 <= opening_offset < len(data)
            or any(value != 0x0A for value in data[:opening_offset])
        ):
            status = "invalid_opening_offset"
        elif len(data) < opening_offset + 48:
            status = "incomplete_opening_prefix"
        else:
            try:
                opened = decode_opened_client(
                    data[opening_offset : opening_offset + 48]
                )
                status = (
                    "unsupported_opening"
                    if select_stove_profile(opened) is not StoveProfile.V4
                    or opened.device_guid == INITIAL_DEVICE_GUID
                    else "accepted_v4_prefix"
                    if prefix_accepted
                    else "unaccepted_opening_prefix"
                )
            except (TypeError, ValueError):
                status = "invalid_opening_prefix"
    return {"eligible": status == "accepted_v4_prefix", "status": status}


def analyze_capture(
    data: bytes,
    reads: list[RxRead],
    opening_offset: int | None,
    *,
    prefix_accepted: bool = True,
) -> dict:
    """Analyze only accepted V4 contexts; direct fixtures still validate raw bytes."""
    context = opening_context(data, opening_offset, prefix_accepted=prefix_accepted)
    h1 = h1_analysis(reads, opening_offset if context["eligible"] else None)
    if not context["eligible"]:
        return {
            "opening_context": context,
            "h1": h1,
            "h2": {"status": "inconclusive"},
            "comparison": "insufficient_data",
        }
    start = opening_offset + 48
    suffix = data[start:]
    framer = H2Framer(start)
    # Preserve original chunk boundaries for one analysis; replay only changes
    # framing input slices, while H1 continues to use actual recorded timings.
    for read in reads:
        left, right = max(start, read.offset), read.offset + read.returned
        if left < right:
            framer.feed(data[left:right])
    h2 = framer.report(len(suffix))
    annotations = [f.annotation() for f in framer.frames]
    replay = []
    for size in REPLAY_SIZES:
        other = H2Framer(start)
        for pos in range(0, len(suffix), size):
            other.feed(suffix[pos : pos + size])
        replay.append(
            {
                "chunk_size": size,
                "same_framing": other.report(len(suffix)) == h2
                and [f.annotation() for f in other.frames] == annotations,
            }
        )
    statuses = (h1["status"], h2["status"])
    comparison = (
        "compatible_with_both"
        if statuses == ("compatible", "compatible")
        else "h2_contradicted"
        if statuses == ("compatible", "contradicted")
        else "neither_model_supported"
        if h2["status"] == "contradicted"
        else "h2_compatible_h1_inconclusive"
        if h2["status"] == "compatible"
        else "insufficient_data"
    )
    return {
        "opening_context": context,
        "h1": h1,
        "h2": h2,
        "replay": replay,
        "comparison": comparison,
    }
