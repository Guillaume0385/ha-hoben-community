"""Pure HA planning references. No HA import, collector or execution authority."""

from dataclasses import dataclass, field
from types import MappingProxyType

CHOICES = (
    "hoben-live",
    "open-errors",
    "refresh-v4",
    "session-reuse",
    "session-reconnect",
    "cleanup",
    "availability",
    "all",
)
STATUSES = ("SUCCESS", "FAILURE", "INCONCLUSIVE", "NOT RUN")
LOSS_KINDS = ("none", "local_stop", "close_client", "eof", "transport_error", "unknown")
_FIRST_LIMITS = (
    ("useful_seconds", 300),
    ("process_seconds", 360),
    ("collection_seconds", 330),
    ("memory_bytes", 1073741824),
    ("max_pids", 128),
    ("max_refreshes", 6),
    ("max_opens", 2),
    ("report_bytes", 8192),
)
_REFERENCES = MappingProxyType(
    {
        "hoben-live": (
            "scripts/launch_ha_manual_live.py",
            "scripts/ha_session_supervisor.py",
            "scripts/ha_session_guard.py",
            "scripts/ha_session_live_worker.py",
            "scripts/ha_session_observer.py",
            "custom_components/hoben/client.py",
            "custom_components/hoben/coordinator.py",
            "custom_components/hoben/v4_lifecycle.py",
            "custom_components/hoben/v4_session.py",
        ),
        "open-errors": (
            "custom_components/hoben/client.py",
            "custom_components/hoben/coordinator.py",
            "custom_components/hoben/config_flow.py",
            "ha_tests/test_config_flow.py",
            "ha_tests/test_reauth.py",
            "ha_tests/test_runtime.py",
        ),
        "refresh-v4": (
            "custom_components/hoben/client.py",
            "custom_components/hoben/coordinator.py",
            "custom_components/hoben/v4_state.py",
            "ha_tests/test_ha_live_observer.py",
        ),
        "session-reuse": (
            "custom_components/hoben/client.py",
            "custom_components/hoben/v4_lifecycle.py",
            "ha_tests/test_persistent_client.py",
            "ha_tests/test_ha_manual_live_worker.py",
        ),
        "session-reconnect": (
            "custom_components/hoben/client.py",
            "custom_components/hoben/v4_lifecycle.py",
            "custom_components/hoben/v4_session.py",
            "ha_tests/test_persistent_client.py",
            "ha_tests/test_ha_live_observer.py",
            "tests/test_session_close_client.py",
        ),
        "cleanup": (
            "custom_components/hoben/client.py",
            "custom_components/hoben/__init__.py",
            "ha_tests/test_runtime.py",
            "tests/test_ha_session_supervisor.py",
        ),
        "availability": (
            "custom_components/hoben/coordinator.py",
            "ha_tests/test_runtime.py",
            "ha_tests/test_entities.py",
            "ha_tests/test_diagnostics.py",
        ),
    }
)


@dataclass(frozen=True)
class _Offline:
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)
    can_start: bool = field(default=False, init=False)

    def __bool__(self):
        return False


@dataclass(frozen=True)
class HAStage(_Offline):
    """Reuse citations are not dedicated scenario implementations or commands."""

    name: str
    readiness: str
    reuse_references: tuple[str, ...]
    known_limits: tuple[tuple[str, int], ...] | None
    possible_outcomes: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    excluded_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class HAPlan(_Offline):
    selection: str | None
    stages: tuple[HAStage, ...]
    known_limits: tuple[tuple[str, int], ...] | None
    reason: str


@dataclass(frozen=True)
class Transition(_Offline):
    pending_step: str | None
    prerequisites_consistent: bool
    reason: str


def build_plan(selection):
    """Only eight closed choices. No budget default for unimplemented stages."""
    if type(selection) is not str or selection not in CHOICES:
        return HAPlan(None, (), None, "unknown_choice")
    names = CHOICES[:-1] if selection == "all" else (selection,)
    stages = tuple(
        HAStage(
            name=name,
            readiness="historical_reference"
            if name == "hoben-live"
            else "not_implemented",
            reuse_references=_REFERENCES[name],
            known_limits=_FIRST_LIMITS if name == "hoben-live" else None,
            possible_outcomes=("SUCCESS", "FAILURE", "NOT RUN")
            if name == "hoben-live"
            else ("NOT RUN",),
            depends_on=() if i == 0 else (names[i - 1],),
            excluded_references=(
                "scripts/session_suite.py",
                "custom_components/hoben/v4_no_pong.py",
            )
            if name == "session-reconnect"
            else (),
        )
        for i, name in enumerate(names)
    )
    return HAPlan(
        selection,
        stages,
        _FIRST_LIMITS if selection == "hoben-live" else None,
        "offline_only",
    )


def _closed(value, names):
    expected = set(names.split())
    return (
        type(value) is dict
        and len(value) == len(expected)
        and all(type(k) is str for k in value)
        and value.keys() == expected
    )


_NEXT_FLAGS = (
    "next_deadline_armed",
    "next_ack",
    "next_limits_attested",
    "next_cleanup_attested",
)
_PAST_FLAGS = (
    "attested",
    "deadline_armed",
    "ack",
    "limits_respected",
    "process_ok",
    "cleanup_ok",
    "report_valid",
    "collection_complete",
    "continuous_300s",
)


def assess_transition(selection, evidence):
    """Model receipt consistency only; supplied flags are not authenticated."""
    plan = build_plan(selection)
    if plan.selection is None:
        return Transition(None, False, "unknown_choice")
    pending = plan.stages[0].name
    try:
        if not _closed(
            evidence,
            "selection admission_attested next_step completed " + " ".join(_NEXT_FLAGS),
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
        for stage, receipt in zip(plan.stages, receipts):
            pending = stage.name
            if not _closed(
                receipt,
                "step outcome loss_kind reconnection_status " + " ".join(_PAST_FLAGS),
            ):
                return Transition(pending, False, "invalid_evidence")
            if type(receipt["step"]) is not str or receipt["step"] != stage.name:
                return Transition(pending, False, "invalid_prefix")
            if stage.readiness != "historical_reference":
                return Transition(pending, False, "not_implemented")
            if not all(receipt[k] is True for k in _PAST_FLAGS):
                return Transition(pending, False, "prefix_unattested")
            if type(receipt["outcome"]) is not str or receipt["outcome"] != "SUCCESS":
                return Transition(pending, False, "prefix_not_admissible")
            # A continuous historical HA window cannot contain any loss. These
            # normalized labels never infer EOF from CloseClient/local stop.
            if (
                type(receipt["loss_kind"]) is not str
                or receipt["loss_kind"] not in LOSS_KINDS
            ):
                return Transition(pending, False, "loss_unattested")
            if receipt["loss_kind"] != "none":
                return Transition(pending, False, "continuity_not_proven")
            if (
                type(receipt["reconnection_status"]) is not str
                or receipt["reconnection_status"] != "INCONCLUSIVE"
            ):
                return Transition(pending, False, "reconnection_unproven")
        index = len(receipts)
        pending = plan.stages[index].name if index < len(plan.stages) else None
        if (
            type(evidence["next_step"]) is not type(pending)
            or evidence["next_step"] != pending
        ):
            return Transition(pending, False, "invalid_prefix")
        if pending is None:
            if not all(evidence[k] is False for k in _NEXT_FLAGS):
                return Transition(None, False, "invalid_evidence")
            return Transition(None, True, "prefix_complete")
        if not all(evidence[k] is True for k in _NEXT_FLAGS):
            return Transition(pending, False, "preconditions_unattested")
        if plan.stages[index].readiness != "historical_reference":
            return Transition(pending, False, "not_implemented")
        return Transition(pending, True, "offline_only")
    except Exception:
        return Transition(pending, False, "invalid_evidence")


if __name__ == "__main__":
    raise SystemExit(1)  # no runnable planner, collector or admission CLI
