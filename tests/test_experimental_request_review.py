"""Review regressions using the real trusted report gate and scheduling YAML."""

import copy
import json
import shutil
import stat
import subprocess

import pytest
import yaml
from test_experimental_request_gate import (
    ROOT,
    WORKFLOW,
    execute,
    live,
    public_report,
    publish_env,
)
from test_experimental_request_gate import (
    api as api,  # Explicitly re-export the shared synthetic pytest fixture.
)


@pytest.mark.parametrize("count", [0, 1, 6, 11, 12])
def test_only_complete_campaign_can_publish_inconclusive_success(api, tmp_path, count):
    live(api)
    report = public_report()
    report.update(executed_sessions=count, sessions=report["sessions"][:count])
    result = execute(
        api,
        tmp_path,
        operations=[{"name": "verify"}, {"name": "publish", "env": publish_env()}],
        report=report,
    )
    assert result["writes"][-2]["args"]["state"] == (
        "success" if count == 12 else "failure"
    )
    assert bool(result["results"][-1]["failed"]) is (count != 12)


@pytest.mark.parametrize(
    "change",
    [
        "extra-root",
        "extra-row",
        "private-category",
        "short-success",
        "wrong-run",
        "wrong-sha",
        "oversize",
        "missing",
        "symlink",
    ],
)
def test_unsafe_candidate_report_is_rejected_before_any_plaintext_upload(
    api, tmp_path, change
):
    live(api)
    report = public_report()
    private = "SYNTHETIC_PRIVATE_TOKEN_PACKET"
    if change == "extra-root":
        report["UserGuid"] = private
    elif change == "extra-row":
        report["sessions"][0]["raw_rx"] = private
    elif change == "private-category":
        report["sessions"][0]["stop"] = private
    elif change == "short-success":
        report.update(executed_sessions=1, sessions=report["sessions"][:1])
    elif change == "wrong-run":
        report["run_id"] += 1
    elif change == "wrong-sha":
        report["candidate_sha"] = "c" * 40
    elif change == "oversize":
        report["reason"] = private * 4000
    if change == "symlink":
        source = tmp_path / "work/hoben-experimental-exports"
        source.mkdir(parents=True)
        target = tmp_path / "private.json"
        target.write_text(json.dumps(report))
        (source / "report.json").symlink_to(target)
    result = execute(
        api,
        tmp_path,
        operations=[{"name": "prepare-public"}],
        candidate_report=None if change in {"missing", "symlink"} else report,
    )
    assert result["results"][0]["failed"]
    assert result["results"][0]["outputs"].get("verified") != "true"
    assert not (tmp_path / "work/hoben-experimental-public").exists()
    assert not result["writes"] and not result["calls"]
    assert private not in json.dumps(result)


@pytest.mark.parametrize("kind", ["dry", "complete", "partial-failure"])
def test_preupload_validates_then_writes_separate_private_projection(
    api, tmp_path, kind
):
    phase = "dry-run" if kind == "dry" else "live"
    if phase == "live":
        live(api)
    report = public_report(
        phase=phase, result="failure" if kind == "partial-failure" else "inconclusive"
    )
    result = execute(
        api, tmp_path, operations=[{"name": "prepare-public"}], candidate_report=report
    )
    assert result["results"][0] == {
        "failed": [],
        "outputs": {"verified": "true"},
        "logs": [],
    }
    output = tmp_path / "work/hoben-experimental-public/report.json"
    assert json.loads(output.read_text()) == report
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert not result["writes"] and not result["calls"]


def test_workflow_uploads_only_validated_projection_and_never_candidate_plaintext():
    workflow = yaml.load((ROOT / WORKFLOW).read_text(), Loader=yaml.BaseLoader)
    for name in ("dry-run", "observations"):
        steps = workflow["jobs"][name]["steps"]
        validation = next(s for s in steps if s.get("id") == "public-report")
        assert (
            "./trusted/.github/scripts/hoben-experimental-request.cjs"
            in validation["with"]["script"]
        )
        assert "preparePublicReport({context, core})" in validation["with"]["script"]
        assert set(validation["env"]) == {"EXPERIMENTAL_APPROVED_SHA"}
        uploads = [
            s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")
        ]
        reports = [s for s in uploads if "report" in s["with"]["name"]]
        assert len(reports) == 1
        upload = reports[0]
        assert steps.index(validation) < steps.index(upload)
        assert "steps.public-report.outputs.verified == 'true'" in upload["if"]
        assert (
            upload["with"]["path"]
            == "${{ runner.temp }}/hoben-experimental-public/report.json"
        )
        assert not any(
            "hoben-experimental-exports/report.json" in s["with"]["path"]
            for s in uploads
        )


def group(workflow, github, inputs=None):
    """Evaluate the actual boolean/path/format scheduling expression offline.

    These fixed expressions use JS-compatible syntax; authorization stays in
    the separately tested gate. No simulation of GitHub queue ordering is needed
    to compare the real mutex names and unrelated run groups.
    """
    definition = yaml.load(
        (ROOT / ".github/workflows" / workflow).read_text(), Loader=yaml.BaseLoader
    )
    assert definition["concurrency"]["cancel-in-progress"] == "false"
    expression = definition["concurrency"]["group"]
    if not expression.startswith("${{"):
        return expression
    result = subprocess.run(
        [
            shutil.which("node"),
            "-e",
            "const fs=require('node:fs');"
            "const x=JSON.parse(fs.readFileSync(0,'utf8'));"
            "const f=new Function('github','inputs','format',"
            "'return ('+x.expression+')');"
            "process.stdout.write(JSON.stringify(f(x.github,x.inputs,"
            "(pattern,id)=>pattern.replace('{0}',id))));",
        ],
        input=json.dumps(
            {"expression": expression[3:-2], "github": github, "inputs": inputs or {}}
        ),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert not result.stderr
    return json.loads(result.stdout)


def event(name="issues", label="manager-hoben-experimental-live", run=123):
    return {
        "event_name": name,
        "run_id": run,
        "ref": "refs/heads/main",
        "actor": "Guillaume0385",
        "event": {
            "action": "labeled",
            "label": {"name": label},
            "issue": {"number": 54},
            "pull_request": {
                "draft": False,
                "base": {"ref": "main"},
                "head": {"repo": {"full_name": "Guillaume0385/ha-hoben-community"}},
            },
        },
    }


@pytest.mark.parametrize(
    "workflow,context,inputs",
    [
        ("hoben-experimental-request.yml", event(), None),
        (
            "hoben-experimental-request.yml",
            event(label="manager-hoben-experimental-dry-run"),
            None,
        ),
        (
            "manager-live-hoben.yml",
            event("pull_request_target", "manager-live-hoben"),
            None,
        ),
        ("live-validation.yml", event("pull_request", "live-validation"), None),
        ("live-validation.yml", event("pull_request", "live-session-negative"), None),
        *[
            ("live-validation.yml", event("workflow_dispatch"), {"mode": mode})
            for mode in ("tls-only", "session-open", "read-v4-state")
        ],
        ("opened-client-boundary.yml", event("workflow_dispatch"), None),
    ],
)
def test_every_recognized_hoben_workflow_uses_the_same_repository_mutex(
    workflow, context, inputs
):
    assert group(workflow, context, inputs) == "hoben-boundary-campaign"


@pytest.mark.parametrize(
    "workflow,name",
    [
        ("hoben-experimental-request.yml", "issues"),
        ("manager-live-hoben.yml", "pull_request_target"),
        ("live-validation.yml", "pull_request"),
    ],
)
@pytest.mark.parametrize(
    "label", ["bug", "state:in-progress", "state:review", "documentation"]
)
def test_unrelated_labels_cannot_evict_an_authorized_pending_run(workflow, name, label):
    first = event(name, label, 100)
    second = event(name, label, 101)
    assert group(workflow, first) != "hoben-boundary-campaign"
    assert group(workflow, first) != group(workflow, second)


def test_same_live_mutex_covers_different_prs_and_excludes_pr_disguised_as_issue():
    first = event("pull_request_target", "manager-live-hoben")
    second = copy.deepcopy(first)
    first["event"]["pull_request"]["number"] = 55
    second["event"]["pull_request"]["number"] = 56
    second["run_id"] += 1
    assert (
        group("manager-live-hoben.yml", first)
        == group("manager-live-hoben.yml", second)
        == "hoben-boundary-campaign"
    )
    disguised = event()
    disguised["event"]["issue"]["pull_request"] = {"url": "synthetic"}
    assert (
        group("hoben-experimental-request.yml", disguised) != "hoben-boundary-campaign"
    )
