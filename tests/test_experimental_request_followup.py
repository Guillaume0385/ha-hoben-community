"""Exercise PR provenance, REST paths, queued contenders and result discovery."""

import copy
import json

import pytest
import yaml
from test_experimental_request_gate import (
    HEAD,
    MAIN,
    REPO,
    ROOT,
    SHA,
    WORKFLOW,
    associated_pr,
    claim_tag,
    execute,
    live,
    public_report,
    publish_env,
    refused,
    run_record,
)
from test_experimental_request_gate import api as api
from test_experimental_request_review import group


@pytest.mark.parametrize("location", ["check", "run"])
@pytest.mark.parametrize(
    "change",
    [
        "other-pr",
        "main-base",
        "other-head",
        "other-branch",
        "fork",
        "wrong-url",
        "absent",
        "empty",
    ],
)
def test_successful_ci_on_the_same_sha_must_belong_to_reviewed_pr(
    api, tmp_path, location, change
):
    target = api["checks"][0] if location == "check" else api["runs"]["98"]
    record = target["pull_requests"][0]
    if change == "other-pr":
        # Another PR can have exactly the same HEAD but a different target.
        record["number"] = 57
        record["url"] = f"https://api.github.com/repos/{REPO}/pulls/57"
    elif change == "main-base":
        record["base"]["ref"] = "main"
    elif change == "other-head":
        record["head"]["sha"] = MAIN
    elif change == "other-branch":
        record["head"]["ref"] = "other-same-sha"
    elif change == "fork":
        record["head"]["repo"]["id"] = 999
    elif change == "wrong-url":
        record["head"]["repo"]["url"] += "-other"
    elif change == "absent":
        del target["pull_requests"]
    else:
        target["pull_requests"] = []
    assert target["head_sha"] == HEAD and target["conclusion"] == "success"
    result = execute(api, tmp_path)
    refused(result, "offline_ci_unverified")
    assert not result["writes"]


def test_a_shared_run_cannot_choose_the_reviewed_pr_from_two_associations(
    api, tmp_path
):
    other = associated_pr()
    other.update(number=57, url=f"https://api.github.com/repos/{REPO}/pulls/57")
    other["base"]["ref"] = "main"
    api["checks"][0]["pull_requests"].append(copy.deepcopy(other))
    api["runs"]["98"]["pull_requests"].append(other)
    result = execute(api, tmp_path)
    refused(result, "offline_ci_unverified")
    assert not result["writes"]


@pytest.mark.parametrize("field", ["repository", "head_repository"])
def test_ci_run_repository_is_verified_independently_of_the_pr(api, tmp_path, field):
    api["runs"]["98"][field]["id"] = 999
    result = execute(api, tmp_path)
    refused(result, "offline_ci_unverified")
    assert not result["writes"]


@pytest.mark.parametrize("suffix", ["", "@main", "@refs/heads/main"])
def test_main_run_and_completed_dry_accept_documented_rest_path_forms(
    api, tmp_path, suffix
):
    live(api)
    api["runs"]["123"]["path"] = WORKFLOW + suffix
    api["runs"]["120"]["path"] = WORKFLOW + suffix
    result = execute(api, tmp_path)
    assert not result["results"][0]["failed"]
    assert result["results"][0]["outputs"]["approved"] == "true"


@pytest.mark.parametrize(
    "suffix",
    ["", "@refs/pull/55/merge", "@codex/issue-54", "@refs/heads/codex/issue-54"],
)
def test_reviewed_pr_ci_accepts_bare_or_expected_ref_paths(api, tmp_path, suffix):
    api["runs"]["98"]["path"] = ".github/workflows/validate.yml" + suffix
    result = execute(api, tmp_path)
    assert not result["results"][0]["failed"]
    assert result["results"][0]["outputs"]["approved"] == "true"


@pytest.mark.parametrize(
    "run,reason",
    [
        ("123", "unauthenticated_request"),
        ("120", "dry_run_required"),
        ("98", "offline_ci_unverified"),
    ],
)
@pytest.mark.parametrize(
    "suffix",
    ["@", "@refs/heads/other", "@refs/pull/57/merge", "@refs/heads/main@other"],
)
def test_wrong_ref_suffix_is_not_silently_removed(api, tmp_path, run, reason, suffix):
    live(api)
    api["runs"][run]["path"] += suffix
    result = execute(api, tmp_path)
    refused(result, reason)
    assert not result["writes"]


@pytest.mark.parametrize(
    "suffix", ["", "@main", "@refs/heads/main", "@experimental", "@"]
)
def test_discovery_normalizes_expected_main_refs_and_refuses_other_refs(
    api, tmp_path, suffix
):
    api["claims"][f"hoben-experimental-dry-run-h1h2-{SHA}"] = claim_tag(id=123)
    api["runs"]["123"].update(
        status="completed", conclusion="success", path=WORKFLOW + suffix
    )
    api["combined"]["statuses"][0]["target_url"] = (
        f"https://github.com/{REPO}/actions/runs/123"
    )
    result = execute(api, tmp_path, operations=[{"name": "discover"}])
    observed = result["results"][0]
    assert not result["writes"]
    if suffix in {"", "@main", "@refs/heads/main"}:
        assert not observed["failed"] and observed["result"]["state"] == "success"
    else:
        assert observed["failed"]


@pytest.mark.parametrize("suffix", ["@refs/heads/main", "@refs/heads/other", "@"])
def test_active_hoben_run_suffix_cannot_hide_concurrent_network_work(
    api, tmp_path, suffix
):
    api["active"] = [{"id": 124, "status": "in_progress", "path": WORKFLOW + suffix}]
    result = execute(api, tmp_path)
    refused(result, "concurrent_hoben_run")
    assert not result["writes"]


@pytest.mark.parametrize("state", ["queued", "pending", "requested"])
def test_three_pending_recognized_requests_do_not_refuse_the_lock_holder(
    api, tmp_path, state
):
    contenders = [
        {"id": n, "status": state, "path": f".github/workflows/{name}@refs/heads/main"}
        for n, name in enumerate(
            (
                "hoben-experimental-request.yml",
                "opened-client-boundary.yml",
                "manager-live-hoben.yml",
            ),
            start=124,
        )
    ]
    live(api)
    result = execute(
        api,
        tmp_path,
        operations=[
            {"name": "verify"},
            {"name": "verify", "recheck": True, "patch": {"active": contenders}},
        ],
    )
    assert all(
        not r["failed"] and r["outputs"]["approved"] == "true"
        for r in result["results"]
    )
    assert len([w for w in result["writes"] if w["name"] == "ref"]) == 1
    stamp = json.loads(
        result["claims"][f"hoben-experimental-live-h1h2-{SHA}"]["message"]
    )
    assert stamp["run_id"] == 123  # Immutable admission survives later waiters.


def test_all_network_workflows_keep_multiple_waiters_in_the_global_queue():
    cases = [
        (
            "hoben-experimental-request.yml",
            {
                "event_name": "issues",
                "run_id": 123,
                "event": {
                    "action": "labeled",
                    "issue": {"number": 54},
                    "label": {"name": "manager-hoben-experimental-live"},
                },
            },
            None,
        ),
        (
            "opened-client-boundary.yml",
            {"event_name": "workflow_dispatch", "run_id": 124},
            None,
        ),
        (
            "manager-live-hoben.yml",
            {
                "event_name": "pull_request_target",
                "actor": "Guillaume0385",
                "run_id": 125,
                "event": {
                    "action": "labeled",
                    "label": {"name": "manager-live-hoben"},
                    "pull_request": {
                        "base": {"ref": "main"},
                        "draft": False,
                        "head": {"repo": {"full_name": REPO}},
                    },
                },
            },
            None,
        ),
        (
            "live-validation.yml",
            {
                "event_name": "workflow_dispatch",
                "ref": "refs/heads/main",
                "run_id": 126,
            },
            {"mode": "read-v4-state"},
        ),
    ]
    for name, github, inputs in cases:
        definition = yaml.load(
            (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
        )
        assert definition["concurrency"]["queue"] == "max"
        assert definition["concurrency"]["cancel-in-progress"] == "false"
        assert group(name, github, inputs) == "hoben-boundary-campaign"
    # The platform queue capacity/order is a GitHub guarantee, not exercised by
    # a local scheduler imitation. No real dry/live workflow is triggered here.


def test_discovery_uses_failed_report_status_even_when_publication_and_run_succeed(
    api, tmp_path
):
    live(api)
    report = public_report()
    report.update(result="failure", reason="collection_interrupted")
    completed = run_record(completed=True)
    result = execute(
        api,
        tmp_path,
        report=report,
        operations=[
            {"name": "verify"},
            {"name": "publish", "env": publish_env()},
            {
                "name": "discover",
                "patch": {
                    "runs": {**api["runs"], "123": completed},
                    "jobs": {
                        **api["jobs"],
                        "123": [
                            {"name": name, "conclusion": "success"}
                            for name in ("request", "observations", "publish")
                        ],
                    },
                },
            },
        ],
    )
    assert not result["results"][0]["failed"] and not result["results"][1]["failed"]
    assert [w for w in result["writes"] if w["name"] == "status"][-1]["args"][
        "state"
    ] == "failure"
    assert result["results"][2]["result"]["state"] == "failure"


@pytest.mark.parametrize(
    "status,expected",
    [
        (None, "failure"),
        ("pending", "failure"),
        ("failure", "failure"),
        ("error", "failure"),
        ("success", "success"),
    ],
)
def test_workflow_success_needs_matching_final_success_status(
    api, tmp_path, status, expected
):
    api["claims"][f"hoben-experimental-dry-run-h1h2-{SHA}"] = claim_tag(id=123)
    api["runs"]["123"] = run_record(completed=True)
    api["combined"]["statuses"] = (
        []
        if status is None
        else [
            {
                "context": "hoben-experimental/h1h2/dry-run",
                "state": status,
                "target_url": f"https://github.com/{REPO}/actions/runs/123",
            }
        ]
    )
    result = execute(api, tmp_path, operations=[{"name": "discover"}])
    assert result["results"][0]["result"]["state"] == expected
    assert not result["writes"]


def test_discovery_never_substitutes_a_success_status_for_another_run(api, tmp_path):
    api["claims"][f"hoben-experimental-dry-run-h1h2-{SHA}"] = claim_tag(id=123)
    api["runs"]["123"] = run_record(completed=True)
    assert api["combined"]["statuses"][0]["target_url"].endswith("/120")
    result = execute(api, tmp_path, operations=[{"name": "discover"}])
    assert result["results"][0]["failed"] and not result["writes"]
