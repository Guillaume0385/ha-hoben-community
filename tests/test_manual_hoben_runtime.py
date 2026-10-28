"""Manual entry, real collectors, isolated process groups and publication offline."""

import asyncio
import json
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import launch_manual_hoben as parent
from scripts import run_manual_hoben as runner
from scripts.manual_hoben_context import PLANS, WORKFLOW, proof
from tests.test_experimental_boundary_capture import session as synthetic_h1_session
from tests.test_session_300_probe import PROOF
from tests.test_session_suite import Harness
from tests.test_session_suite_publication import node

ROOT = Path(__file__).resolve().parents[1]


def check_cleanup_in_running_loop(monkeypatch, harness):
    original = asyncio.run

    def checked_run(coroutine):
        async def checked():
            result = await coroutine
            harness.assert_closed()
            return result

        return original(checked())

    monkeypatch.setattr(runner.asyncio, "run", checked_run)


def test_manual_gate_with_offline_github_api():
    result = subprocess.run(
        ["node", "--test", "tests/js/manual-hoben.test.cjs"],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_only_dispatch_is_live_and_every_secret_is_after_recheck():
    workflows = {p.name for p in (ROOT / ".github/workflows").glob("*.yml")}
    assert workflows == {
        "hoben-manual.yml",
        "hoben-protocol-manual.yml",
        "hoben-ha-manual.yml",
        "validate.yml",
        "publish-release.yml",
    }
    source = (ROOT / ".github/workflows/hoben-manual.yml").read_text()
    config = yaml.load(source, Loader=yaml.BaseLoader)
    assert set(config["on"]) == {"workflow_dispatch"}
    assert config["on"]["workflow_dispatch"]["inputs"]["scenario"]["options"] == list(
        PLANS
    ) + ["hoben-live"]
    assert config["concurrency"]["cancel-in-progress"] == "false"
    assert config["concurrency"]["group"] == "hoben-read-only-observation"
    assert config["permissions"] == {}
    jobs = config["jobs"]
    assert jobs["collect"]["environment"] == "hoben-experimental"
    assert "github.run_attempt == 1" in jobs["collect"]["if"]
    for job_name, job in jobs.items():
        assert "env" not in job
        for step in job["steps"]:
            if "secrets." in json.dumps(step):
                assert job_name in {"collect", "collect-ha"} and step["id"] == "capture"
                assert step["if"] == "steps.recheck.outputs.approved == 'true'"
            if step.get("uses", "").startswith("actions/checkout"):
                assert step["with"]["ref"] == "${{ github.sha }}"
                assert step["with"]["persist-credentials"] == "false"
    assert "environment" not in jobs["publish"]
    assert set(jobs["publish"]["permissions"]) == {"contents"}


def test_main_campaign_registration_workflows_are_strictly_inert():
    # These two entries make Actions navigation possible on main; they must
    # never accidentally become real collectors without a separate promotion.
    catalogs = {
        "hoben-protocol-manual.yml": [
            "tls-only", "session-open", "read-v4-state", "h1h2",
            "session-300", "session-reconnect", "all",
        ],
        "hoben-ha-manual.yml": [
            "hoben-live", "open-errors", "refresh-v4", "session-reuse",
            "session-reconnect", "cleanup", "availability", "all",
        ],
    }
    for filename, scenarios in catalogs.items():
        source = (ROOT / ".github/workflows" / filename).read_text()
        config = yaml.load(source, Loader=yaml.BaseLoader)
        assert set(config["on"]) == {"workflow_dispatch"}
        assert config["on"]["workflow_dispatch"]["inputs"]["scenario"]["options"] == scenarios
        assert config["permissions"] == {}
        assert set(config["jobs"]) == {"not-activated"}
        job = config["jobs"]["not-activated"]
        assert set(job) == {"runs-on", "timeout-minutes", "permissions", "steps"}
        assert job["permissions"] == {}
        assert job["timeout-minutes"] == "1"
        assert len(job["steps"]) == 1
        step = job["steps"][0]
        assert set(step) == {"name", "shell", "run"}
        assert step["shell"] == "bash"
        assert "NOT RUN" in step["run"]
        assert "exit 1" in step["run"]
        assert "secrets." not in source
        assert "actions/checkout" not in source
        assert "environment:" not in source


@pytest.mark.parametrize(
    "progress", [0, 1, 2], ids=["before-first-ack", "after-h1h2", "during-session-300"]
)
@pytest.mark.parametrize("capture_outcome", ["failure", "cancelled"])
@pytest.mark.parametrize("artifact", ["valid", "missing", "invalid"])
def test_actual_result_step_requires_validated_start_evidence(
    tmp_path, progress, capture_outcome, artifact
):
    from scripts import run_experimental_boundary as h1

    selection = "all"
    started = list(PLANS[selection][:progress])
    control = tmp_path / "hoben-manual-control"
    control.mkdir(mode=0o700)
    parent.write_report(
        control / "report.json",
        {"schema": 1, "selection": selection, "started": started, "process_ok": False},
    )
    if progress:
        folder = tmp_path / "hoben-experimental-exports"
        folder.mkdir(mode=0o700)
        parent.write_report(
            folder / "report.json",
            h1.safe_report(
                {
                    "boundary_proven": False,
                    "sessions": [synthetic_h1_session(i) for i in range(12)],
                },
                interrupted=False,
                provenance=PROOF | {"candidate_sha": PROOF["merge_sha"]},
            ),
        )
    config = yaml.load(
        (ROOT / ".github/workflows/hoben-manual.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    step = config["jobs"]["result"]["steps"][-1]
    values = {
        "APPROVED_PR": str(PROOF["pr_number"]),
        "APPROVED_CANDIDATE": PROOF["candidate_sha"],
        "APPROVED_SELECTION": selection,
        "APPROVED": "true",
        "COLLECTION_RESULT": capture_outcome,
        "PUBLICATION_RESULT": "success" if artifact != "missing" else "failure",
        "ADMITTED": "true",
        "CAPTURE_OUTCOME": capture_outcome,
    }
    # Resolve the actual result step's environment, including legacy inputs if
    # present, so the reviewed workflow's fallback fails this regression test.
    environment = {k: values[k] for k in step["env"]}
    environment["GITHUB_RUN_ATTEMPT"] = "1"
    result = node(
        """
const payload=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const [root,p,source,environment,artifact]=payload;
const fs=require('node:fs'),path=require('node:path');
const checkoutRequire=require('node:module').createRequire(
  process.cwd()+'/result-step.cjs');
process.env.RUNNER_TEMP=root;
const api=checkoutRequire('./.github/scripts/manual-hoben-report.cjs');
let outputs={},errors=[];
const core={setOutput:(k,v)=>outputs[k]=v,setFailed:v=>errors.push(v)};
api.prepare({core,proof:p});
const parts=[0,1,2,3].map(i=>outputs['report_'+i+'_b64']);outputs={};
api.publish({core,proof:p,parts});
if(artifact!=='missing') {
  const target=path.join(root,'public-report');fs.mkdirSync(target);
  const r=api.readReport(path.join(root,'hoben-manual-public/report.json'),p);
  if(artifact==='invalid')r.private='SYNTHETIC_UNVALIDATED_FIELD';
  fs.writeFileSync(path.join(target,'report.json'),JSON.stringify(r),{mode:0o600});
}
Object.assign(process.env,environment);process.chdir(root);
let table,summary='';const failures=[];
const summaryApi={addTable:v=>{table=v;return summaryApi;},
  addRaw:v=>{summary+=v;return summaryApi;},write:async()=>{}};
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
(async()=>{
  await new AsyncFunction('core','context','require',source)(
    {summary:summaryApi,setFailed:v=>failures.push(v)},
    {sha:p.merge_sha,runId:p.run_id},checkoutRequire);
  process.stdout.write(JSON.stringify({errors,failures,summary,
    states:Object.fromEntries(table.slice(1))}));
})();
""",
        [
            str(tmp_path),
            PROOF | {"selection": selection},
            step["with"]["script"],
            environment,
            artifact,
        ],
    )
    expected = dict.fromkeys(PLANS[selection], "NOT RUN")
    if artifact == "valid":
        if progress == 1:
            expected["h1h2"] = "FAILURE"
        elif progress == 2:
            expected.update({"h1h2": "INCONCLUSIVE", "session-300": "FAILURE"})
    assert result["errors"] == []
    assert result["states"] == expected
    assert result["failures"]
    assert "Résultat global : FAILURE" in result["summary"]
    assert "SYNTHETIC_UNVALIDATED_FIELD" not in json.dumps(result)


@pytest.mark.parametrize("selection", ["session-300", "session-reconnect", "all"])
@pytest.mark.parametrize("mode", ["recovered", "no_disconnect"])
def test_manual_session_choices_use_real_owners_and_preserve_outcomes(
    monkeypatch, selection, mode
):
    h = Harness(mode)
    check_cleanup_in_running_loop(monkeypatch, h)
    armed, reports = [], {}
    monkeypatch.setattr(runner, "arm", armed.append)
    monkeypatch.setattr(
        runner, "save", lambda folder, report, limit: reports.update({folder: report})
    )
    runner.sessions(
        selection,
        "b" * 32,
        "0" * 32,
        PROOF,
        clock=h.clock,
        sleep=h.sleep,
        make_lifecycle=h.make,
    )
    assert armed == (
        ["session-300", "session-reconnect"] if selection == "all" else [selection]
    )
    report = next(iter(reports.values()))
    if selection == "all":
        assert report["session_300"]["result"] == "continuous_300s"
        result = report["session_reconnect_no_pong"]["result"]
    else:
        result = report["result"]
    assert result == (
        "continuous_300s"
        if selection == "session-300"
        else "recovered_120s"
        if mode == "recovered"
        else "inconclusive"
    )
    assert "private" not in json.dumps(report)


@pytest.mark.parametrize("ok", [False, True])
def test_all_stops_after_blocking_h1h2_failure(monkeypatch, ok):
    monkeypatch.setattr(sys, "argv", ["run_manual_hoben.py"])
    monkeypatch.setattr(runner, "proof", lambda *args: ("all", PROOF))
    for key in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "GITHUB_STEP_SUMMARY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOBEN_USER_GUID", "b" * 32)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "0" * 32)
    calls = []
    monkeypatch.setattr(runner, "arm", lambda s: calls.append(("arm", s)))
    monkeypatch.setattr(
        runner, "h1h2", lambda *args: calls.append(("collect", "h1h2")) or ok
    )
    monkeypatch.setattr(
        runner, "sessions", lambda *args: calls.append(("sessions", args[0]))
    )
    assert runner.main() == 0
    assert calls == [("arm", "h1h2"), ("collect", "h1h2")] + (
        [("sessions", "all")] if ok else []
    )


def test_child_environment_has_no_runner_tokens_or_arbitrary_mode():
    source = {k: "allowed" for k in parent.ALLOWED}
    source.update(
        {
            k: "PRIVATE"
            for k in (
                "GITHUB_TOKEN",
                "ACTIONS_RUNTIME_TOKEN",
                "GITHUB_OUTPUT",
                "PYTHONPATH",
                "LD_PRELOAD",
            )
        }
    )
    assert "PRIVATE" not in json.dumps(parent.collector_environment(source))
    assert parent.SECONDS == {
        "h1h2": 1800,
        "session-300": 360,
        "session-reconnect": 600,
    }
    assert set(parent.collector_environment(source)) == set(parent.ALLOWED) | {"PATH"}


def test_local_manual_context_checks_every_field_before_identity(monkeypatch, tmp_path):
    candidate, trusted = tmp_path / "candidate", tmp_path / "trusted"
    candidate.mkdir()
    trusted.mkdir()
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "inputs": {"scenario": "all"},
                "repository": {
                    "id": 1401398724,
                    "full_name": "Guillaume0385/ha-hoben-community",
                },
                "sender": {"id": 18246624, "login": "Guillaume0385", "type": "User"},
            }
        )
    )
    source = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
        "GITHUB_SHA": PROOF["merge_sha"],
        "GITHUB_WORKFLOW_SHA": PROOF["merge_sha"],
        "GITHUB_RUN_ID": str(PROOF["run_id"]),
        "GITHUB_EVENT_PATH": str(event),
        "MANUAL_HOBEN_SHA": PROOF["merge_sha"],
        "MANUAL_HOBEN_CANDIDATE": PROOF["candidate_sha"],
        "MANUAL_HOBEN_PR": str(PROOF["pr_number"]),
        "MANUAL_HOBEN_SCENARIO": "all",
    }
    monkeypatch.setattr(
        subprocess, "check_output", lambda *args, **kwargs: PROOF["merge_sha"].encode()
    )
    assert proof(source, candidate) == ("all", PROOF)
    for checkout in (candidate, trusted):
        with pytest.raises(ValueError):
            proof(source | {"RUNNER_TEMP": str(checkout)}, candidate)
    for key in source:
        changed = dict(source)
        changed[key] = "PRIVATE_INVALID"
        with pytest.raises((ValueError, OSError)):
            proof(changed, candidate)


@pytest.mark.parametrize("selection", ["h1h2", "session-300", "session-reconnect"])
def test_new_parent_kills_resistant_child_and_descendant(
    monkeypatch, tmp_path, selection
):
    candidate = tmp_path / "candidate"
    (candidate / "scripts").mkdir(parents=True)
    token = {"h1h2": "H", "session-300": "S", "session-reconnect": "R"}[selection]
    script = """import os,signal,subprocess,sys,time
signal.signal(signal.SIGTERM,signal.SIG_IGN)
worker="import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
child=subprocess.Popen([sys.executable,'-c',worker])
open(os.environ['RUNNER_TEMP']+'/descendant','w').write(str(child.pid))
os.write(int(os.environ['MANUAL_CONTROL_FD']),TOKEN)
os.read(int(os.environ['MANUAL_ACK_FD']),1)
time.sleep(60)
""".replace("TOKEN", repr(token.encode()))
    (candidate / "scripts/run_manual_hoben.py").write_text(script)
    monkeypatch.setattr(parent, "proof", lambda *args: (selection, PROOF))
    monkeypatch.setattr(parent, "SECONDS", {selection: 3})
    assert parent.supervise(candidate, {"RUNNER_TEMP": str(tmp_path)}) == 0
    status = json.loads((tmp_path / "hoben-manual-control/report.json").read_text())
    assert status == {
        "schema": 1,
        "selection": selection,
        "started": [selection],
        "process_ok": False,
    }
    pid = int((tmp_path / "descendant").read_text())
    state = Path(f"/proc/{pid}/stat")
    assert not state.exists() or state.read_text().split()[2] == "Z"


def test_real_report_survives_isolated_export_publication_and_result(
    tmp_path, monkeypatch
):
    h = Harness()
    check_cleanup_in_running_loop(monkeypatch, h)
    reports = {}
    monkeypatch.setattr(runner, "arm", lambda *args: None)
    monkeypatch.setattr(
        runner, "save", lambda folder, report, limit: reports.update({folder: report})
    )
    runner.sessions(
        "session-reconnect",
        "b" * 32,
        "0" * 32,
        PROOF,
        clock=h.clock,
        sleep=h.sleep,
        make_lifecycle=h.make,
    )
    folder = tmp_path / "hoben-session-reconnect-exports"
    folder.mkdir()
    (folder / "report.json").write_text(json.dumps(next(iter(reports.values()))))
    control = tmp_path / "hoben-manual-control"
    control.mkdir()
    (control / "report.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "selection": "session-reconnect",
                "started": ["session-reconnect"],
                "process_ok": True,
            }
        )
    )
    result = node(
        """
const [root,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.env.RUNNER_TEMP=root;
const api=require('./.github/scripts/manual-hoben-report.cjs');
let outputs={},errors=[];
const core={setOutput:(k,v)=>outputs[k]=v,setFailed:m=>errors.push(m)};
api.prepare({core,proof:p});
const parts=[0,1,2,3].map(i=>outputs['report_'+i+'_b64']);outputs={};
api.publish({core,proof:p,parts});
const r=api.readReport(root+'/hoben-manual-public/report.json',p);
process.stdout.write(JSON.stringify({errors,outputs,states:api.states(r),complete:api.completed(r,p)}));
""",
        [str(tmp_path), PROOF | {"selection": "session-reconnect"}],
    )
    assert result["errors"] == [] and result["outputs"] == {"report": "true"}
    assert (
        result["complete"] is True
        and result["states"]["session-reconnect"] == "SUCCESS"
    )


@pytest.mark.parametrize("late", [False, True])
def test_all_deadlines_are_armed_before_ack_and_late_transition_is_denied(
    monkeypatch, tmp_path, late
):
    now, requests, acks, killed = (
        [0.0],
        [(0, b"H"), (1800 if late else 100, b"S"), (400, b"R")],
        [],
        [],
    )
    process = SimpleNamespace(pid=987654, poll=lambda: None, wait=lambda **kw: 0)
    monkeypatch.setattr(parent, "proof", lambda *args: ("all", PROOF))
    monkeypatch.setattr(parent.subprocess, "Popen", lambda *args, **kw: process)
    current = [None]

    class Selector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def select(self, timeout):
            assert 0 < timeout <= 0.2
            if requests:
                now[0], current[0] = requests.pop(0)
                return [object()]
            now[0] = 999  # R was armed at400: deadline1000, one second for reaping.
            return []

    monkeypatch.setattr(parent.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(parent.os, "read", lambda *args: current[0])
    monkeypatch.setattr(
        parent.os, "write", lambda fd, token: acks.append((token, now[0])) or 1
    )
    monkeypatch.setattr(parent.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    assert (
        parent.supervise(tmp_path, {"RUNNER_TEMP": str(tmp_path)}, clock=lambda: now[0])
        == 0
    )
    assert acks == ([(b"H", 0)] if late else [(b"H", 0), (b"S", 100), (b"R", 400)])
    assert killed == [(987654, signal.SIGKILL)]
    assert not json.loads((tmp_path / "hoben-manual-control/report.json").read_text())[
        "process_ok"
    ]


@pytest.mark.parametrize("mode", ["recovered", "first_invalid"])
def test_full_h1h2_then_session_suite_bundle_and_stop_are_revalidated(
    monkeypatch, tmp_path, mode
):
    from scripts import run_experimental_boundary as h1

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("HOBEN_USER_GUID", "b" * 32)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "0" * 32)

    def collect(private):
        (private / "raw-private.bin").write_bytes(b"PRIVATE")
        return {
            "boundary_proven": False,
            "sessions": [synthetic_h1_session(i) for i in range(12)],
        }, False

    monkeypatch.setattr(h1, "collect", collect)
    assert runner.h1h2("b" * 32, "0" * 32, PROOF)
    assert not list(tmp_path.glob("hoben-experimental-private-*"))
    h = Harness(mode)
    check_cleanup_in_running_loop(monkeypatch, h)
    stages = ["h1h2"]
    monkeypatch.setattr(runner, "arm", stages.append)
    runner.sessions(
        "all",
        "b" * 32,
        "0" * 32,
        PROOF,
        clock=h.clock,
        sleep=h.sleep,
        make_lifecycle=h.make,
    )
    control = tmp_path / "hoben-manual-control"
    control.mkdir()
    (control / "report.json").write_text(
        json.dumps(
            {"schema": 1, "selection": "all", "started": stages, "process_ok": True}
        )
    )
    result = node(
        """
const [root,p]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.env.RUNNER_TEMP=root;
const api=require('./.github/scripts/manual-hoben-report.cjs');
let outputs={},errors=[];
api.prepare({core:{setOutput:(k,v)=>outputs[k]=v,setFailed:v=>errors.push(v)},proof:p});
require('node:assert/strict').deepEqual(Object.keys(outputs),[0,1,2,3].map(i=>'report_'+i+'_b64'));
const parts=Object.values(outputs);
require('node:assert/strict').ok(parts.every(x=>x.length<=120000));
const r=api.validate(JSON.parse(Buffer.from(parts.join(''),'base64')),p);
process.stdout.write(JSON.stringify({errors,states:api.states(r),complete:api.completed(r,p)}));
""",
        [str(tmp_path), PROOF | {"selection": "all"}],
    )
    assert result["errors"] == [] and result["states"]["h1h2"] == "INCONCLUSIVE"
    assert result["complete"] == (mode == "recovered")
    assert result["states"]["session-reconnect"] == (
        "SUCCESS" if mode == "recovered" else "NOT RUN"
    )
    assert stages == (
        ["h1h2", "session-300", "session-reconnect"]
        if mode == "recovered"
        else ["h1h2", "session-300"]
    )
