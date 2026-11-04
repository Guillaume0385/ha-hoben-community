"""032 profile through actual controllers, parent, guardian and confinement."""

import base64
import io
import json
import subprocess
import sys
import tarfile
import time
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from scripts.campaign_runtime_contract import ha_limits
from scripts.ha_session_supervisor import SourceBundle, supervise_campaign
from tests.test_campaign_minimal_admission import context, controller
from tests.test_campaign_publication import node
from tests.test_campaign_runtime import ROOT
from tests.test_campaign_supervision import CampaignEngine
from tests.test_dual_session_contract import DUAL, proof, report
from tests.test_ha_manual_live import IDENTITY
from tests.test_ha_session_supervisor import IMAGE


@pytest.mark.parametrize("fault", [None, "private", "mode", "memory", "pids", "cancel"])
def test_dedicated_profile_retains_confinement_private_channel_and_reaping(
    monkeypatch, fault
):
    monkeypatch.setattr("tests.test_campaign_supervision.ha_detail", lambda _: proof())
    clock = [0]
    engine = CampaignEngine(DUAL, clock)
    deadlines = []
    request = engine.request

    def inspect(method, path, body=None, **kwargs):
        if method == "PUT" and "/archive?" in path:
            with tarfile.open(fileobj=io.BytesIO(body)) as archive:
                deadlines.append(int(archive.extractfile("deadline").read()))
        return request(method, path, body, **kwargs)

    engine.request = inspect
    engine.corrupt = fault == "private"
    if fault == "mode":
        engine.mode = "live"
    if fault in {"memory", "pids"}:

        def mutate(config):
            config["HostConfig"]["Memory" if fault == "memory" else "PidsLimit"] = 0
            return config

        engine.mutate = mutate
    d = supervise_campaign(
        IMAGE,
        DUAL,
        IDENTITY,
        engine=engine,
        clock=lambda: clock[0],
        cancelled=lambda: fault == "cancel",
        _absolute_deadline=850,
    )
    assert engine.deleted and d["supervisor"]["reaped"]
    if fault is None:
        assert d["supervisor"]["reason"] == "completed"
        assert d["evidence"]["completed"]
        assert deadlines == [850000000000]
        assert json.loads(engine.config["Cmd"][1]) == asdict(ha_limits(DUAL))
    else:
        assert d["supervisor"]["reason"] != "completed"
    if fault in {"memory", "pids", "cancel"}:
        assert not engine.started and not engine.fed
    assert "PRIVATE_PAYLOAD" not in json.dumps(d)


def test_dual_sources_are_in_private_read_only_bundle():
    bundle = SourceBundle(live=True, campaign=True)
    try:
        for name in (
            "ha_dual_observer.py",
            "ha_dual_instrumentation.py",
            "ha_dual_evidence.py",
        ):
            assert (bundle.folder / "scripts" / name).is_file()
    finally:
        bundle.close()


def test_guardian_accepts_only_exact_named_profile_and_never_resets_deadline(
    monkeypatch,
):
    from scripts import ha_session_guard as guard

    monkeypatch.setattr(guard.os, "getpid", lambda: 1)
    monkeypatch.setattr(guard.os, "getuid", lambda: 0)
    monkeypatch.setattr(guard.time, "monotonic_ns", lambda: 100000000000)
    monkeypatch.setattr(guard, "stopping", True)
    monkeypatch.setattr(
        guard, "metrics", lambda: dict(memory_bytes=1024**3, pids=128, swap=0)
    )
    limits = asdict(ha_limits(DUAL))
    r = guard.run("campaign/" + DUAL, limits, 900000000000)
    assert not r["started"] and r["reason"] == "cancelled"
    for scenario, deadline in (
        ("cleanup", 900000000000),
        (DUAL, 100000000000),
        (DUAL, 1000000000001),
    ):
        with pytest.raises(ValueError):
            guard.run("campaign/" + scenario, limits, deadline)


@pytest.mark.parametrize("actor", ["Guillaume0385", "unauthorized"])
def test_actual_native_admission_and_refusal_include_only_explicit_dual_selection(
    monkeypatch, tmp_path, actor
):
    w = yaml.safe_load((ROOT / ".github/workflows/hoben-ha-manual.yml").read_text())
    monkeypatch.setattr("tests.test_campaign_minimal_admission.workflow", lambda _: w)
    ctx = context(DUAL, **{"github.actor": actor})
    result, outputs, _ = controller("hoben-ha-manual.yml", "admission", ctx, tmp_path)
    assert (result.returncode == 0) == (actor == "Guillaume0385")
    assert outputs["collector_ready"] == str(actor == "Guillaume0385").lower()


@pytest.mark.parametrize("collect", ["success", "failure", "cancelled"])
def test_publication_never_confuses_stage_success_with_actions_success(
    tmp_path, collect
):
    r = report(proof())
    encoded = base64.b64encode(json.dumps(r, separators=(",", ":")).encode()).decode()
    result = node("publish", tmp_path, "ha", DUAL, encoded=encoded, collect=collect)
    assert (result.returncode == 0) == (collect == "success")
    text = (tmp_path / "summary").read_text()
    for name in ("before", "overlap", "after"):
        assert name + " / a" in text and name + " / b" in text
    assert "PRIVATE_PAYLOAD" not in text


@pytest.mark.parametrize("timer", [None, "invalid", "0", "99999999999999999999"])
def test_missing_invalid_expired_or_future_global_start_refuses_before_identity(
    monkeypatch, tmp_path, timer
):
    from scripts import run_campaign as parent

    monkeypatch.setattr(parent.sys, "argv", ["run_campaign.py", "ha"])
    monkeypatch.setattr(
        parent,
        "context",
        lambda *_: (
            DUAL,
            dict(ref="refs/heads/experimental", sha="a" * 40, run_id=1, run_attempt=1),
        ),
    )
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    (tmp_path / "hoben-ha-runtime.id").write_text(IMAGE)
    if timer is None:
        monkeypatch.delenv("HOBEN_DUAL_STARTED_NS", raising=False)
    else:
        monkeypatch.setenv("HOBEN_DUAL_STARTED_NS", timer)

    def forbidden(*args, **kwargs):
        raise AssertionError("identity must not be requested")

    monkeypatch.setattr(parent, "identity", forbidden)
    assert parent.main() == 1
    r = json.loads((tmp_path / "hoben-campaign-public/report.json").read_text())
    assert r["stages"][0]["status"] == "NOT RUN"
    assert r["stages"][0]["reason"] == "identity_refused"


@pytest.mark.parametrize("mode", ["private", "big"])
def test_dual_parent_refuses_excessive_or_private_output_and_reaps_worker(
    monkeypatch, mode
):
    from scripts.run_campaign import execute

    original = subprocess.Popen
    children, folders = [], []

    def spawn(argv, **kwargs):
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        folders.append(Path(kwargs["env"]["CAMPAIGN_PRIVATE_DIR"]))
        child = original(
            [
                sys.executable,
                "-I",
                str(ROOT / "tests/fixtures/campaign_parent_worker.py"),
                mode,
            ],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    value = execute(
        "ha", DUAL, b'{"device_guid":"synthetic"}', time.monotonic() + 5, image=IMAGE
    )
    assert value["started"] and value["status"] == "FAILURE"
    assert not value["metrics"]["cleanup"]
    assert children and all(p.poll() is not None for p in children)
    assert folders and all(not p.exists() for p in folders)
    assert "PRIVATE_PAYLOAD" not in json.dumps(value)
