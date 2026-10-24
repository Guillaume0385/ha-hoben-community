"""Offline structural contracts of the new lane, plus Node gate regressions."""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dedicated_lane_has_exact_scope_and_one_secret_step():
    file = ROOT / ".github/workflows/hoben-session-300.yml"
    workflow = yaml.load(file.read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"push": {"branches": ["experimental"]}}
    assert workflow["permissions"] == {}
    assert not re.search(
        r"\$\{\{\s*secrets\b",
        json.dumps({k: v for k, v in workflow.items() if k != "jobs"}),
    )
    assert workflow["concurrency"]["group"] == "hoben-read-only-observation"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "dry-run",
        "admission",
        "collect",
        "publish",
        "result",
    }
    assert "needs" not in jobs["dry-run"]
    assert jobs["admission"]["needs"] == "dry-run"
    assert jobs["collect"]["needs"] == "admission"
    assert jobs["collect"]["environment"] == "hoben-experimental"
    assert "github.run_attempt == 1" in jobs["dry-run"]["if"]
    secret_steps = []
    for name, job in jobs.items():
        assert job["permissions"].get("id-token") != "write"
        writes = {k for k, v in job["permissions"].items() if v == "write"}
        assert writes == (
            {"contents"}
            if name == "admission"
            else {"statuses"}
            if name == "result"
            else set()
        )
        if name != "collect":
            assert "environment" not in job
            assert not re.search(r"\$\{\{\s*secrets\b", json.dumps(job))
        for step in job["steps"]:
            if "uses" in step:
                assert re.search(r"@[0-9a-f]{40}$", step["uses"])
            if "checkout@" in step.get("uses", ""):
                assert step["with"]["persist-credentials"] == "false"
            if "${{ secrets." in json.dumps(step):
                secret_steps.append((name, step))
    assert len(secret_steps) == 1
    name, step = secret_steps[0]
    assert name == "collect"
    assert step["if"] == "steps.recheck.outputs.approved == 'true'"
    assert step["run"] == "python trusted/scripts/launch_session_suite.py"
    assert set(k for k in step["env"] if k.startswith("HOBEN_")) == {
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
    }
    assert not any(
        "upload-artifact" in s.get("uses", "") for s in jobs["collect"]["steps"]
    )
    assert jobs["publish"]["needs"] == ["admission", "collect"]
    assert "session-suite-report.cjs" in json.dumps(jobs["publish"])
    assert "exports.completed(report, proof," in json.dumps(jobs["result"])
    assert jobs["collect"]["timeout-minutes"] == "22"
    for name in ("dry-run", "admission", "collect"):
        assert "session-suite-gate.cjs" in json.dumps(jobs[name])
        assert "session-300-gate.cjs" not in json.dumps(jobs[name])
    assert "steps.capture.outcome == 'success'" in jobs["collect"]["steps"][-1]["if"]


def test_suite_keeps_preflight_admission_and_recheck_before_secrets():
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-session-300.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    jobs = workflow["jobs"]
    assert " ".join(jobs["dry-run"]["if"].split()) == (
        "github.event_name == 'push' && github.ref == 'refs/heads/experimental' && "
        "github.actor == 'Guillaume0385' && "
        "github.triggering_actor == 'Guillaume0385' && github.run_attempt == 1"
    )
    assert "needs" not in jobs["dry-run"]
    assert jobs["admission"]["needs"] == "dry-run"
    assert "if" not in jobs["admission"]  # Default success(), no failed-gate bypass.
    assert jobs["collect"]["needs"] == "admission"
    assert jobs["collect"]["if"] == "needs.admission.outputs.approved == 'true'"
    for name in ("dry-run", "admission", "collect"):
        assert "continue-on-error" not in json.dumps(jobs[name])
    preflight = jobs["dry-run"]["steps"][-1]["with"]["script"]
    admission = jobs["admission"]["steps"][-1]["with"]["script"]
    assert "await gate.dryRun({github, context})" in preflight
    assert "await gate.verify({github, context})" in admission
    steps = jobs["collect"]["steps"]
    recheck = next(s for s in steps if s.get("id") == "recheck")
    capture = next(s for s in steps if s.get("id") == "capture")
    exports = next(s for s in steps if s.get("id") == "exports")
    assert steps.index(recheck) < steps.index(capture) < steps.index(exports)
    assert (
        "await gate.verify({github, context, recheck: true})"
        in recheck["with"]["script"]
    )
    assert capture["if"] == "steps.recheck.outputs.approved == 'true'"
    assert exports["if"] == (
        "${{ always() && steps.recheck.outputs.approved == 'true' && "
        "steps.capture.outcome == 'success' }}"
    )
    assert jobs["result"]["needs"] == ["admission", "collect", "publish"]
    # Downstream always() cannot bypass the absent admission proof/report.
    assert jobs["result"]["if"] == (
        "${{ always() && needs.admission.outputs.approved == 'true' }}"
    )
    assert jobs["publish"]["if"] == (
        "${{ always() && needs.admission.outputs.approved == 'true' && "
        "needs.collect.outputs.report_b64 != '' }}"
    )


@pytest.mark.parametrize("suite", ["session-300-gate", "session-300-report"])
def test_node_safety_contracts(suite):
    result = subprocess.run(
        ["node", "--test", f"tests/js/{suite}.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]


def test_chat_wiring_002_legacy_lane_cannot_masquerade_as_session_300():
    """H1/H2 admission and its collector are not a V4 lifecycle installation."""
    import ast

    legacy = yaml.load(
        (ROOT / ".github/workflows/hoben-experimental.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    policy = json.loads((ROOT / ".github/config/hoben-experimental.json").read_text())
    capture = next(
        step
        for step in legacy["jobs"]["collect"]["steps"]
        if step.get("id") == "capture"
    )
    assert policy == {
        "schema": 1,
        "scenario": "h1h2",
        "environment": "hoben-experimental",
    }
    assert capture["run"] == "python trusted/scripts/launch_experimental_boundary.py"
    launcher = ast.parse((ROOT / "scripts/launch_experimental_boundary.py").read_text())
    runner = ast.parse((ROOT / "scripts/run_experimental_boundary.py").read_text())
    probe = ast.parse((ROOT / "scripts/probe_opened_client_boundary.py").read_text())
    assert any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "run_experimental_boundary.py" in node.value
        for node in ast.walk(launcher)
    )
    collect = next(
        node
        for node in runner.body
        if isinstance(node, ast.FunctionDef) and node.name == "collect"
    )
    assert any(
        isinstance(node, ast.Constant)
        and node.value == "scripts.probe_opened_client_boundary"
        for node in ast.walk(collect)
    )
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "campaign_with_signals"
        for node in ast.walk(collect)
    )
    assert any(
        isinstance(node, ast.AsyncFunctionDef) and node.name == "campaign_with_signals"
        for node in probe.body
    )
    assert not any(
        isinstance(node, ast.Name) and node.id in {"V4Session", "V4Lifecycle"}
        for node in ast.walk(collect)
    )
    assert "quarantine-installation" not in legacy["jobs"]


def test_suite_admission_still_guards_secrets_and_uses_shared_v4():
    """A runnable import path is not authorization to invoke the live scenario."""
    import ast

    suite = yaml.load(
        (ROOT / ".github/workflows/hoben-session-300.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    jobs = suite["jobs"]
    assert "quarantine-installation" not in jobs
    assert "needs" not in jobs["dry-run"]
    assert jobs["collect"]["needs"] == "admission"
    assert jobs["collect"]["environment"] == "hoben-experimental"
    capture = next(s for s in jobs["collect"]["steps"] if s.get("id") == "capture")
    assert capture["run"] == "python trusted/scripts/launch_session_suite.py"
    assert capture["if"] == "steps.recheck.outputs.approved == 'true'"

    launcher = ast.parse((ROOT / "scripts/launch_session_suite.py").read_text())
    runner = ast.parse((ROOT / "scripts/run_session_suite.py").read_text())
    engine = ast.parse((ROOT / "scripts/session_suite.py").read_text())
    imports = {
        alias.name
        for node in runner.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert {"V4Session", "V4Lifecycle", "observe_suite"} <= imports
    assert any(
        isinstance(node, ast.Name) and node.id == "V4Session"
        for node in ast.walk(runner)
    )
    assert any(
        isinstance(node, ast.Name) and node.id == "V4Lifecycle"
        for node in ast.walk(runner)
    )
    assert any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "run_session_suite.py" in node.value
        for node in ast.walk(launcher)
    )
    observe = next(
        node
        for node in engine.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "observe_suite"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "observe_300"
        for node in ast.walk(observe)
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_observe_reconnect"
        for node in ast.walk(observe)
    )
