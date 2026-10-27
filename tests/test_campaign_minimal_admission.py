"""Run the actual embedded controllers offline; no Actions/collector/network."""

import json
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ("hoben-protocol-manual.yml", "hoben-ha-manual.yml")
CHOICES = {
    FILES[0]: (
        "tls-only",
        "session-open",
        "read-v4-state",
        "h1h2",
        "session-300",
        "session-reconnect",
        "all",
    ),
    FILES[1]: (
        "hoben-live",
        "open-errors",
        "refresh-v4",
        "session-reuse",
        "session-reconnect",
        "cleanup",
        "availability",
        "all",
    ),
}
CASES = [(name, choice) for name in FILES for choice in CHOICES[name]]
NODE = shutil.which("node")


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden")

    for key in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, key, denied)


def context(scenario="all", ref="refs/heads/experimental", **changes):
    value = {
        "github.repository": "Guillaume0385/ha-hoben-community",
        "github.event_name": "workflow_dispatch",
        "github.actor": "Guillaume0385",
        "github.triggering_actor": "Guillaume0385",
        "github.ref": ref,
        "inputs.scenario": scenario,
        "needs.admission.result": "success",
        "needs.admission.outputs.admitted": "true",
    }
    value.update(changes)
    return value


def controller(name, job, ctx, directory, extra=None, event_body=None):
    assert NODE is not None, "Node is required by the workflow controllers"
    w = workflow(name)
    step = w["jobs"][job]["steps"][0]
    lines = step["run"].splitlines()
    assert lines[0] == "node <<'NODE'" and lines[-1] == "NODE"
    code = "\n".join(lines[1:-1]) + "\n"
    # Deny network/child-process modules and fetch in the separate Node process.
    prelude = """
const testModule = require('node:module');
const testLoad = testModule._load;
testModule._load = function(name, ...args) {
  if (name !== 'node:fs') throw new Error('Forbidden module in offline controller');
  return testLoad.call(this, name, ...args);
};
globalThis.fetch = () => { throw new Error('Network forbidden'); };
"""
    output, summary = directory / "output", directory / "summary"
    event = directory / "event.json"
    event.write_text(
        json.dumps({"inputs": {"scenario": ctx["inputs.scenario"]}})
        if event_body is None
        else event_body
    )
    env = {
        "CAMPAIGN": w["env"]["CAMPAIGN"],
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_EVENT_PATH": str(event),
    }
    for key, expression in step["env"].items():
        match = re.fullmatch(r"\$\{\{ ([a-z_.]+) \}\}", expression)
        assert match, "Only native context-to-environment wiring is allowed"
        env[key] = ctx[match[1]]
    env.update(extra or {})
    result = subprocess.run(
        [
            NODE,
            "--permission",
            "--allow-fs-write=" + str(directory),
            "--allow-fs-read=" + str(event),
        ],
        input=prelude + code,
        text=True,
        env=env,
        capture_output=True,
        cwd=directory,
        timeout=5,
    )
    outputs = (
        dict(line.split("=", 1) for line in output.read_text().splitlines())
        if output.exists()
        else {}
    )
    text = summary.read_text() if summary.exists() else ""
    assert "SYNTHETIC_PRIVATE_INPUT" not in result.stdout + result.stderr + text
    return result, outputs, text


def slot_enabled(w, outputs, admission_result="success"):
    expression = w["jobs"]["scenario-slot"]["if"]
    assert expression == (
        "needs.admission.result == 'success' && "
        "needs.admission.outputs.admitted == 'true' && "
        "needs.admission.outputs.collector_ready == 'true'"
    )
    return (
        admission_result == "success"
        and outputs.get("admitted") == "true"
        and outputs.get("collector_ready") == "true"
    )


@pytest.mark.parametrize("name", FILES)
def test_workflow_dispatch_choices_empty_permissions_and_shared_mutex(name):
    w = workflow(name)
    assert set(w) == {"name", "on", "permissions", "concurrency", "env", "jobs"}
    assert set(w["on"]) == {"workflow_dispatch"}
    assert set(w["on"]["workflow_dispatch"]) == {"inputs"}
    inputs = w["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"scenario"}
    assert inputs["scenario"]["options"] == list(CHOICES[name])
    assert (
        inputs["scenario"]["required"] is True
        and inputs["scenario"]["type"] == "choice"
    )
    assert inputs["scenario"]["default"] == CHOICES[name][0]
    assert w["permissions"] == {}
    assert w["env"] == {"CAMPAIGN": "protocol" if name == FILES[0] else "ha"}
    assert w["concurrency"] == {
        "group": "hoben-read-only-observation",
        "cancel-in-progress": False,
        "queue": "max",
    }
    old = yaml.safe_load((ROOT / ".github/workflows/hoben-manual.yml").read_text())
    assert w["concurrency"] == old["concurrency"]
    assert set(w["jobs"]) == {"admission", "scenario-slot", "result"}
    for key, job in w["jobs"].items():
        common = {"runs-on", "timeout-minutes", "permissions", "steps"}
        extra = {
            "admission": {"outputs"},
            "scenario-slot": {"needs", "if", "environment"},
            "result": {"needs", "if"},
        }[key]
        assert set(job) == common | extra
        assert job["permissions"] == {} and job["runs-on"] == "ubuntu-latest"
        assert job["timeout-minutes"] == 1
        assert len(job["steps"]) == 1 and "uses" not in job["steps"][0]
        step = job["steps"][0]
        expected = {"name", "shell", "run"}
        if key in {"admission", "result"}:
            expected.add("env")
        if key == "admission":
            expected.add("id")
        assert set(step) == expected and step["shell"] == "bash"
    assert "environment" not in w["jobs"]["admission"]
    assert "environment" not in w["jobs"]["result"]
    assert w["jobs"]["scenario-slot"]["environment"] == (
        "hoben-experimental" if name == FILES[0] else "hoben-live"
    )
    assert w["jobs"]["scenario-slot"]["needs"] == "admission"
    assert w["jobs"]["result"]["needs"] == ["admission", "scenario-slot"]
    assert w["jobs"]["result"]["if"] == "always()"
    assert w["jobs"]["admission"]["outputs"] == {
        "admitted": "${{ steps.context.outputs.admitted }}",
        "collector_ready": "${{ steps.context.outputs.collector_ready }}",
    }
    assert w["jobs"]["admission"]["steps"][0]["id"] == "context"
    assert w["jobs"]["admission"]["steps"][0]["env"] == {
        "REQUEST_REPOSITORY": "${{ github.repository }}",
        "REQUEST_EVENT": "${{ github.event_name }}",
        "REQUEST_ACTOR": "${{ github.actor }}",
        "REQUEST_TRIGGERING_ACTOR": "${{ github.triggering_actor }}",
        "REQUEST_REF": "${{ github.ref }}",
    }
    assert w["jobs"]["result"]["steps"][0]["env"] == {
        "ADMISSION_RESULT": "${{ needs.admission.result }}",
        "ADMITTED": "${{ needs.admission.outputs.admitted }}",
    }
    encoded = json.dumps(w)
    for forbidden in (
        "secrets.",
        "GITHUB_TOKEN",
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
        "checkout",
        "github.sha",
        "run_attempt",
        "createRef",
        "github_campaign_",
        "manual_campaign_contract",
    ):
        assert forbidden not in encoded
    # Unknown input must not be expanded into the step's automatically logged env.
    assert "${{ inputs.scenario }}" not in json.dumps(w["jobs"])


@pytest.mark.parametrize("name,scenario", CASES)
@pytest.mark.parametrize("ref", ["refs/heads/experimental", "refs/heads/main"])
@pytest.mark.parametrize("attempt", ["1", "2", "10"])
def test_actual_admission_accepts_both_refs_and_reruns_but_no_collector(
    name, scenario, ref, attempt, tmp_path
):
    result, outputs, _ = controller(
        name,
        "admission",
        context(scenario, ref),
        tmp_path,
        {"GITHUB_RUN_ATTEMPT": attempt},
    )
    assert result.returncode == 0 and result.stderr == ""
    assert outputs == {"admitted": "true", "collector_ready": "false"}
    assert not slot_enabled(workflow(name), outputs)


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize(
    "key,bad",
    [
        ("github.event_name", "push"),
        ("github.event_name", "pull_request"),
        ("github.event_name", "workflow_call"),
        ("github.actor", "someone-else"),
        ("github.triggering_actor", "someone-else"),
        ("github.triggering_actor", ""),
        ("github.repository", "fork/ha-hoben-community"),
        ("github.ref", "refs/heads/other"),
        ("github.ref", "refs/tags/main"),
        ("github.ref", "main"),
        ("inputs.scenario", "unknown"),
        ("inputs.scenario", ""),
        ("inputs.scenario", "$(touch SYNTHETIC_PRIVATE_INPUT)"),
        ("github.actor", "SYNTHETIC_PRIVATE_INPUT\n::notice::injected"),
    ],
)
def test_actual_admission_refuses_unauthorized_or_unknown_context(
    name, key, bad, tmp_path
):
    ctx = context(**{key: bad})
    result, outputs, _ = controller(name, "admission", ctx, tmp_path)
    assert result.returncode == 1
    assert outputs == {"admitted": "false", "collector_ready": "false"}
    assert not slot_enabled(workflow(name), outputs)
    assert "admission_context_refused" in result.stdout


@pytest.mark.parametrize("name", FILES)
def test_no_pr_review_merge_ci_or_sha_precondition(name, tmp_path):
    result, outputs, _ = controller(
        name,
        "admission",
        context(),
        tmp_path,
        {
            "GITHUB_SHA": "documentary-commit-without-pr",
            "PR_NUMBER": "",
            "MANAGER_REVIEW": "absent",
            "CI_STATUS": "failure",
            "HOBEN_USER_GUID": "SYNTHETIC_PRIVATE_INPUT",
            "GITHUB_TOKEN": "SYNTHETIC_PRIVATE_INPUT",
        },
    )
    assert result.returncode == 0 and outputs["admitted"] == "true"
    assert outputs["collector_ready"] == "false"


@pytest.mark.parametrize("name", FILES)
def test_future_slot_really_requires_context_and_implementation_and_keeps_environment(
    name,
):
    w = workflow(name)
    assert slot_enabled(w, {"admitted": "true", "collector_ready": "true"})
    for admission, ready, result in [
        ("false", "true", "success"),
        ("true", "false", "success"),
        ("true", "true", "failure"),
        ("true", "true", "cancelled"),
    ]:
        assert not slot_enabled(
            w, {"admitted": admission, "collector_ready": ready}, result
        )
    script = w["jobs"]["scenario-slot"]["steps"][0]["run"]
    assert script == (
        "printf '%s\\n' '::error::NOT RUN: aucun collecteur raccordé "
        "à ce point insertion.'\nexit 1\n"
    )


@pytest.mark.parametrize("name,scenario", CASES)
@pytest.mark.parametrize("gate", ["success", "failure", "cancelled"])
def test_actual_result_always_reports_every_selected_scenario_not_run_and_fails(
    name, scenario, gate, tmp_path
):
    ctx = context(
        scenario,
        **{
            "needs.admission.result": gate,
            "needs.admission.outputs.admitted": "true"
            if gate == "success"
            else "false",
        },
    )
    result, _, text = controller(name, "result", ctx, tmp_path)
    assert result.returncode == 1 and "scenarios_not_connected" in result.stderr
    report = json.loads(result.stdout)
    expected = CHOICES[name][:-1] if scenario == "all" else (scenario,)
    assert [s["scenario"] for s in report["stages"]] == list(expected)
    assert all(s["status"] == "NOT RUN" for s in report["stages"])
    assert report["execution"] == "NOT RUN" and report["actions_result"] == "FAILURE"
    assert report["admission"] == ("checked" if gate == "success" else "not_verified")
    assert "Résultat global : FAILURE" in text and "| Scénario | Résultat |\n" in text
    assert "SUCCESS" not in text and "INCONCLUSIVE" not in text


@pytest.mark.parametrize("name", FILES)
def test_unknown_selection_has_no_free_text_or_secret_in_result(name, tmp_path):
    ctx = context("SYNTHETIC_PRIVATE_INPUT", **{"needs.admission.result": "failure"})
    result, _, text = controller(
        name, "result", ctx, tmp_path, {"HOBEN_DEVICE_GUID": "SYNTHETIC_PRIVATE_INPUT"}
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["stages"] == []
    assert "Sélection non attestée : NOT RUN." in text


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize(
    "event_body",
    [
        "SYNTHETIC_PRIVATE_INPUT",
        "{}",
        '{"inputs": {}}',
        '{"inputs": {"scenario": null}}',
        '{"inputs": {"scenario": ["all"]}}',
        '{"inputs": {"scenario": "all"}, "padding": "' + "x" * (256 * 1024) + '"}',
    ],
    ids=[
        "malformed",
        "missing_inputs",
        "missing_scenario",
        "null",
        "array",
        "excessive",
    ],
)
def test_missing_malformed_or_excessive_native_event_metadata_refuses(
    name, event_body, tmp_path
):
    result, outputs, _ = controller(
        name, "admission", context(), tmp_path, event_body=event_body
    )
    assert result.returncode == 1 and outputs["admitted"] == "false"
    assert outputs["collector_ready"] == "false"


def test_both_workflows_use_identical_controller_logic():
    for job in ("admission", "result"):
        assert (
            workflow(FILES[0])["jobs"][job]["steps"][0]["run"]
            == workflow(FILES[1])["jobs"][job]["steps"][0]["run"]
        )
