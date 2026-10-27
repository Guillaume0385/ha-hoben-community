"""Protocol plan metadata and synthetic transition receipts, with no runtime."""

import ast
import copy
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from scripts.protocol_campaign_plan import CHOICES, assess_transition, build_plan

ROOT = Path(__file__).resolve().parents[1]
ALL = ("h1h2", "session-300", "session-reconnect")


def proof(step):
    return {
        "step": step,
        "attested": True,
        "deadline_armed": True,
        "ack": True,
        "process_ok": True,
        "cleanup_ok": True,
        "report_valid": True,
        "collection_complete": True,
        "limits_respected": True,
        "outcome": "INCONCLUSIVE" if step == "h1h2" else "SUCCESS",
    }


def evidence(selection="all", count=0):
    names = ALL if selection == "all" else (selection,)
    pending = names[count] if count < len(names) else None
    return {
        "selection": selection,
        "admission_attested": True,
        "next_step": pending,
        "next_deadline_armed": pending is not None,
        "next_ack": pending is not None,
        "completed": [proof(name) for name in names[:count]],
    }


def never_starts(result):
    assert result.execution == "NOT RUN" and result.can_start is False
    assert not bool(result)
    assert "PRIVATE_INPUT" not in repr(result)


def test_choices_match_the_inert_protocol_shell_and_all_has_historical_order():
    shell = yaml.load(
        (ROOT / ".github/workflows/hoben-protocol-manual.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    expected = ("tls-only", "session-open", "read-v4-state", *ALL, "all")
    assert CHOICES == expected
    assert shell["on"]["workflow_dispatch"]["inputs"]["scenario"]["options"] == list(
        expected
    )
    plan = build_plan("all")
    assert tuple(s.name for s in plan.stages) == ALL
    historical = ast.parse((ROOT / "scripts/manual_hoben_context.py").read_text())
    old_plans = next(
        ast.literal_eval(n.value)
        for n in historical.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "PLANS" for t in n.targets)
    )
    assert old_plans["all"] == ALL
    assert tuple(s.depends_on for s in plan.stages) == ((), ("h1h2",), ("session-300",))
    assert dict(plan.historical_limits) == {
        "process_seconds": 2820,
        "session_suite_seconds": 1020,
    }
    never_starts(plan)


@pytest.mark.parametrize("selection", CHOICES)
def test_plans_are_deeply_immutable_and_never_execution_permits(selection):
    plan = build_plan(selection)
    assert type(plan.stages) is tuple and type(plan.historical_limits) is tuple
    with pytest.raises(FrozenInstanceError):
        plan.can_start = True
    for stage in plan.stages:
        never_starts(stage)
        for refs in (stage.references, stage.excluded_references):
            assert type(refs) is tuple
            assert all((ROOT / p).is_file() for p in refs)
        assert type(stage.historical_limits) is tuple
        assert all(type(pair) is tuple for pair in stage.historical_limits)
        with pytest.raises(FrozenInstanceError):
            stage.readiness = "ready"
        with pytest.raises(TypeError):
            stage.historical_limits[0] = ("process_seconds", 99999)
    never_starts(plan)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        1,
        [],
        {},
        b"all",
        "PRIVATE_INPUT",
        "hoben-live",
        "ha-parity",
        "session-reconnect-no-pong",
        "session-natural-900",
    ],
)
def test_unknown_choice_has_no_default_plan_and_echoes_no_input(bad):
    plan = build_plan(bad)
    assert (
        plan.selection is None and plan.stages == () and plan.reason == "unknown_choice"
    )
    never_starts(plan)
    result = assess_transition(bad, {})
    assert result.reason == "unknown_choice" and not result.prerequisites_consistent
    never_starts(result)


@pytest.mark.parametrize("selection", ["tls-only", "session-open", "read-v4-state"])
def test_old_clis_need_review_and_an_unknown_budget_is_not_filled_in(selection):
    stage = build_plan(selection).stages[0]
    assert stage.readiness == "review_required"
    assert dict(stage.historical_limits)["process_seconds"] is None
    assert stage.possible_outcomes == ("NOT RUN",)
    for count in (0, 1):
        result = assess_transition(selection, evidence(selection, count))
        assert (
            result.reason == "review_required" and not result.prerequisites_consistent
        )
        never_starts(result)


def test_natural_reconnect_has_no_implementation_and_excludes_artificial_routes():
    stage = build_plan("session-reconnect").stages[0]
    assert stage.readiness == "not_implemented" and stage.references == ()
    assert stage.possible_outcomes == ("NOT RUN",) and stage.completion_outcomes == ()
    assert "custom_components/hoben/v4_no_pong.py" in stage.excluded_references
    assert "scripts/session_suite.py" in stage.excluded_references
    assert "scripts/session_natural_900.py" in stage.excluded_references
    for selection, count in (
        ("session-reconnect", 0),
        ("session-reconnect", 1),
        ("all", 2),
        ("all", 3),
    ):
        result = assess_transition(selection, evidence(selection, count))
        assert (
            result.reason == "not_implemented" and not result.prerequisites_consistent
        )
        never_starts(result)


def test_historical_ceilings_and_scientific_outcomes_are_not_expanded():
    caps = {name: dict(build_plan(name).historical_limits) for name in ALL}
    assert caps["h1h2"] == {
        "process_seconds": 1800,
        "per_session_seconds": 90,
        "h1_sessions": 6,
        "h2_sessions": 6,
        "rx_bytes_per_session": 1048576,
    }
    assert caps["session-300"] == {
        "process_seconds": 360,
        "useful_seconds": 300,
        "max_opens": 3,
        "max_reads": 6,
        "read_interval_seconds": 60,
        "rx_bytes_total": 1048576,
    }
    assert caps["session-reconnect"] == {
        "process_seconds": 600,
        "functional_seconds": 360,
        "max_opens": 3,
        "max_reads": 10,
        "rx_bytes_total": 1048576,
        "stable_seconds": 120,
    }
    parent = ast.parse((ROOT / "scripts/launch_manual_hoben.py").read_text())
    seconds = next(
        ast.literal_eval(n.value)
        for n in parent.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SECONDS" for t in n.targets)
    )
    assert seconds == {name: caps[name]["process_seconds"] for name in ALL}
    budget = ast.parse((ROOT / "custom_components/hoben/v4_experiment.py").read_text())
    for cls, name in (
        ("Session300", "session-300"),
        ("SessionReconnect", "session-reconnect"),
    ):
        node = next(
            n for n in budget.body if isinstance(n, ast.ClassDef) and n.name == cls
        )
        reads = next(
            ast.literal_eval(n.value)
            for n in node.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "MAX_READS" for t in n.targets)
        )
        assert reads == caps[name]["max_reads"]
    assert "SUCCESS" not in build_plan("h1h2").stages[0].possible_outcomes
    assert set(build_plan("session-300").stages[0].possible_outcomes) == {
        "SUCCESS",
        "FAILURE",
        "INCONCLUSIVE",
        "NOT RUN",
    }


@pytest.mark.parametrize("count,pending", [(0, "h1h2"), (1, "session-300")])
def test_all_prefix_consistency_does_not_allow_start(count, pending):
    result = assess_transition("all", evidence(count=count))
    assert result.pending_step == pending and result.prerequisites_consistent
    assert result.reason == "offline_only"
    never_starts(result)


@pytest.mark.parametrize("selection", ["h1h2", "session-300"])
def test_completed_fixture_prefix_is_not_a_successful_live_report(selection):
    result = assess_transition(selection, evidence(selection, 1))
    assert result.pending_step is None and result.reason == "prefix_complete"
    assert result.prerequisites_consistent and result.actions_result == "FAILURE"
    never_starts(result)


@pytest.mark.parametrize(
    "flag", ["admission_attested", "next_deadline_armed", "next_ack"]
)
@pytest.mark.parametrize("unknown", [False, None, 1, "true"])
def test_missing_next_phase_proof_never_advances(flag, unknown):
    e = evidence(count=1)
    e[flag] = unknown
    result = assess_transition("all", e)
    assert not result.prerequisites_consistent
    never_starts(result)


@pytest.mark.parametrize(
    "flag",
    [
        "attested",
        "deadline_armed",
        "ack",
        "process_ok",
        "cleanup_ok",
        "report_valid",
        "collection_complete",
        "limits_respected",
    ],
)
@pytest.mark.parametrize("unknown", [False, None, 1, "true"])
def test_incomplete_h1_inconclusive_cannot_unlock_session(flag, unknown):
    e = evidence(count=1)
    e["completed"][0][flag] = unknown
    result = assess_transition("all", e)
    assert not result.prerequisites_consistent and result.reason == "prefix_unattested"
    never_starts(result)


@pytest.mark.parametrize(
    "index,outcome",
    [
        (0, "SUCCESS"),
        (0, "FAILURE"),
        (0, "NOT RUN"),
        (0, "PRIVATE_INPUT"),
        (1, "FAILURE"),
        (1, "INCONCLUSIVE"),
        (1, "NOT RUN"),
    ],
)
def test_bad_or_insufficient_science_blocks_following_stage(index, outcome):
    e = evidence(count=index + 1)
    e["completed"][index]["outcome"] = outcome
    result = assess_transition("all", e)
    assert (
        not result.prerequisites_consistent and result.reason == "prefix_not_admissible"
    )
    never_starts(result)


def test_every_evidence_field_is_closed_required_and_unknown_is_refused():
    source = evidence(count=1)
    for path in ((), ("completed", 0)):
        original = source if not path else source["completed"][0]
        for key in (*original, "PRIVATE_INPUT"):
            e = copy.deepcopy(source)
            record = e if not path else e["completed"][0]
            if key in record:
                del record[key]
            else:
                record[key] = 99999  # no budget or result override can be injected
            result = assess_transition("all", e)
            assert not result.prerequisites_consistent
            never_starts(result)
    for bad in (None, [], {}, {"selection": "all"}):
        assert not assess_transition("all", bad).prerequisites_consistent


@pytest.mark.parametrize(
    "mutation",
    ["gap", "duplicate", "too_many", "wrong_next", "wrong_plan", "phantom_ack"],
)
def test_prefix_order_selection_and_acks_are_not_approximated(mutation):
    e = evidence(count=1)
    if mutation == "gap":
        e["completed"][0] = proof("session-300")
    elif mutation == "duplicate":
        e["completed"].append(proof("h1h2"))
    elif mutation == "too_many":
        e["completed"] *= 4
    elif mutation == "wrong_next":
        e["next_step"] = "session-reconnect"
    elif mutation == "wrong_plan":
        e["selection"] = "h1h2"
    else:
        e = evidence("session-300", 1)
        e["next_ack"] = True
        assert not assess_transition("session-300", e).prerequisites_consistent
        return
    result = assess_transition("all", e)
    assert not result.prerequisites_consistent
    never_starts(result)


def test_no_io_imports_live_callers_or_runnable_cli():
    path = ROOT / "scripts/protocol_campaign_plan.py"
    for node in ast.walk(ast.parse(path.read_text())):
        assert not isinstance(node, ast.Import)
        if isinstance(node, ast.ImportFrom):
            assert node.module in {"dataclasses", "types"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {
                "open",
                "eval",
                "exec",
                "__import__",
                "print",
                "input",
            }
    for folder in (".github", "scripts", "custom_components"):
        for source in (ROOT / folder).rglob("*"):
            if (
                source.is_file()
                and source.suffix in {".py", ".cjs", ".yml"}
                and source != path
            ):
                assert "protocol_campaign_plan" not in source.read_text()
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
