"""D6 injectable evidence ports, exclusively over D4's exact memory transport.

No TLS implementation, socket, CLI, opt-in supplier or network factory exists
here. Fixture layout declarations are synthetic assumptions, not wire framing.
"""

import asyncio
import copy
import json
from collections import deque
from typing import Protocol

from custom_components.hoben.v4_session import SessionState, V4Session, V4SessionMode
from scripts.info_delivery_memory import MemoryFactory, MemoryTransport, OfflineClock
from scripts.info_delivery_supervisor import LIMITS, validate_supervision_report

LAYOUTS = {"unknown", "isolated_fixture", "fragmented_fixture", "coalesced_fixture"}
ERRORS = {
    "none",
    "owner_unproven",
    "generation_changed",
    "unregistered_delivery",
    "ambiguous_delivery",
    "partial_frame",
    "quarantine",
    "delivery_budget",
    "multiple_requests",
    "unconsumed_delivery",
    "cleanup_unproven",
    "worker_failed",
    "correlation_unproven",
}
CONSTANTS = {
    "schema": 1,
    "scenario": "info-memory-tls-adapter",
    "mode": "offline",
    "proof_scope": "synthetic_memory_ports",
    "tls_provenance": "not_proven",
    "process_reap": "not_proven",
    "info_framing": "INCONCLUSIVE",
    "boundary_proven": False,
}


class InvalidTlsAdapter(ValueError):
    def __init__(self):
        super().__init__("invalid_offline_info_tls_adapter")


def need(condition):
    if not condition:
        raise InvalidTlsAdapter()


class PlaintextDeliveryPort(Protocol):
    def delivered(self, data: bytes) -> None: ...


class V4OwnerPort(Protocol):
    def allow_v4_read(self) -> bool: ...


class CleanupWitnessPort(Protocol):
    def finish(self, worker_report: dict) -> dict: ...


class MemoryInfoPorts:
    """One-use memory-only implementation of the three evidence ports.

    The fixture alone supplies session/capability and declares delivery layout.
    Generic Protocol implementations cannot be passed to D4's strict entry point.
    """

    def __init__(self, *, session, clock):
        need(type(session) is V4Session and type(clock) is OfflineClock)
        need(session.state is SessionState.DISCONNECTED)
        need(session._mode is V4SessionMode.PERSISTENT)
        need(session.verified_read_sequence == 0)
        factory = session._transport_factory
        need(type(factory) is MemoryFactory and factory.calls == 0)
        wire = factory.transport
        need(type(wire) is MemoryTransport and wire.session is None)
        need(wire._ports_claim is None and wire._delivery_port is None)
        self.session, self.clock, self.factory, self.wire = (
            session,
            clock,
            factory,
            wire,
        )
        wire._ports_claim = self
        self._bound = False
        self._owner_consistent = self._generation_consistent = True
        self._rx = None
        self._pending = deque()
        self._layouts = dict.fromkeys(sorted(LAYOUTS), 0)
        self._count = self._bytes = self._max_bytes = self._permits = 0
        self._first_error = "none"
        self._terminal = None

    def __repr__(self):
        return "MemoryInfoPorts()"

    @property
    def failed(self):
        return self._first_error != "none"

    def _deny(self, reason):
        if not self.failed:
            self._first_error = reason

    def bind(self, session, clock):
        need(not self._bound and self._terminal is None)
        need(session is self.session and clock is self.clock)
        need(self.factory.calls == 0 and self.wire._ports_claim is self)
        need(self.wire._delivery_port is None)
        self._bound = True

    def feed_memory(self, data, *, layout="unknown", generation=1):
        """Queue a synthetic delivery; never infer layout from a byte pattern."""
        need(self._terminal is None and not self.wire.closed)
        need(type(data) is bytes and len(data) <= 4096)
        need(type(layout) is str and layout in LAYOUTS)
        need(type(generation) is int and 0 <= generation <= 2)
        need(len(self._pending) < 32 and not self.wire.queue.full())
        need(self.wire.queue.qsize() == len(self._pending))
        # Keep the exact queued object's identity until read, not a raw export
        # or duplicated payload. Metadata alone cannot create a received event.
        self._pending.append((data, layout, generation))
        self.wire.feed(data)

    def delivered(self, data):
        """Called by the real memory read owner, before handing bytes to RX."""
        need(type(data) is bytes and len(data) <= 4096)
        s, w = self.session, self.wire
        need(self._terminal is None)
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if (
            not self._bound
            or w._delivery_port is not self
            or w.session is not s
            or current is not s._rx_task
            or w.active_reads != 1
            or s._transport is not w
            or s.state is not SessionState.CONNECTED
        ):
            self._owner_consistent = False
            self._deny("owner_unproven")
        if self._rx is None:
            self._rx = current
        elif self._rx is not current:
            self._owner_consistent = False
            self._deny("owner_unproven")
        layout, generation = "unknown", 0
        if self._pending:
            queued, layout, generation = self._pending.popleft()
            if queued is not data:
                self._deny("unregistered_delivery")
                layout = "unknown"
        else:
            self._deny("unregistered_delivery")
        self._count += 1
        self._bytes += len(data)
        self._max_bytes = max(self._max_bytes, len(data))
        self._layouts[layout] += 1
        if self._count > 256:
            self._deny("delivery_budget")
        if (
            generation != 1
            or w.connect_count != 1
            or self.factory.calls != 1
            or s._transport_factory is not self.factory
        ):
            self._generation_consistent = False
            self._deny("generation_changed")
        if layout != "isolated_fixture":
            self._deny("ambiguous_delivery")
        if s._framer.partial:
            self._deny("partial_frame")
        if s._data_updated.active:
            self._deny("quarantine")

    def allow_v4_read(self):
        s, w = self.session, self.wire
        child = w.scenario
        if self.failed:
            return False
        if (
            s._transport is not w
            or s._rx_task is not self._rx
            or s._transport_factory is not self.factory
            or w.connect_count != 1
        ):
            self._deny("owner_unproven")
        elif (
            child is None
            or not child.drops
            or child.steps["pong"] is None
            or self._layouts["isolated_fixture"] != self._count
        ):
            self._deny("correlation_unproven")
        elif self._permits:
            self._deny("multiple_requests")
        else:
            self._permits = 1
        return not self.failed

    def finish(self, worker_report):
        if self._terminal is not None:
            return copy.deepcopy(self._terminal)
        worker = validate_supervision_report(worker_report)
        need(self._bound)
        s, w = self.session, self.wire
        owner = bool(
            self._owner_consistent
            and w.session is s
            and w._ports_claim is self
            and w._delivery_port is self
            and s._transport_factory is self.factory
            and (self._rx is None or s._rx_task is self._rx)
        )
        generation = (
            self._generation_consistent and self.factory.calls == w.connect_count == 1
        )
        clean = bool(
            s.cleanup_succeeded
            and s.state is SessionState.CLOSED
            and w.closed
            and w.close_count == 1
            and s._rx_task is not None
            and s._rx_task.done()
            and not s._operations
            and not s._tx_operations
            and w.active_reads == w.active_tx == 0
            and worker["cleanup_attested"]
            and worker["worker_reaped"]
        )
        if not owner:
            self._deny("owner_unproven")
        if not generation:
            self._deny("generation_changed")
        if self._count != w.plaintext_deliveries or self._bytes != w.plaintext_bytes:
            self._deny("unregistered_delivery")
        pending = len(self._pending)
        if pending:
            self._deny("unconsumed_delivery")
        if not clean:
            self._deny("cleanup_unproven")
        actual, observation = w.scenario, worker["observation"]
        if worker["result"] in {"SUCCESS", "INCONCLUSIVE"} and (
            actual is None
            or observation is None
            or observation["info_discarded"] != actual.drops
            or observation["reads_after_drop"] != actual.reads
            or observation["info_delivery_bytes"] != actual.sizes
            or observation["first_error"] != actual.first_error
        ):
            self._deny("correlation_unproven")
        if s._rx_error is not None:
            self._deny("worker_failed")
        if worker["result"] not in {"SUCCESS", "INCONCLUSIVE"}:
            self._deny("worker_failed")
        if worker["result"] == "SUCCESS" and (
            self._permits != 1 or s.verified_read_sequence != 1
        ):
            self._deny("correlation_unproven")
        report = {
            **CONSTANTS,
            "limits": dict(LIMITS),
            "worker": worker,
            "same_owner": owner,
            "same_generation": generation,
            "cleanup_attested": clean,
            "delivery_count": self._count,
            "delivery_bytes": self._bytes,
            "max_delivery_bytes": self._max_bytes,
            "layouts": dict(self._layouts),
            "read_permits": self._permits,
            "verified_reads": s.verified_read_sequence,
            "pending_deliveries": pending,
            "first_error": self._first_error,
        }
        report["result"], report["reason"] = verdict(report)
        self._terminal = validate_adapter_report(report)
        self._pending.clear()
        w._delivery_port = w._ports_claim = None
        return copy.deepcopy(self._terminal)


def verdict(report):
    if report["first_error"] != "none":
        return "FAILURE", report["first_error"]
    if not report["same_owner"] or not report["same_generation"]:
        return "FAILURE", "owner_unproven"
    if not report["cleanup_attested"]:
        return "FAILURE", "cleanup_unproven"
    if (
        report["pending_deliveries"]
        or report["layouts"]["isolated_fixture"] != report["delivery_count"]
    ):
        return "FAILURE", "ambiguous_delivery"
    worker = report["worker"]
    if worker["result"] == "SUCCESS":
        if report["read_permits"] == report["verified_reads"] == 1:
            return "SUCCESS", "post_drop_read_verified"
        return "FAILURE", "correlation_unproven"
    if worker["result"] == "INCONCLUSIVE":
        return "INCONCLUSIVE", "info_absent"
    return "FAILURE", "worker_failed"


def validate_adapter_report(report):
    """Scalar consistency only; no authentication or grant to run live code."""
    try:
        counters = {
            "delivery_count": 256,
            "delivery_bytes": 1_048_576,
            "max_delivery_bytes": 4096,
            "read_permits": 1,
            "verified_reads": 1,
            "pending_deliveries": 32,
        }
        booleans = {"same_owner", "same_generation", "cleanup_attested"}
        keys = (
            set(CONSTANTS)
            | set(counters)
            | booleans
            | {
                "limits",
                "worker",
                "layouts",
                "first_error",
                "result",
                "reason",
            }
        )
        need(type(report) is dict and report.keys() == keys)
        for k, v in CONSTANTS.items():
            need(type(report[k]) is type(v) and report[k] == v)
        need(type(report["limits"]) is dict and report["limits"] == LIMITS)
        need(all(type(v) is int for v in report["limits"].values()))
        for k in booleans:
            need(type(report[k]) is bool)
        for k, high in counters.items():
            need(type(report[k]) is int and 0 <= report[k] <= high)
        layout = report["layouts"]
        need(type(layout) is dict and layout.keys() == LAYOUTS)
        need(all(type(n) is int and 0 <= n <= 256 for n in layout.values()))
        need(sum(layout.values()) == report["delivery_count"])
        need(report["max_delivery_bytes"] <= report["delivery_bytes"])
        need(report["delivery_bytes"] <= report["delivery_count"] * 4096)
        if not report["delivery_count"]:
            need(report["max_delivery_bytes"] == 0)
        need(type(report["first_error"]) is str and report["first_error"] in ERRORS)
        worker = validate_supervision_report(report["worker"])
        observation = worker["observation"]
        if worker["result"] == "SUCCESS":
            need(observation is not None)
            need(
                report["delivery_count"]
                >= observation["info_discarded"]
                + observation["pings_after_drop"]
                + observation["reads_after_drop"]
            )
            need(report["delivery_bytes"] >= sum(observation["info_delivery_bytes"]))
        if report["cleanup_attested"]:
            need(worker["cleanup_attested"] and worker["worker_reaped"])
        need(type(report["result"]) is str and type(report["reason"]) is str)
        need((report["result"], report["reason"]) == verdict(report))
        need(len(json.dumps(report, separators=(",", ":")).encode()) <= 8192)
        return copy.deepcopy(report)
    except Exception:
        raise InvalidTlsAdapter() from None
