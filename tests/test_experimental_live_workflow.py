"""Offline security and behavioral parity for Issue #54 experimental HA live lane."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from custom_components.hoben.profiles import StoveProfile
from scripts import launch_live_ha_parity as launcher
from scripts import run_live_ha_parity as live

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hoben-live-experimental.yml"


def test_exact_live_workflow_permissions_and_secret_lifecycle():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow.get("on", workflow.get(True)) == {
        "push": {"branches": ["experimental"]}
    }
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "hoben-read-only-observation",
        "cancel-in-progress": False,
        "queue": "max",
    }
    jobs = workflow["jobs"]
    assert set(jobs) == {"dry-run", "admission", "collect", "result"}
    assert jobs["admission"]["needs"] == "dry-run"
    assert jobs["collect"]["needs"] == "admission"
    assert jobs["collect"]["environment"] == "hoben-live"
    assert jobs["collect"]["if"] == "needs.admission.outputs.approved == 'true'"
    assert "environment" not in jobs["admission"]
    assert "environment" not in jobs["dry-run"]
    for name, job in jobs.items():
        writes = {key for key, value in job["permissions"].items() if value == "write"}
        assert writes == (
            {"contents"}
            if name == "admission"
            else {"statuses"}
            if name == "result"
            else set()
        )
        assert job["permissions"].get("id-token") != "write"
        assert all(
            step["with"]["persist-credentials"] is False
            for step in job["steps"]
            if "checkout@" in step.get("uses", "")
        )

    secret_steps = [
        (name, step)
        for name, job in jobs.items()
        for step in job["steps"]
        if "${{ secrets." in json.dumps(step)
    ]
    assert len(secret_steps) == 1
    name, secret = secret_steps[0]
    assert name == "collect"
    assert secret["id"] == "capture"
    assert secret["if"] == "steps.recheck.outputs.approved == 'true'"
    assert set(secret["env"]) == {
        "LIVE_APPROVED_SHA",
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
    }
    assert secret["run"] == "python trusted/scripts/launch_live_ha_parity.py"

    uploads = [
        step
        for step in jobs["collect"]["steps"]
        if "upload-artifact@" in step.get("uses", "")
    ]
    assert len(uploads) == 1
    assert uploads[0]["with"]["retention-days"] <= 7
    assert uploads[0]["with"]["path"] == (
        "${{ runner.temp }}/hoben-live-public/report.json"
    )
    script = next(s for s in jobs["admission"]["steps"] if s.get("id") == "gate")
    assert "gate.refusalCategory(error)" in script["with"]["script"]
    assert (
        "core.setOutput('approved', 'true')"
        not in (script["with"]["script"].split("catch (error)", 1)[1])
    )
    assert "workflow_dispatch" not in workflow.get("on", workflow.get(True))


def test_live_uses_real_home_assistant_client_without_lab_instrumentation():
    text = (ROOT / "scripts/run_live_ha_parity.py").read_text()
    coordinator = (ROOT / "custom_components/hoben/coordinator.py").read_text()
    assert "from custom_components.hoben.client import HobenClient" in text
    assert "from custom_components.hoben.v4_state import decode_v4_snapshot" in text
    assert "await client.async_refresh()" in text
    assert "decoder(snapshot)" in text
    assert "await client.async_close()" in text
    assert "await self.client.async_refresh()" in coordinator
    assert "decode_v4_snapshot(snapshot)" in coordinator
    assert "HobenClient(" in (ROOT / "custom_components/hoben/__init__.py").read_text()
    assert "max_attempts=1" in text
    assert "asyncio.timeout(BUDGET_SECONDS)" in text
    assert "async_associate" not in text
    assert "run_experimental_boundary" not in text
    assert "boundary_capture" not in text
    assert (
        "write_"
        not in text.split("async def observe", 1)[1].split("def write_report", 1)[0]
    )
    assert live.BUDGET_SECONDS == 150


class FakeClient:
    def __init__(self, *, fail_at=0):
        self.fail_at = fail_at
        self.refreshes = 0
        self.closed = False
        self.has_assigned_device_guid = False
        self.device_guid_for_persistence = "0" * 32

    async def async_refresh(self):
        self.refreshes += 1
        if self.refreshes == self.fail_at:
            raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION")
        self.has_assigned_device_guid = True
        self.device_guid_for_persistence = "a" * 32
        return SimpleNamespace(profile=StoveProfile.V4, registers=(0,) * 20)

    async def async_close(self):
        self.closed = True


@pytest.mark.parametrize("failure", [0, 1, 2])
def test_two_actual_client_refresh_calls_fake_transport_only(failure):
    clients = []
    decoded = []

    def factory(**kwargs):
        assert kwargs["max_attempts"] == 1
        assert kwargs["retry_delay"] == 0
        assert kwargs["handshake_timeout"] == kwargs["read_timeout"] == 30
        client = FakeClient(fail_at=failure)
        clients.append(client)
        return client

    result = asyncio.run(
        live.observe(
            "SYNTHETIC_USER_GUID",
            None,
            client_factory=factory,
            decoder=lambda snapshot: decoded.append(snapshot),
        )
    )
    assert len(clients) == 1 and clients[0].closed
    assert clients[0].refreshes == (failure if failure else 2)
    assert len(decoded) == (failure - 1 if failure else 2)
    assert result["closed"] is True
    assert result["session_mode"] == "one-shot"
    assert result["ping_pong"] == "unsupported"
    assert result["data_updated"] == "unsupported"
    assert result["persistent_session"] == "unsupported"
    assert result["reconnect"] == "not_tested"
    assert "SYNTHETIC_PRIVATE" not in json.dumps(result)
    assert result["status"] == ("success" if failure == 0 else "failure")
    if failure == 0:
        assert result["refreshes_completed"] == 2
        assert result["decoded_refreshes"] == 2
        assert result["device_identity_reused"] is True
    else:
        assert result["error"] == "client_failure"


def test_invalid_launch_context_refuses_before_client_and_without_secret_echo(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("HOBEN_USER_GUID", "SYNTHETIC_PRIVATE_GUID")
    monkeypatch.setenv("GITHUB_ACTOR", "outsider")
    monkeypatch.setattr(
        live, "observe", lambda *a, **k: pytest.fail("network must not start")
    )
    assert live.main() == 1
    report = json.loads((tmp_path / "hoben-live-public/report.json").read_text())
    assert report["error"] == "invalid_context"
    assert "SYNTHETIC_PRIVATE_GUID" not in json.dumps(report)
    assert live.write_report(report, str(tmp_path)) is False


def test_child_process_drops_github_tokens_and_action_command_files(monkeypatch):
    for key in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "GITHUB_OUTPUT",
        "GITHUB_ENV",
        "GITHUB_STEP_SUMMARY",
        "PYTHONPATH",
        "SYNTHETIC_PRIVATE_KEY",
    ):
        monkeypatch.setenv(key, "SYNTHETIC_PRIVATE_VALUE")
    monkeypatch.setenv("HOBEN_USER_GUID", "SYNTHETIC_PRIVATE_GUID")
    child = launcher.child_environment(dict(os.environ))
    assert set(child) <= set(launcher.ALLOWED) | {"PATH"}
    assert child["HOBEN_USER_GUID"] == "SYNTHETIC_PRIVATE_GUID"
    assert not any(key in child for key in ("GITHUB_TOKEN", "PYTHONPATH", "GH_TOKEN"))
    assert child["PATH"] == "/usr/bin:/bin"


@pytest.mark.parametrize(
    "suite", ["experimental-live-gate", "experimental-live-report"]
)
def test_node_live_offline_security_regressions(suite):
    assert shutil.which("node"), "Node required to test the Actions security gates"
    result = subprocess.run(
        ["node", "--test", f"tests/js/{suite}.test.cjs"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
