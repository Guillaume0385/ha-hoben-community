"""HA plan metadata only; never import or instantiate the live client/collector."""

import ast
import copy
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from scripts.ha_campaign_plan import CHOICES, LOSS_KINDS, assess_transition, build_plan

ROOT = Path(__file__).resolve().parents[1]
ORDER = (
    "hoben-live",
    "open-errors",
    "refresh-v4",
    "session-reuse",
    "session-reconnect",
    "cleanup",
    "availability",
)
NEXT_FLAGS = (
    "next_deadline_armed",
    "next_ack",
    "next_limits_attested",
    "next_cleanup_attested",
)
PAST_FLAGS = (
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


def proof(step):
    return {
        "step": step,
        "outcome": "SUCCESS",
        "loss_kind": "none",
        "reconnection_status": "INCONCLUSIVE",
        **{key: True for key in PAST_FLAGS},
    }


def evidence(selection="all", count=0):
    names = ORDER if selection == "all" else (selection,)
    pending = names[count] if count < len(names) else None
    return {
        "selection": selection,
        "admission_attested": True,
        "next_step": pending,
        "completed": [proof(name) for name in names[:count]],
        **{key: pending is not None for key in NEXT_FLAGS},
    }


def never_starts(result):
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert result.can_start is False and not bool(result)
    assert "PRIVATE_INPUT" not in repr(result)


def test_exact_shell_choices_seven_stage_order_and_dependencies():
    shell = yaml.load(
        (ROOT / ".github/workflows/hoben-ha-manual.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert CHOICES == (*ORDER, "all")
    assert shell["on"]["workflow_dispatch"]["inputs"]["scenario"]["options"] == list(
        CHOICES
    )
    plan = build_plan("all")
    assert tuple(s.name for s in plan.stages) == ORDER
    assert tuple(s.depends_on for s in plan.stages) == (
        (),
        *((ORDER[i - 1],) for i in range(1, 7)),
    )
    assert plan.known_limits is None  # no invented aggregate or seven-times budget
    never_starts(plan)


@pytest.mark.parametrize("selection", CHOICES)
def test_all_plans_and_reuse_references_are_immutable_and_not_capabilities(selection):
    plan = build_plan(selection)
    assert type(plan.stages) is tuple
    with pytest.raises(FrozenInstanceError):
        plan.can_start = True
    with pytest.raises(FrozenInstanceError):
        plan.actions_result = "SUCCESS"
    for stage in plan.stages:
        never_starts(stage)
        assert type(stage.reuse_references) is tuple
        assert all(
            (ROOT / p).is_file()
            for p in (*stage.reuse_references, *stage.excluded_references)
        )
        with pytest.raises(FrozenInstanceError):
            stage.readiness = "ready"
        if stage.known_limits is not None:
            assert type(stage.known_limits) is tuple
            assert all(type(pair) is tuple for pair in stage.known_limits)
            assert not any("rx" in key for key, _ in stage.known_limits)
            with pytest.raises(TypeError):
                stage.known_limits[0] = ("process_seconds", 99999)
    never_starts(plan)


@pytest.mark.parametrize("selection", ORDER[1:])
def test_six_complements_remain_unimplemented_unknown_and_never_unlock(selection):
    plan = build_plan(selection)
    stage = plan.stages[0]
    assert stage.readiness == "not_implemented" and stage.known_limits is None
    assert plan.known_limits is None and stage.possible_outcomes == ("NOT RUN",)
    for count in (0, 1):
        result = assess_transition(selection, evidence(selection, count))
        assert (
            result.reason == "not_implemented" and not result.prerequisites_consistent
        )
        never_starts(result)


@pytest.mark.parametrize("count", range(1, 8))
def test_all_stops_after_the_historical_reference_even_with_fabricated_success(count):
    result = assess_transition("all", evidence(count=count))
    assert result.pending_step == "open-errors" and result.reason == "not_implemented"
    assert not result.prerequisites_consistent
    never_starts(result)


def test_historical_success_is_not_a_new_shell_connection_or_a_reconnection_proof():
    stage = build_plan("hoben-live").stages[0]
    assert stage.readiness == "historical_reference"
    assert stage.possible_outcomes == ("SUCCESS", "FAILURE", "NOT RUN")
    assert "scripts/ha_session_live_worker.py" in stage.reuse_references
    assert "custom_components/hoben/client.py" in stage.reuse_references
    assert "custom_components/hoben/coordinator.py" in stage.reuse_references
    for count, reason in ((0, "offline_only"), (1, "prefix_complete")):
        result = assess_transition("hoben-live", evidence("hoben-live", count))
        assert result.prerequisites_consistent and result.reason == reason
        never_starts(result)
    excluded = build_plan("session-reconnect").stages[0].excluded_references
    assert "custom_components/hoben/v4_no_pong.py" in excluded
    assert "scripts/session_suite.py" in excluded


def test_known_first_scenario_budgets_match_source_without_importing_ha():
    def integer_expression(n, known):
        if isinstance(n, ast.Constant) and type(n.value) is int:
            return n.value
        if isinstance(n, ast.Name):
            return known[n.id]
        if isinstance(n, ast.Tuple):
            return tuple(integer_expression(x, known) for x in n.elts)
        if isinstance(n, ast.BinOp):
            left, right = (
                integer_expression(n.left, known),
                integer_expression(n.right, known),
            )
            if isinstance(n.op, ast.Add):
                return left + right
            if isinstance(n.op, ast.Pow):
                return left**right
        raise AssertionError("Unexpected static budget expression")

    wanted = {
        "MEMORY_BYTES",
        "PIDS",
        "USEFUL_MS",
        "COLLECTION_MS",
        "PROCESS_MS",
        "REPORT_BYTES",
        "REFRESH_AT_MS",
    }
    known = {}
    for n in ast.parse((ROOT / "scripts/ha_live_proof.py").read_text()).body:
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id in wanted
        ):
            known[n.targets[0].id] = integer_expression(n.value, known)
    client = ast.parse((ROOT / "custom_components/hoben/client.py").read_text())
    cls = next(
        n
        for n in client.body
        if isinstance(n, ast.ClassDef) and n.name == "HobenClient"
    )
    ctor = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    attempts = next(
        ast.literal_eval(value)
        for arg, value in zip(ctor.args.kwonlyargs, ctor.args.kw_defaults)
        if arg.arg == "max_attempts"
    )
    caps = dict(build_plan("hoben-live").known_limits)
    assert caps == {
        "useful_seconds": 300,
        "process_seconds": 360,
        "collection_seconds": 330,
        "memory_bytes": 1073741824,
        "max_pids": 128,
        "max_refreshes": 6,
        "max_opens": 2,
        "report_bytes": 8192,
    }
    assert caps["useful_seconds"] * 1000 == known["USEFUL_MS"]
    assert caps["process_seconds"] * 1000 == known["PROCESS_MS"]
    assert caps["collection_seconds"] * 1000 == known["COLLECTION_MS"]
    assert caps["memory_bytes"] == known["MEMORY_BYTES"]
    assert caps["max_pids"] == known["PIDS"]
    assert caps["report_bytes"] == known["REPORT_BYTES"]
    assert caps["max_refreshes"] == len(known["REFRESH_AT_MS"])
    assert caps["max_opens"] == attempts


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
        "tls-only",
        "h1h2",
        "session-300",
        "ha-parity",
        "live-hoben-authenticated",
    ],
)
def test_unknown_and_protocol_choices_are_not_defaulted_or_echoed(bad):
    plan = build_plan(bad)
    assert plan.selection is None and plan.stages == () and plan.known_limits is None
    never_starts(plan)
    result = assess_transition(bad, {})
    assert result.reason == "unknown_choice" and not result.prerequisites_consistent
    never_starts(result)


@pytest.mark.parametrize("key", ("admission_attested", *NEXT_FLAGS))
@pytest.mark.parametrize("unknown", [False, None, 1, "true"])
def test_absent_admission_ack_limits_or_cleanup_never_unlocks(key, unknown):
    e = evidence()
    e[key] = unknown
    result = assess_transition("all", e)
    assert not result.prerequisites_consistent
    never_starts(result)


@pytest.mark.parametrize("key", PAST_FLAGS)
@pytest.mark.parametrize("unknown", [False, None, 1, "true"])
def test_historical_receipt_requires_every_attestation(key, unknown):
    e = evidence("hoben-live", 1)
    e["completed"][0][key] = unknown
    result = assess_transition("hoben-live", e)
    assert not result.prerequisites_consistent and result.reason == "prefix_unattested"
    never_starts(result)


@pytest.mark.parametrize(
    "outcome", ["INCONCLUSIVE", "FAILURE", "NOT RUN", "PRIVATE_INPUT", True]
)
def test_insufficient_overall_result_cannot_complete_the_reference(outcome):
    e = evidence("hoben-live", 1)
    e["completed"][0]["outcome"] = outcome
    result = assess_transition("hoben-live", e)
    assert (
        not result.prerequisites_consistent and result.reason == "prefix_not_admissible"
    )
    never_starts(result)


@pytest.mark.parametrize("kind", (*LOSS_KINDS[1:], None, "pong_suppressed"))
def test_error_local_close_and_loss_are_not_a_continuous_success(kind):
    assert len(set(LOSS_KINDS)) == len(LOSS_KINDS)
    e = evidence("hoben-live", 1)
    e["completed"][0]["loss_kind"] = kind
    result = assess_transition("hoben-live", e)
    assert not result.prerequisites_consistent
    never_starts(result)


@pytest.mark.parametrize(
    "status", ["SUCCESS", "FAILURE", "NOT RUN", None, "PRIVATE_INPUT"]
)
def test_silence_cannot_be_promoted_to_reconnection(status):
    e = evidence("hoben-live", 1)
    e["completed"][0]["reconnection_status"] = status
    result = assess_transition("hoben-live", e)
    assert (
        result.reason == "reconnection_unproven" and not result.prerequisites_consistent
    )
    never_starts(result)


def test_closed_records_and_prefixes_refuse_unknown_missing_and_unsafe_defaults():
    original = evidence("hoben-live", 1)
    for nested in (False, True):
        keys = original["completed"][0] if nested else original
        for key in (*keys, "PRIVATE_INPUT"):
            for action in ("missing", "null", "extra"):
                e = copy.deepcopy(original)
                record = e["completed"][0] if nested else e
                if action == "missing":
                    record.pop(key, None)
                elif action == "null":
                    record[key] = None
                else:
                    record["PRIVATE_INPUT"] = 99999
                if record == keys:  # removing an absent extra key changes nothing
                    continue
                result = assess_transition("hoben-live", e)
                assert not result.prerequisites_consistent
                never_starts(result)
    for bad in (None, [], {}):
        assert not assess_transition("all", bad).prerequisites_consistent
    for changed in ("next_step", "selection"):
        e = evidence()
        e[changed] = "cleanup"
        assert not assess_transition("all", e).prerequisites_consistent
    for names in (("cleanup",), ("hoben-live", "hoben-live"), ORDER * 2):
        e = evidence()
        e["completed"] = [proof(n) for n in names]
        assert not assess_transition("all", e).prerequisites_consistent
    e = evidence("hoben-live", 1)
    e["next_ack"] = True
    assert not assess_transition("hoben-live", e).prerequisites_consistent


def test_no_io_imports_live_callers_or_successful_cli():
    path = ROOT / "scripts/ha_campaign_plan.py"
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
                text = source.read_text()
                if "ha_campaign_plan" not in text:
                    continue
                # 016+017 authorizes catalog reuse, never executing this old
                # offline plan/transition as admission or a live collector.
                if source == ROOT / "scripts/campaign_runtime_contract.py":
                    imports = [
                        n
                        for n in ast.walk(ast.parse(text))
                        if isinstance(n, ast.ImportFrom)
                        and n.module == "scripts.ha_campaign_plan"
                    ]
                    assert len(imports) == 1
                    assert [(a.name, a.asname) for a in imports[0].names] == [
                        ("CHOICES", "HA_CHOICES")
                    ]
                    assert text.count("ha_campaign_plan") == 1
                elif source == ROOT / "scripts/ha_session_supervisor.py":
                    # The private source bundle must supply that pure module to
                    # the fixed worker; only its exact filename is referenced.
                    assert text.count("ha_campaign_plan") == 1
                    assert '"ha_campaign_plan.py"' in text
                else:
                    raise AssertionError("Unauthorized planning-model caller")
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
