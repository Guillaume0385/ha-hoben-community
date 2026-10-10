"""Fail-closed regression contract while #54 native rerun gates are unimplemented.

This deliberately DOES NOT simulate manager approval or enable live access.
It prevents an accidental secret-bearing change from being reported as ready.
"""

import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
SCRIPTS = ROOT / ".github/scripts"


def test_rejected_temporary_branch_trigger_is_absent():
    assert not (WORKFLOWS / "experimental-campaign-trigger-proof.yml").exists()
    assert not (SCRIPTS / "experimental-campaign-trigger-proof.cjs").exists()


def test_both_secret_bearing_workflows_still_fail_closed_on_rerun():
    for filename, expected_environment in (
        ("hoben-experimental.yml", "hoben-experimental"),
        ("hoben-live-experimental.yml", "hoben-live"),
    ):
        data = yaml.safe_load((WORKFLOWS / filename).read_text())
        assert data.get("on", data.get(True)) == {
            "push": {"branches": ["experimental"]}
        }
        assert data["jobs"]["collect"]["environment"] == expected_environment
        assert "github.run_attempt == 1" in data["jobs"]["dry-run"]["if"]
        assert data["concurrency"]["group"] == "hoben-read-only-observation"
        assert data["concurrency"]["cancel-in-progress"] is False


def test_both_original_gates_cannot_reuse_v1_decision_for_attempt_two():
    push = (SCRIPTS / "experimental-push-preflight.cjs").read_text()
    assert 'env.GITHUB_RUN_ATTEMPT !== "1"' in push
    for filename in ("experimental-lab-gate.cjs", "experimental-live-gate.cjs"):
        gate = (SCRIPTS / filename).read_text()
        assert "run.run_attempt === 1" in gate
        assert "tracking_issue_id" not in gate
        assert "issue_number: 54" not in gate
        assert "campaign_id" not in gate


def test_no_unreviewed_code_or_script_path_is_added_to_ha_runtime():
    root = ROOT / "custom_components/hoben"
    for component in root.rglob("*.py"):
        text = component.read_text()
        assert "experimental-campaign-trigger-proof" not in text
        assert "experimental-attempt.cjs" not in text

def test_pure_native_rerun_gate_proves_attempt_and_decision_refusals_offline():
    assert shutil.which("node"), "Node.js required for independent gate tests"
    result = subprocess.run(
        ["node", "--test", "tests/js/experimental-native-rerun.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]


def test_native_rerun_helper_does_not_unlock_current_hoben_workflows():
    helper = (SCRIPTS / "experimental-native-rerun.cjs").read_text()
    assert "authorizeAttempt" in helper
    assert "authorizeDecision" in helper
    assert "claimName" in helper
    for filename in ("experimental-lab-gate.cjs", "experimental-live-gate.cjs"):
        text = (SCRIPTS / filename).read_text()
        assert "experimental-native-rerun" not in text
        assert "run.run_attempt === 1" in text
