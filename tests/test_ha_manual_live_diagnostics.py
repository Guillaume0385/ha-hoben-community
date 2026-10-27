"""Reproduce C2c input refusal offline; never execute a live supervisor."""

import json
import os
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest
import yaml

from scripts.ha_live_proof import empty_evidence
from scripts.ha_manual_live_report import build_live_report, not_run
from tests.test_ha_manual_live import (
    PROOF,
    ROOT,
    live_report,
    node_accepts,
    source_context,
)
from tests.test_ha_session_supervisor import IMAGE


def setup_capture(tmp_path, monkeypatch):
    launch, candidate, storage, source = source_context(tmp_path, monkeypatch)
    for key, value in source.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HOBEN_USER_GUID", "1" * 32)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "D" * 32)
    monkeypatch.setattr(launch.sys, "argv", ["launch_ha_manual_live.py"])
    (storage / "hoben-ha-runtime.id").write_text(IMAGE)
    supervisor = Mock(return_value=live_report())
    monkeypatch.setattr(launch, "supervise_live", supervisor)
    return launch, storage, supervisor


def diagnostic(capsys, expected):
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "HA_LIVE_DIAGNOSTIC " + expected + "\n"


@pytest.mark.parametrize(
    "key,value,category",
    [
        ("HOBEN_DEVICE_GUID", "", "device_input_missing"),
        ("HOBEN_DEVICE_GUID", None, "device_input_missing"),
        ("HOBEN_DEVICE_GUID", "0" * 32, "identity_invalid"),
        ("HOBEN_DEVICE_GUID", "PRIVATE_INVALID\n::error::injected", "identity_invalid"),
        ("HOBEN_DEVICE_GUID", "é" * 32, "identity_invalid"),
        ("HOBEN_USER_GUID", "", "user_input_missing"),
        ("HOBEN_USER_GUID", None, "user_input_missing"),
    ],
)
def test_required_input_refusal_is_explicit_without_start_or_private_data(
    tmp_path, monkeypatch, capsys, key, value, category
):
    launch, storage, supervisor = setup_capture(tmp_path, monkeypatch)
    if value is None:
        monkeypatch.delenv(key)
    else:
        monkeypatch.setenv(key, value)
    assert launch.main() == 1
    supervisor.assert_not_called()
    report = json.loads((storage / "hoben-ha-live-public/report.json").read_text())
    assert report == not_run(PROOF) and node_accepts(report)
    diagnostic(
        capsys,
        f"phase=identity category={category} started=false "
        "report=valid session=NOT_RUN exit_code=1",
    )


@pytest.mark.parametrize(
    "failure", ["context", "image", "supervisor", "report", "write"]
)
def test_failures_never_echo_exception_or_invent_no_start(
    tmp_path, monkeypatch, capsys, failure
):
    launch, storage, supervisor = setup_capture(tmp_path, monkeypatch)
    private = RuntimeError("PRIVATE_INVALID\n::error::injected")
    expected = {
        "context": (
            "provenance category=context_refused started=false "
            "report=absent session=NOT_RUN"
        ),
        "image": (
            "image category=image_refused started=false report=valid session=NOT_RUN"
        ),
        "supervisor": (
            "supervision category=supervisor_failed started=unattested "
            "report=absent session=FAILURE"
        ),
        "report": (
            "report category=report_refused started=unattested "
            "report=absent session=FAILURE"
        ),
        "write": (
            "report category=report_refused started=true report=absent session=FAILURE"
        ),
    }[failure]
    if failure == "context":
        monkeypatch.setattr(launch, "provenance", Mock(side_effect=private))
    elif failure == "image":
        (storage / "hoben-ha-runtime.id").unlink()
    elif failure == "supervisor":
        supervisor.side_effect = private
    elif failure == "report":
        supervisor.return_value = {"private": str(private)}
    else:
        monkeypatch.setattr(launch, "write_report", Mock(side_effect=private))
    assert launch.main() == 1
    if failure in ("context", "image"):
        supervisor.assert_not_called()
    assert (storage / "hoben-ha-live-public/report.json").exists() == (
        failure == "image"
    )
    diagnostic(capsys, "phase=" + expected + " exit_code=1")


@pytest.mark.parametrize("state", ["SUCCESS", "FAILURE", "NOT RUN"])
def test_validated_outcomes_reach_independent_publication(
    tmp_path, monkeypatch, capsys, state
):
    launch, storage, supervisor = setup_capture(tmp_path, monkeypatch)
    report = live_report()
    if state == "NOT RUN":
        report = not_run(PROOF)
    elif state == "FAILURE":
        report = build_live_report(
            PROOF,
            {**report["supervisor"], "network": "none", "reason": "worker_failure"},
            empty_evidence(),
        )
    supervisor.return_value = report
    assert launch.main() == 0
    public = json.loads((storage / "hoben-ha-live-public/report.json").read_text())
    assert public == report and public["outcome"] == state and node_accepts(public)
    started = "false" if state == "NOT RUN" else "true"
    diagnostic(
        capsys,
        "phase=report category=reported "
        f"started={started} report=valid session={state.replace(' ', '_')} exit_code=0",
    )


def test_actual_isolated_command_reproduces_empty_input_after_real_git_checks(tmp_path):
    """Real -I/provenance/image path, synthetic event/identity, no Docker call."""
    trusted, candidate, storage = (
        tmp_path / n for n in ("trusted", "candidate", "storage")
    )
    trusted.mkdir()
    storage.mkdir()
    subprocess.run(["git", "init", "-q", str(trusted)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(trusted),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
            "--allow-empty",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "clone", "-q", str(trusted), str(candidate)],
        check=True,
        capture_output=True,
    )
    sha = (
        subprocess.check_output(["git", "-C", str(trusted), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    shutil.copytree(ROOT / "scripts", trusted / "scripts")
    # Build a complete synthetic runner context; run real provenance, not its double.
    from scripts.manual_hoben_context import WORKFLOW

    event = storage / "event.json"
    event.write_text(
        json.dumps(
            {
                "inputs": {"scenario": "hoben-live"},
                "repository": {
                    "id": 1401398724,
                    "full_name": "Guillaume0385/ha-hoben-community",
                },
                "sender": {"id": 18246624, "login": "Guillaume0385", "type": "User"},
            }
        )
    )
    env = {
        "PATH": os.environ["PATH"],
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
        "GITHUB_SHA": sha,
        "GITHUB_WORKFLOW_SHA": sha,
        "GITHUB_EVENT_PATH": str(event),
        "RUNNER_TEMP": str(storage),
        "MANUAL_HOBEN_SHA": sha,
        "MANUAL_HOBEN_SCENARIO": "hoben-live",
        "GITHUB_RUN_ID": "20",
        "MANUAL_HOBEN_PR": "128",
        "MANUAL_HOBEN_CANDIDATE": "b" * 40,
        "MANUAL_HOBEN_CI": "10",
        "MANUAL_HOBEN_ENVIRONMENT": "30",
        "MANUAL_HOBEN_POLICY": "c" * 64,
        "MANUAL_HOBEN_CLAIM": "d" * 40,
        "HOBEN_USER_GUID": "1" * 32,
        "HOBEN_DEVICE_GUID": "",
    }
    (storage / "hoben-ha-runtime.id").write_text(IMAGE)
    harness = (
        "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
        "import scripts.ha_session_supervisor as s;"
        # Exit 97 if a regression ever reaches supervisor; no engine/network.
        "s.supervise_live=lambda *a,**k:sys.exit(97);"
        "entry=sys.argv[2];sys.argv=[entry];runpy.run_path(entry,run_name='__main__')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            harness,
            str(trusted),
            str(trusted / "scripts/launch_ha_manual_live.py"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr == (
        "HA_LIVE_DIAGNOSTIC phase=identity category=device_input_missing "
        "started=false report=valid session=NOT_RUN exit_code=1\n"
    )
    report = json.loads((storage / "hoben-ha-live-public/report.json").read_text())
    assert node_accepts(report, PROOF | {"merge_sha": sha})


@pytest.mark.parametrize("state", ["missing", "early", "not_run", "success"])
def test_real_result_script_keeps_global_failure_when_collection_failed(state):
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-manual.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    job = workflow["jobs"]["collect-ha"]
    exports = next(s for s in job["steps"] if s.get("id") == "exports")
    assert "steps.capture.outcome == 'failure'" in exports["if"]
    assert "steps.recheck.outputs.approved == 'true'" in exports["if"]
    script = workflow["jobs"]["result-ha"]["steps"][-1]["with"]["script"]
    report = not_run(PROOF) if state == "not_run" else live_report()
    if state == "early":
        report = build_live_report(
            PROOF,
            {**report["supervisor"], "network": "none", "reason": "worker_failure"},
            empty_evidence(),
        )
    harness = """
const fs=require('node:fs');
const {script,report,missing}=JSON.parse(fs.readFileSync(0,'utf8'));
const errors=[],summary={table:[],raw:'',addHeading(){return this},
addTable(v){this.table=v;return this},
addRaw(v){this.raw+=v;return this},async write(){}};
const api=require('./.github/scripts/ha-manual-live-report.cjs');
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('core','context','require','process',script)(
 {summary,setFailed:v=>errors.push(v)},{sha:report.proof.merge_sha,runId:20},
 ()=>({...api,read:(file,p)=>{if(missing)throw Error('absent');
   return api.validate(report,p)}}),
 {env:{APPROVED:'true',GITHUB_RUN_ATTEMPT:'1',APPROVED_PR:'128',APPROVED_CANDIDATE:'b'.repeat(40),
 APPROVED_CI:'10',APPROVED_ENVIRONMENT:'30',APPROVED_POLICY:'c'.repeat(64),APPROVED_CLAIM:'d'.repeat(40),
 COLLECTION_RESULT:'failure',PUBLICATION_RESULT:missing?'skipped':'success'}}
).then(()=>process.stdout.write(JSON.stringify({errors,table:summary.table,raw:summary.raw})));
"""
    result = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps(
            {
                "script": script,
                "report": report,
                "missing": state == "missing",
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert result.stderr == "" and data["errors"]
    assert ["Collecte (job)", "failure"] in data["table"]
    expected = {
        "missing": "NOT RUN",
        "early": "FAILURE",
        "not_run": "NOT RUN",
        "success": "SUCCESS",
    }[state]
    assert ["hoben-live (preuve de session)", expected] in data["table"]
    assert "Résultat global : FAILURE" in data["raw"]
