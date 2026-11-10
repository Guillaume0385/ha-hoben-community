"""D7 wiring is reviewed separately from the unavailable live continuation proof."""

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.info_delivery_worker_fixture_186 import run_worker_case
from tests.tls_read_candidate_186 import RESPONSE

ROOT = Path(__file__).resolve().parents[1]


def workflow():
    return yaml.load(
        (ROOT / ".github/workflows/hoben-manual.yml").read_text(),
        Loader=yaml.BaseLoader,
    )


def test_existing_choice_routes_only_to_info_with_secrets_after_admission():
    config = workflow()
    assert config["on"]["workflow_dispatch"]["inputs"]["scenario"]["options"] == [
        "h1h2",
        "session-300",
        "session-reconnect",
        "all",
        "hoben-live",
    ]
    jobs = config["jobs"]
    assert not {"collect-ha", "publish-ha", "result-ha"}.intersection(jobs)
    assert jobs["collect-info"]["environment"] == "hoben-experimental"
    assert int(jobs["collect-info"]["timeout-minutes"]) > 60
    assert jobs["collect"]["timeout-minutes"] == "50"
    assert "selection == 'hoben-live'" in jobs["collect-info"]["if"]
    assert "selection != 'hoben-live'" in jobs["collect"]["if"]
    assert config["concurrency"]["group"] == "hoben-read-only-observation"
    assert config["concurrency"]["cancel-in-progress"] == "false"
    steps = jobs["collect-info"]["steps"]
    capture = next(i for i, step in enumerate(steps) if step.get("id") == "capture")
    assert all("secrets." not in json.dumps(step) for step in steps[:capture])
    assert steps[capture]["if"] == "steps.recheck.outputs.approved == 'true'"
    assert steps[capture]["run"] == "python -I trusted/scripts/launch_info_manual.py"
    assert all("secrets." not in json.dumps(step) for step in steps[capture + 1 :])
    for key in ("publish-info", "result-info"):
        assert "secrets." not in json.dumps(jobs[key])
        assert "environment" not in jobs[key]
    assert "continue-on-error" not in json.dumps(jobs["collect-info"])


def test_d7_route_manifest_binds_sources_and_opaque_candidate_policy():
    manifest = json.loads((ROOT / ".github/info-manual-route.json").read_text())
    assert manifest["limits"] == {
        "observation_ms": 3540000,
        "cleanup_ms": 60000,
        "total_ms": 3600000,
    }
    assert manifest["schema"] == 2
    assert manifest["policy"] == {
        "observation": "passive_candidate_stop",
        "continuation": "never_force",
        "info_framing": "INCONCLUSIVE",
        "boundary_proven": False,
    }
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest


def test_historical_jobs_and_dedicated_ha_workflow_are_identical_to_d7_base():
    # Generated from the exact authorized base 4fdcf03, independent of the
    # manifest. These protected parts must not change to enable Info.
    jobs = workflow()["jobs"]
    historical = {
        name: jobs[name] for name in ("preflight", "collect", "publish", "result")
    }
    # Only the Info source-contract output is added to shared preflight.
    del historical["preflight"]["outputs"]["contract"]
    script = historical["preflight"]["steps"][-1]["with"]["script"]
    # Normalize only the reviewed diagnostic delta, without weakening
    # the historical digest of the other protected steps and jobs.
    new_catch = (
        "}catch(error){\n"
        "  // Only a fixed public category, never an exception or API response.\n"
        "  const category=require('./.github/scripts/manual-hoben-gate.cjs')"
        ".publicFailureCategory(error);\n"
        "  core.setFailed('NOT RUN: manual admission refused; phase='"
        "+category+'.');\n"
        "}"
    )
    old_catch = (
        "}catch(_){core.setFailed('NOT RUN: manual provenance, review, CI, "
        "environment or claim refused.');}"
    )
    assert script.count(new_catch) == 1
    script = script.replace("  core.setOutput('contract',d.contract_digest||'');\n", "")
    historical["preflight"]["steps"][-1]["with"]["script"] = script.replace(
        new_catch, old_catch
    )
    assert hashlib.sha256(
        json.dumps(historical, sort_keys=True).encode()
    ).hexdigest() == (
        "b385c52d37eabba97105ff9fa061f541a786600704abc9169ae3f19ae0c5e656"
    )
    assert (
        hashlib.sha256(
            (ROOT / ".github/workflows/hoben-ha-manual.yml").read_bytes()
        ).hexdigest()
        == "f1f27e60304f2f3b44c08e9b88e13064e5e0f80de40f3396d57a84c2f7b02eff"
    )


def test_live_report_authentication_with_synthetic_github():
    result = subprocess.run(
        ["node", "tests/js/info-manual-live-report.test.cjs"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_gate_report_and_tampering_with_synthetic_github():
    result = subprocess.run(
        ["node", "tests/js/info-manual-route.test.cjs"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("suffix", [b"", b"\x00", b"\x07", b"\xff", b"\x0a", RESPONSE])
def test_actual_read_delivery_cannot_claim_isolated_info_from_its_shape(
    monkeypatch, suffix
):
    # The same byte prefix is compatible with an Info fragment or a coalesced
    # following message. No fixture declaration is supplied by the TLS stream.
    result = asyncio.run(
        run_worker_case(
            monkeypatch,
            adapter=True,
            delivery_layout="unknown",
            replies=(),
            plan=((1000, b"\x0c" + suffix), (1100, b"\x0a"), (1200, RESPONSE)),
        )
    )
    assert result.adapter_report["result"] == "FAILURE"
    assert result.adapter_report["first_error"] == "ambiguous_delivery"
    assert result.wire.requests == result.session.verified_read_sequence == 0
    assert result.factory.calls == result.wire.connect_count == 1
    assert result.wire.closed and result.session.cleanup_succeeded
    assert result.session._rx_task.done()


def test_offline_success_is_not_a_live_attestation(monkeypatch):
    result = asyncio.run(
        run_worker_case(
            monkeypatch,
            adapter=True,
            delivery_layout="isolated_fixture",
            replies=(),
            plan=((1000, b"\x0c"), (1100, b"\x0a"), (1200, RESPONSE)),
        )
    )
    assert result.adapter_report["result"] == "SUCCESS"
    assert result.adapter_report["tls_provenance"] == "not_proven"
    assert result.adapter_report["process_reap"] == "not_proven"
    assert result.adapter_report["mode"] == "offline"
    assert result.adapter_report["boundary_proven"] is False



def test_collect_info_is_only_passed_user_secret():
    """The historic collect campaign stays byte-for-byte under its own contract."""
    jobs = workflow()["jobs"]
    capture = next(
        step for step in jobs["collect-info"]["steps"] if step.get("id") == "capture"
    )
    secret_env = {k: v for k, v in capture["env"].items() if "secrets." in str(v)}
    assert secret_env == {"HOBEN_USER_GUID": "${{ secrets.HOBEN_USER_GUID }}"}
    assert "HOBEN_DEVICE_GUID" not in json.dumps(jobs["collect-info"])
