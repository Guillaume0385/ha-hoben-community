"""Disconnected #186 bench; static APK observations, never a wire decoder.

Sources and exclusions: docs/tls-read-candidate-offline-186.md. No TX, sockets,
retry, identity, register values, or production entry point belong here.
"""

import asyncio
import json
from collections import deque

from custom_components.hoben.exceptions import HobenFrameBoundaryError
from custom_components.hoben.transport import TransportEOF, TransportTlsError
from custom_components.hoben.v4_experiment import ExperimentalV4Framer

# Independently invented read response, not an APK/server capture.
RESPONSE = bytes.fromhex("0effff0000002b010428") + b"\x00\x00" * 20
PING = b"\x0a"
INVALID_UPDATED = b"\x1b" + b"\x00" * 4 + bytes.fromhex("ffff0000ffff")
RE_HEAD = "e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e"
# APK ManageOpened allocates 512 bytes (06000C21:0108–0120). A comparison
# completion must fit both readers; HA's 4096-byte read capacity is not framing.
MAX_COMPLETION_BYTES = 512


class MemoryCompletions:
    """Exactly one prescribed plaintext completion per read; no resegmentation."""

    def __init__(self, deliveries):
        if len(deliveries) > 64 or any(
            not (type(item) is bytes and len(item) <= MAX_COMPLETION_BYTES)
            and type(item) not in (TransportEOF, TransportTlsError)
            for item in deliveries
        ):
            raise ValueError("invalid_synthetic_deliveries")
        self.items = deque(deliveries)
        self.sizes = []

    async def read(self):
        await asyncio.sleep(0)
        item = self.items.popleft()
        if isinstance(item, Exception):
            raise item
        self.sizes.append(len(item))
        return item


def side_report():
    return {
        "events": [],
        "dispatch_count": 0,
        "pings": 0,
        "decoder_attempts": 0,
        "complete_responses": 0,
        "correlated_reads": "not_executed",
        "guard": "none",
        "rx_state": "not_established",
    }


class ApkCandidateModel:
    """Only selected proven ReadLoopAsync branches; no UI/decoder emulation."""

    def __init__(self):
        self.report = side_report()
        self.timeout_count = 0
        self.expected_read_attempts = 0

    def note(self, event, size=0, subcode=None):
        item = {"event": event, "delivery_bytes": size}
        if subcode is not None:
            item["synthetic_subcode"] = subcode
        self.report["events"].append(item)

    def delivery(self, data):
        size = len(data)
        if not size:
            self.note("zero_read_fallthrough")
        elif data[0] == 10:
            self.report["pings"] += 1
            self.report["dispatch_count"] += 1
            self.note("ping_decision_no_tx", size)
        elif size > 1 and data[0] == 12:
            code = data[1]
            if code == 2:
                self.timeout_count += 1
            if code == 4 or code == 2 and self.timeout_count <= 3:
                self.expected_read_attempts += 1
                self.note("logical_read_decision_no_tx", size, code)
            elif code in (0, 1, 5, 6) or code == 2:
                self.report["dispatch_count"] += 1
                self.note("forward_entire_delivery", size, code)
            else:
                self.note("info_fallthrough", size, code)
        elif size > 1 and data[0] == 5:
            self.report["dispatch_count"] += 1
            self.report["rx_state"] = "cancel_requested_model_only"
            self.note("close_forward_entire_delivery", size)
        elif size > 2 and data[0] in (7, 14, 27):
            # Take(n)/Skip(1 or 5), not a proof of decoded/correlated success.
            self.report["decoder_attempts"] += 1
            self.note("decoder_candidate_outcome_unknown", size)
        else:
            self.note("fallthrough", size)

    def exception(self):
        # Local Info/03 creation is distinct from receipt of wire Info/03.
        self.note("local_server_timeout", subcode=3)
        self.report["guard"] = "read_exception"
        self.report["rx_state"] = "cancel_requested_model_only"


async def apk_observation(deliveries):
    memory, model = MemoryCompletions(deliveries), ApkCandidateModel()
    while memory.items:
        try:
            model.delivery(await memory.read())
        except (TransportEOF, TransportTlsError):
            model.exception()
        if model.report["rx_state"] == "cancel_requested_model_only":
            break
    model.report["delivery_bytes"] = memory.sizes
    model.report["logical_read_decisions"] = model.expected_read_attempts
    return model.report


async def ha_observation(deliveries):
    """Actual framer only: neither RX lifecycle nor decoded success is invented."""
    memory, report = MemoryCompletions(deliveries), side_report()
    framer = ExperimentalV4Framer(
        classify_frame_boundary=True, recover_data_updated=True
    )
    exchange = object()
    while memory.items:
        try:
            data = await memory.read()
        except (TransportEOF, TransportTlsError) as error:
            report["guard"] = "tls_error" if type(error) is TransportTlsError else "eof"
            if type(error) is TransportEOF and framer.partial:
                report["partial_eof_provenance"] = (
                    framer.incomplete_error().safe_report()["frame_boundary_provenance"]
                )
            break
        if not data:
            report["guard"] = "eof"
            if framer.partial:
                report["partial_eof_provenance"] = (
                    framer.incomplete_error().safe_report()["frame_boundary_provenance"]
                )
            break
        try:
            events = framer.feed(data, exchange)
        except HobenFrameBoundaryError as error:
            report["guard"] = error.safe_report()["frame_boundary_provenance"]
            break  # Never skip Info, search a suffix, or feed after rejection.
        if len(report["events"]) + len(events) > 128:
            raise ValueError("synthetic_event_budget")
        for event in events:
            kind = {10: "ping", 14: "response", 5: "close_client"}[event.payload[0]]
            report["events"].append({"event": kind, "frame_bytes": len(event.payload)})
            report["dispatch_count"] += 1
            report["pings"] += int(kind == "ping")
            report["complete_responses"] += int(kind == "response")
        if events and events[-1].payload[0] == 5:
            report["guard"] = "close_client_post_open_hypothesis"
            break  # No drain of a terminal close's unproven suffix.
        if framer.invalid_data_updated is not None:
            report["guard"] = "data_updated_policy_not_executed"
            break  # 30 s session policy belongs to the real RX, not this model.
    report["delivery_bytes"] = memory.sizes
    report["partial"] = framer.partial
    report["rx_state"] = "lifecycle_not_executed"
    return report


async def compare(deliveries):
    """Same immutable plan, independent consumers; rejection can stop HA earlier."""
    deliveries = tuple(deliveries)
    return {
        "synthetic": True,
        "source": "prescribed_plaintext_read_completion",
        "size_unit": "bytes",
        "re_head": RE_HEAD,
        "info_total_bytes": "not_proven",
        "boundary_proven": False,
        "apk": await apk_observation(deliveries),
        "ha": await ha_observation(deliveries),
    }


def bounded_json(report):
    """Closed test report schema: refuse extensions or arbitrary exception text."""
    constants = {
        "synthetic": True,
        "source": "prescribed_plaintext_read_completion",
        "size_unit": "bytes",
        "re_head": RE_HEAD,
        "info_total_bytes": "not_proven",
        "boundary_proven": False,
    }
    allowed_strings = {
        "correlated_reads": {"not_executed"},
        "guard": {
            "none",
            "read_exception",
            "eof",
            "tls_error",
            "unsupported_type",
            "unknown_type",
            "invalid_mbap",
            "close_client_post_open_hypothesis",
            "data_updated_policy_not_executed",
        },
        "rx_state": {
            "not_established",
            "cancel_requested_model_only",
            "lifecycle_not_executed",
        },
        "partial_eof_provenance": {"partial_eof"},
    }
    event_names = {
        "zero_read_fallthrough",
        "ping_decision_no_tx",
        "logical_read_decision_no_tx",
        "forward_entire_delivery",
        "info_fallthrough",
        "close_forward_entire_delivery",
        "decoder_candidate_outcome_unknown",
        "fallthrough",
        "local_server_timeout",
        "ping",
        "response",
        "close_client",
    }

    def number(value, limit=262144):
        return type(value) is int and 0 <= value <= limit

    valid = type(report) is dict and set(report) == set(constants) | {"apk", "ha"}
    valid = valid and all(
        type(report[k]) is type(v) and report[k] == v for k, v in constants.items()
    )
    for side in ("apk", "ha") if valid else ():
        value = report[side]
        keys = set(side_report()) | {"delivery_bytes"}
        keys |= {"logical_read_decisions"} if side == "apk" else {"partial"}
        if type(value) is not dict or set(value) - {"partial_eof_provenance"} != keys:
            valid = False
            break
        for key, item in value.items():
            if key in allowed_strings:
                valid &= type(item) is str and item in allowed_strings[key]
            elif key == "partial":
                valid &= type(item) is bool
            elif key == "delivery_bytes":
                valid &= (
                    type(item) is list
                    and len(item) <= 64
                    and all(number(n, MAX_COMPLETION_BYTES) for n in item)
                )
            elif key == "events":
                if type(item) is not list or len(item) > 128:
                    valid = False
                    break
                for event in item:
                    valid &= type(event) is dict and set(event) in (
                        {"event", "delivery_bytes"},
                        {"event", "delivery_bytes", "synthetic_subcode"},
                        {"event", "frame_bytes"},
                    )
                    if not valid:
                        break
                    valid &= (
                        type(event["event"]) is str
                        and event["event"] in event_names
                        and all(
                            number(v, 255 if k == "synthetic_subcode" else 4096)
                            for k, v in event.items()
                            if k != "event"
                        )
                    )
            else:
                valid &= number(item)
    if not valid:
        raise ValueError("invalid_synthetic_report")
    encoded = json.dumps(report, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode()) > 8192:
        raise ValueError("synthetic_report_budget")
    return encoded
