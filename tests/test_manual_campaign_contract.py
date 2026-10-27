"""Synthetic normalized attestations only; no GitHub reader or claim creation."""

import ast
import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from scripts.manual_campaign_contract import assess_admission, assess_recheck

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "protocol": "hoben-protocol-manual.yml",
    "ha": "hoben-ha-manual.yml",
}


def bind(s):
    """Canonical contract fixture, independent of the validator's helpers."""
    payload = {k: v for k, v in s.items() if k not in {"claim", "observed_ms"}}
    payload["ci"] = {
        **s["ci"],
        "jobs": sorted(s["ci"]["jobs"], key=lambda j: j["name"]),
    }
    s["claim"]["binding"] = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return s


def snapshot(campaign="protocol", required=True):
    workflow = ".github/workflows/" + FILES[campaign]
    s = {
        "schema": 1,
        "campaign": campaign,
        "observed_ms": 2000,
        "dispatch": {
            "repository": "Guillaume0385/ha-hoben-community",
            "repository_id": 1401398724,
            "actor": "Guillaume0385",
            "actor_id": 18246624,
            "triggering_actor": "Guillaume0385",
            "triggering_actor_id": 18246624,
            "event": "workflow_dispatch",
            "ref": "refs/heads/experimental",
            "sha": "a" * 40,
            "workflow": workflow,
            "workflow_sha": "a" * 40,
            "workflow_ref": "Guillaume0385/ha-hoben-community/"
            + workflow
            + "@refs/heads/experimental",
            "run_id": 10,
            "attempt": 1,
            "scenario": "all",
            "started_ms": 1000,
            "attested": True,
        },
        "branch": {"head_sha": "a" * 40, "protected": True, "attested": True},
        "pr": {
            "number": 20,
            "matches": 1,
            "base_ref": "experimental",
            "base_repo_id": 1401398724,
            "head_repo_id": 1401398724,
            "head_ref": "work",
            "merge_sha": "a" * 40,
            "candidate_sha": "b" * 40,
            "merge_tree": "c" * 40,
            "candidate_tree": "c" * 40,
            "merged": True,
            "draft": False,
            "merged_by": "Guillaume0385",
            "merged_by_id": 18246624,
            "merged_ms": 500,
            "attested": True,
        },
        "review": {
            "candidate_sha": "b" * 40,
            "manager_reviewed": True,
            "changes_requested": False,
            "unresolved_threads": 0,
            "attested": True,
        },
        "ci": {
            "id": 30,
            "repository_id": 1401398724,
            "head_repository_id": 1401398724,
            "pr_number": 20,
            "candidate_sha": "b" * 40,
            "head_ref": "work",
            "event": "pull_request",
            "attempt": 1,
            "workflow": ".github/workflows/validate.yml",
            "status": "completed",
            "completed_ms": 400,
            "attested": True,
            "jobs": [
                {
                    "name": name,
                    "candidate_sha": "b" * 40,
                    "status": "completed",
                    "conclusion": "success",
                }
                for name in ("tests", "ha-tests", "hacs", "hassfest")
            ],
        },
        "environment": {
            "id": 40,
            "name": "hoben-live" if campaign == "ha" else "hoben-experimental",
            "policy_digest": "d" * 64,
            "policy_kind": "experimental_only",
            "rules_known": True,
            "branch_allowed": True,
            "approval_required": required,
            "approval": {
                "run_id": 10,
                "environment_id": 40,
                "state": "approved",
                "independent": True,
                "approved_ms": 1500,
                "attested": True,
            }
            if required
            else None,
            "attested": True,
        },
        "claim": {
            "binding": "",
            "object_sha": "e" * 40,
            "created_for_run": 10,
            "exclusive": True,
            "replayed": False,
            "attested": True,
        },
        "concurrency": {
            "group": "hoben-read-only-observation",
            "run_id": 10,
            "exclusive": True,
            "scan_complete": True,
            "other_active_runs": [],
            "attested": True,
        },
    }
    return bind(s)


def no_permit(result):
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert not bool(result)
    assert "PRIVATE_INPUT" not in repr(result)


@pytest.mark.parametrize("campaign", FILES)
@pytest.mark.parametrize("required", [True, False])
def test_coherent_synthetic_snapshots_never_authorize_execution(campaign, required):
    w = yaml.load(
        (ROOT / ".github/workflows" / FILES[campaign]).read_text(),
        Loader=yaml.BaseLoader,
    )
    options = w["on"]["workflow_dispatch"]["inputs"]["scenario"]["options"]
    for scenario in options:
        before = snapshot(campaign, required)
        before["dispatch"]["scenario"] = scenario
        model = assess_admission(bind(before))
        assert model.consistent and model.category == "coherent_offline"
        after = copy.deepcopy(before)
        after["observed_ms"] += 1
        after["ci"]["jobs"].reverse()  # API order is not a policy change
        checked = assess_recheck(model, after)
        assert checked.consistent
        for result in (model, checked):
            no_permit(result)


MUTATIONS = [
    ("dispatch", "workflow", ".github/workflows/hoben-manual.yml"),
    ("dispatch", "workflow_ref", "PRIVATE_INPUT"),
    ("dispatch", "workflow_sha", "f" * 40),
    ("dispatch", "sha", "0" * 40),
    ("dispatch", "ref", "refs/heads/main"),
    ("dispatch", "ref", "refs/heads/unreviewed"),
    ("dispatch", "event", "push"),
    ("dispatch", "repository", "other/repository"),
    ("dispatch", "repository_id", 2),
    ("dispatch", "actor", "other"),
    ("dispatch", "actor_id", True),
    ("dispatch", "triggering_actor", "other"),
    ("dispatch", "triggering_actor_id", 2),
    ("dispatch", "scenario", "PRIVATE_INPUT"),
    ("dispatch", "attempt", 2),
    ("dispatch", "attempt", True),
    ("dispatch", "run_id", 0),
    ("dispatch", "started_ms", 2500),
    ("branch", "protected", False),
    ("branch", "head_sha", "f" * 40),
    ("pr", "number", True),
    ("pr", "matches", 2),
    ("pr", "base_ref", "main"),
    ("pr", "base_repo_id", 2),
    ("pr", "head_repo_id", 2),
    ("pr", "merge_sha", "f" * 40),
    ("pr", "candidate_tree", "f" * 40),
    ("pr", "merged", False),
    ("pr", "draft", True),
    ("pr", "merged_by", "other"),
    ("pr", "merged_by_id", 2),
    ("pr", "merged_ms", 1500),
    ("review", "candidate_sha", "f" * 40),
    ("review", "manager_reviewed", False),
    ("review", "changes_requested", True),
    ("review", "unresolved_threads", 1),
    ("review", "unresolved_threads", False),
    ("ci", "id", 0),
    ("ci", "repository_id", 2),
    ("ci", "head_repository_id", 2),
    ("ci", "pr_number", 99),
    ("ci", "candidate_sha", "f" * 40),
    ("ci", "head_ref", "other"),
    ("ci", "event", "workflow_dispatch"),
    ("ci", "attempt", 2),
    ("ci", "workflow", "other.yml"),
    ("ci", "status", "in_progress"),
    ("ci", "completed_ms", 501),
    ("environment", "name", "other"),
    ("environment", "id", True),
    ("environment", "policy_digest", "PRIVATE_INPUT"),
    ("environment", "policy_kind", "unknown"),
    ("environment", "rules_known", False),
    ("environment", "branch_allowed", None),
    ("environment", "approval_required", "false"),
    ("environment", "approval", None),
    ("concurrency", "group", "other"),
    ("concurrency", "run_id", 99),
    ("concurrency", "exclusive", False),
    ("concurrency", "scan_complete", None),
    ("concurrency", "other_active_runs", [99]),
    ("claim", "created_for_run", 99),
    ("claim", "exclusive", False),
    ("claim", "replayed", True),
    ("claim", "object_sha", "0" * 40),
]


@pytest.mark.parametrize("campaign", FILES)
@pytest.mark.parametrize("section,key,value", MUTATIONS)
def test_bound_proof_refusals_even_when_attacker_rebinds_fixture(
    campaign, section, key, value
):
    bad = snapshot(campaign)
    initial = assess_admission(bad)
    bad[section][key] = value
    # Recomputing a digest cannot turn invalid facts into a valid model.
    bind(bad)
    result = assess_admission(bad)
    assert not result.consistent
    no_permit(result)
    bad["observed_ms"] = 3000
    reread = assess_recheck(initial, bind(bad))
    assert not reread.consistent
    no_permit(reread)


def records(s):
    return [
        (),
        *(
            (name,)
            for name in (
                "dispatch",
                "branch",
                "pr",
                "review",
                "ci",
                "environment",
                "claim",
                "concurrency",
            )
        ),
        ("environment", "approval"),
        *(("ci", "jobs", i) for i in range(4)),
    ]


def at(s, path):
    for key in path:
        s = s[key]
    return s


@pytest.mark.parametrize("campaign", FILES)
def test_every_record_is_closed_every_required_field_and_attestation_is_mandatory(
    campaign,
):
    original = snapshot(campaign)
    initial = assess_admission(original)
    for path in records(original):
        for operation, key in [
            (operation, k)
            for k in at(original, path)
            for operation in ("missing", "null")
        ] + [("extra", "PRIVATE_INPUT")]:
            bad = copy.deepcopy(original)
            bad["observed_ms"] = 3000
            record = at(bad, path)
            if operation == "missing":
                del record[key]
            elif operation == "null":
                record[key] = None
            else:
                record[key] = "PRIVATE_INPUT"
            result = assess_admission(bad)
            assert not result.consistent, (path, operation, key)
            no_permit(result)
            reread = assess_recheck(initial, bad)
            assert not reread.consistent, (path, operation, key)
            no_permit(reread)
        if "attested" in at(original, path):
            for unknown in (False, None, 1, "true"):
                bad = copy.deepcopy(original)
                bad["observed_ms"] = 3000
                at(bad, path)["attested"] = unknown
                assert not assess_admission(bad).consistent
                assert not assess_recheck(initial, bad).consistent


@pytest.mark.parametrize(
    "key,value",
    [
        ("run_id", 99),
        ("environment_id", 99),
        ("state", "pending"),
        ("independent", False),
        ("approved_ms", 999),
        ("approved_ms", 2001),
    ],
)
def test_approval_must_be_fresh_independent_and_bound(key, value):
    s = snapshot("ha")
    s["environment"]["approval"][key] = value
    assert not assess_admission(bind(s)).consistent


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "extra", "failure", "skipped", "wrong_sha"]
)
def test_ci_job_set_cannot_be_approximated(mutation):
    s = snapshot()
    jobs = s["ci"]["jobs"]
    if mutation == "duplicate":
        jobs[0]["name"] = jobs[1]["name"]
    elif mutation == "missing":
        jobs.pop()
    elif mutation == "extra":
        jobs.append(copy.deepcopy(jobs[0]))
    elif mutation == "wrong_sha":
        jobs[0]["candidate_sha"] = "f" * 40
    else:
        jobs[0]["conclusion"] = mutation
    assert not assess_admission(bind(s)).consistent


@pytest.mark.parametrize("campaign", FILES)
@pytest.mark.parametrize(
    "change",
    [
        "scenario",
        "campaign",
        "sha",
        "policy",
        "approval",
        "environment",
        "ci",
        "tree",
        "claim",
        "stale",
    ],
)
def test_recheck_rejects_coherent_changed_state_against_immutable_model(
    campaign, change
):
    before = snapshot(campaign)
    initial = assess_admission(before)
    after = copy.deepcopy(before)
    after["observed_ms"] = 3000
    if change == "scenario":
        after["dispatch"]["scenario"] = "hoben-live" if campaign == "ha" else "tls-only"
    elif change == "campaign":
        after = snapshot("protocol" if campaign == "ha" else "ha")
        after["observed_ms"] = 3000
    elif change == "sha":
        after["dispatch"]["sha"] = after["dispatch"]["workflow_sha"] = "f" * 40
        after["branch"]["head_sha"] = after["pr"]["merge_sha"] = "f" * 40
    elif change == "policy":
        after["environment"]["policy_digest"] = "f" * 64
    elif change == "approval":
        after["environment"]["approval"]["approved_ms"] = 1501
    elif change == "environment":
        after["environment"]["id"] = after["environment"]["approval"][
            "environment_id"
        ] = 41
    elif change == "ci":
        after["ci"]["id"] = 31
    elif change == "tree":
        after["pr"]["candidate_tree"] = after["pr"]["merge_tree"] = "f" * 40
    elif change == "claim":
        after["claim"]["object_sha"] = "f" * 40
    else:
        after["observed_ms"] = before["observed_ms"]
    bind(after)
    assert assess_admission(after).consistent  # individually coherent is insufficient
    result = assess_recheck(initial, after)
    assert not result.consistent and result.category == "state_changed"
    no_permit(result)


def test_input_mutation_cannot_rewrite_the_model_and_no_result_is_a_permit():
    before = snapshot()
    after = copy.deepcopy(before)
    initial = assess_admission(before)
    before["dispatch"]["scenario"] = "tls-only"
    after["observed_ms"] += 1
    assert assess_recheck(initial, after).consistent
    with pytest.raises(FrozenInstanceError):
        initial.execution = "live"
    no_permit(initial)
    for previous in (None, {}, assess_admission(None), assess_recheck(initial, after)):
        result = assess_recheck(previous, after)
        assert not result.consistent and result.category == "previous"


def test_environment_modes_do_not_enable_main_and_claim_binding_is_not_optional():
    for campaign in FILES:
        s = snapshot(campaign)
        s["environment"]["policy_kind"] = "protected_branches"
        assert assess_admission(bind(s)).consistent == (campaign == "ha")
        s["dispatch"]["ref"] = "refs/heads/main"
        s["dispatch"]["workflow_ref"] = s["dispatch"]["workflow_ref"].replace(
            "experimental", "main"
        )
        s["pr"]["base_ref"] = "main"
        assert not assess_admission(bind(s)).consistent
    s = snapshot()
    s["claim"]["binding"] = "f" * 64
    assert assess_admission(s).category == "claim"


@pytest.mark.parametrize("bad", [None, [], True, 1, "PRIVATE_INPUT", {"schema": True}])
def test_malformed_inputs_never_escape_or_echo(bad):
    result = assess_admission(bad)
    assert not result.consistent
    no_permit(result)


def test_module_has_no_io_imports_live_callers_or_successful_cli():
    path = ROOT / "scripts/manual_campaign_contract.py"
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert {n.name for n in node.names} <= {"hashlib", "json", "re"}
        if isinstance(node, ast.ImportFrom):
            assert node.module == "dataclasses"
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
                assert "manual_campaign_contract" not in source.read_text()
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
