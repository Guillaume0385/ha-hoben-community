"""Pure protocol planning references. No runnable commands or live authority."""

from dataclasses import dataclass, field, replace
from types import MappingProxyType

CHOICES = (
    "tls-only",
    "session-open",
    "read-v4-state",
    "h1h2",
    "session-300",
    "session-reconnect",
    "all",
)
OUTCOMES = ("SUCCESS", "FAILURE", "INCONCLUSIVE", "NOT RUN")
_ALL = ("h1h2", "session-300", "session-reconnect")


@dataclass(frozen=True)
class Stage:
    """Immutable citations/ceilings; references are never imported or invoked."""

    name: str
    readiness: str
    references: tuple[str, ...]
    historical_limits: tuple[tuple[str, int | None], ...]
    possible_outcomes: tuple[str, ...]
    completion_outcomes: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    excluded_references: tuple[str, ...] = ()
    execution: str = field(default="NOT RUN", init=False)
    can_start: bool = field(default=False, init=False)

    def __bool__(self):
        return False


_STAGES = MappingProxyType(
    {
        "tls-only": Stage(
            "tls-only",
            "review_required",
            (
                "scripts/probe_hoben_connection.py",
                "custom_components/hoben/transport.py",
            ),
            (("process_seconds", None),),
            ("NOT RUN",),
        ),
        "session-open": Stage(
            "session-open",
            "review_required",
            ("scripts/probe_hoben_connection.py", "custom_components/hoben/session.py"),
            (("process_seconds", None), ("max_opens", 1)),
            ("NOT RUN",),
        ),
        "read-v4-state": Stage(
            "read-v4-state",
            "review_required",
            ("scripts/probe_hoben_connection.py", "custom_components/hoben/v4_read.py"),
            (
                ("process_seconds", None),
                ("max_opens", 1),
                ("max_reads", 1),
                ("register_count", 20),
            ),
            ("NOT RUN",),
        ),
        "h1h2": Stage(
            "h1h2",
            "reference_only",
            (
                "scripts/run_manual_hoben.py",
                "scripts/run_experimental_boundary.py",
                "scripts/boundary_capture.py",
                "scripts/boundary_analysis.py",
            ),
            (
                ("process_seconds", 1800),
                ("per_session_seconds", 90),
                ("h1_sessions", 6),
                ("h2_sessions", 6),
                ("rx_bytes_per_session", 1048576),
            ),
            ("FAILURE", "INCONCLUSIVE", "NOT RUN"),
            ("INCONCLUSIVE",),
        ),
        "session-300": Stage(
            "session-300",
            "reference_only",
            (
                "scripts/run_manual_hoben.py",
                "scripts/run_session_300.py",
                "custom_components/hoben/v4_experiment.py",
                "custom_components/hoben/v4_lifecycle.py",
                "custom_components/hoben/v4_session.py",
            ),
            (
                ("process_seconds", 360),
                ("useful_seconds", 300),
                ("max_opens", 3),
                ("max_reads", 6),
                ("read_interval_seconds", 60),
                ("rx_bytes_total", 1048576),
            ),
            OUTCOMES,
            ("SUCCESS",),
        ),
        "session-reconnect": Stage(
            "session-reconnect",
            "not_implemented",
            (),
            # Historical artificial scenario ceilings only, NOT a natural runtime.
            (
                ("process_seconds", 600),
                ("functional_seconds", 360),
                ("max_opens", 3),
                ("max_reads", 10),
                ("rx_bytes_total", 1048576),
                ("stable_seconds", 120),
            ),
            ("NOT RUN",),
            excluded_references=(
                "scripts/session_suite.py",
                "custom_components/hoben/v4_no_pong.py",
                "scripts/session_natural_900.py",
            ),
        ),
    }
)


@dataclass(frozen=True)
class ProtocolPlan:
    selection: str | None
    stages: tuple[Stage, ...]
    historical_limits: tuple[tuple[str, int | None], ...]
    reason: str
    execution: str = field(default="NOT RUN", init=False)
    can_start: bool = field(default=False, init=False)

    def __bool__(self):
        return False


@dataclass(frozen=True)
class Transition:
    """Consistency of supplied fixtures, never permission or an ACK emitter."""

    pending_step: str | None
    prerequisites_consistent: bool
    reason: str
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)
    can_start: bool = field(default=False, init=False)

    def __bool__(self):
        return False


def build_plan(selection):
    """Only seven closed choices; unknown input is not echoed or defaulted."""
    if type(selection) is not str or selection not in CHOICES:
        return ProtocolPlan(None, (), (), "unknown_choice")
    names = _ALL if selection == "all" else (selection,)
    stages = tuple(
        replace(_STAGES[name], depends_on=() if i == 0 else (names[i - 1],))
        for i, name in enumerate(names)
    )
    limits = (
        (("process_seconds", 2820), ("session_suite_seconds", 1020))
        if selection == "all"
        else stages[0].historical_limits
    )
    return ProtocolPlan(selection, stages, limits, "offline_only")


def _closed(value, names):
    expected = set(names.split())
    return (
        type(value) is dict
        and len(value) == len(expected)
        and all(type(k) is str for k in value)
        and value.keys() == expected
    )


def assess_transition(selection, evidence):
    """Inspect a completed prefix and next-phase receipts; never start a step.

    Flags represent normalized, externally attested fixtures. This function
    neither authenticates those flags nor supplies an actual admission result.
    """
    plan = build_plan(selection)
    if plan.selection is None:
        return Transition(None, False, "unknown_choice")
    pending = plan.stages[0].name
    try:
        if not _closed(
            evidence,
            "selection admission_attested next_step next_deadline_armed "
            "next_ack completed",
        ):
            return Transition(pending, False, "invalid_evidence")
        if (
            type(evidence["selection"]) is not str
            or evidence["selection"] != selection
            or evidence["admission_attested"] is not True
        ):
            return Transition(pending, False, "preconditions_unattested")
        receipts = evidence["completed"]
        if type(receipts) is not list or len(receipts) > len(plan.stages):
            return Transition(pending, False, "invalid_evidence")
        for stage, proof in zip(plan.stages, receipts):
            pending = stage.name
            if not _closed(
                proof,
                "step attested deadline_armed ack process_ok cleanup_ok "
                "report_valid collection_complete limits_respected outcome",
            ):
                return Transition(pending, False, "invalid_evidence")
            if type(proof["step"]) is not str or proof["step"] != stage.name:
                return Transition(pending, False, "invalid_prefix")
            if stage.readiness != "reference_only":
                return Transition(pending, False, stage.readiness)
            if not all(
                proof[k] is True
                for k in (
                    "attested",
                    "deadline_armed",
                    "ack",
                    "process_ok",
                    "cleanup_ok",
                    "report_valid",
                    "collection_complete",
                    "limits_respected",
                )
            ):
                return Transition(pending, False, "prefix_unattested")
            if (
                type(proof["outcome"]) is not str
                or proof["outcome"] not in stage.completion_outcomes
            ):
                return Transition(pending, False, "prefix_not_admissible")
        index = len(receipts)
        pending = plan.stages[index].name if index < len(plan.stages) else None
        if (
            type(evidence["next_step"]) is not type(pending)
            or evidence["next_step"] != pending
        ):
            return Transition(pending, False, "invalid_prefix")
        if pending is None:
            if (
                evidence["next_deadline_armed"] is not False
                or evidence["next_ack"] is not False
            ):
                return Transition(None, False, "invalid_evidence")
            return Transition(None, True, "prefix_complete")
        if (
            evidence["next_deadline_armed"] is not True
            or evidence["next_ack"] is not True
        ):
            return Transition(pending, False, "preconditions_unattested")
        stage = plan.stages[index]
        if stage.readiness != "reference_only":
            return Transition(pending, False, stage.readiness)
        return Transition(pending, True, "offline_only")
    except Exception:
        return Transition(pending, False, "invalid_evidence")


if __name__ == "__main__":
    raise SystemExit(1)  # no CLI, scheduler or successful process-level permit
