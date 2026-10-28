"""Actual parent pipes/process cleanup and injected C2a engine, entirely offline."""

import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from scripts.campaign_runtime_contract import HA_CHOICES, SECONDS
from scripts.ha_session_supervisor import SourceBundle, supervise_campaign
from scripts.run_campaign import execute
from tests.test_campaign_runtime import ha_detail
from tests.test_ha_manual_live import IDENTITY
from tests.test_ha_session_supervisor import IMAGE, Engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "mode,status,started",
    [
        ("valid", "SUCCESS", True),
        ("before_ack", "NOT RUN", False),
        ("after_ack", "FAILURE", True),
        ("private", "FAILURE", True),
        ("big", "FAILURE", True),
    ],
)
def test_actual_parent_ack_bounds_projection_and_reaping(
    mode, status, started, monkeypatch
):
    processes = []
    private_directories = []
    real = subprocess.Popen

    def spawn(argv, **kwargs):
        private_directories.append(Path(kwargs["env"]["CAMPAIGN_PRIVATE_DIR"]))
        assert argv[2].endswith("scripts/campaign_worker.py")
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        process = real(
            [
                sys.executable,
                "-I",
                str(ROOT / "tests/fixtures/campaign_parent_worker.py"),
                mode,
            ],
            **kwargs,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    value = execute(
        "protocol", "tls-only", b'{"device_guid":"synthetic"}', time.monotonic() + 5
    )
    assert value["status"] == status and value["started"] is started
    assert processes and processes[0].poll() is not None
    assert all(not p.exists() for p in private_directories)
    assert "PRIVATE_PAYLOAD" not in json.dumps(value)


def test_cancel_before_ack_does_not_spawn(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no worker before admission")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    value = execute(
        "protocol", "tls-only", b"{}", time.monotonic() + 5, cancelled=lambda: True
    )
    assert not value["started"] and value["status"] == "NOT RUN"


def test_timeout_after_ack_kills_even_sigterm_resistant_group(monkeypatch):
    real_spawn, real_write = subprocess.Popen, os.write
    processes, acknowledged = [], [False]

    def spawn(argv, **kwargs):
        p = real_spawn(
            [
                sys.executable,
                "-I",
                str(ROOT / "tests/fixtures/campaign_parent_worker.py"),
                "resistant",
            ],
            **kwargs,
        )
        processes.append(p)
        return p

    def write(fd, data):
        result = real_write(fd, data)
        if data == b"A":
            acknowledged[0] = True
        return result

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(os, "write", write)
    value = execute(
        "protocol",
        "tls-only",
        b'{"device_guid":"synthetic"}',
        5,
        clock=lambda: 4.0 if acknowledged[0] else 0.0,
    )
    assert (
        value["started"]
        and value["status"] == "FAILURE"
        and value["reason"] == "timeout"
    )
    assert processes[0].poll() is not None
    assert processes[0].returncode == -signal.SIGKILL


class CampaignEngine(Engine):
    def __init__(self, scenario, clock):
        super().__init__()
        self.scenario, self.clock = scenario, clock
        self.fed, self.mode, self.corrupt = [], "campaign/" + scenario, False

    def feed(self, name, payload, **kwargs):
        self.fed.append(payload)

    def request(self, method, path, body=None, **kwargs):
        detail = ha_detail(self.scenario)
        if path.endswith("/start"):
            self.clock[0] = detail["supervisor"]["elapsed_ms"] / 1000
        if "/archive?" in path and method == "GET":
            data = {
                "started": True,
                "reason": "completed",
                "oom_killed": False,
                "pids_limited": False,
                "mode": self.mode,
                "evidence": detail["evidence"],
            }
            if self.corrupt:
                data["evidence"]["private"] = "PRIVATE_PAYLOAD"
            raw = json.dumps(data, separators=(",", ":")).encode()
            out = io.BytesIO()
            with tarfile.open(fileobj=out, mode="w") as archive:
                item = tarfile.TarInfo("receipt.json")
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
            return out.getvalue()
        result = super().request(method, path, body, **kwargs)
        if path.endswith("/json") and "/containers/" in path:
            result["Config"] = self.config
        return result


@pytest.mark.parametrize("scenario", HA_CHOICES[:-1])
def test_shared_supervisor_applies_exact_new_limits_and_private_identity(scenario):
    clock = [0]
    engine = CampaignEngine(scenario, clock)
    d = supervise_campaign(
        IMAGE, scenario, IDENTITY, engine=engine, clock=lambda: clock[0]
    )
    assert d["supervisor"]["reason"] == "completed" and d["supervisor"]["reaped"]
    assert engine.deleted and engine.fed == [IDENTITY]
    config = engine.config
    assert config["Cmd"][0] == "campaign/" + scenario and config["Env"] == []
    limits = json.loads(config["Cmd"][1])
    assert limits["process_ms"] == SECONDS["ha"][scenario] * 1000
    assert (
        config["HostConfig"]["Memory"] == 1024**3
        and config["HostConfig"]["PidsLimit"] == 128
    )
    assert config["HostConfig"]["LogConfig"] == {"Type": "none"}
    assert "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD" not in json.dumps(config) + json.dumps(d)


@pytest.mark.parametrize("fault", ["mode", "private", "memory", "pids", "cancel"])
def test_shared_supervisor_refuses_wrong_receipt_or_confinement_before_success(fault):
    clock = [0]
    engine = CampaignEngine("cleanup", clock)
    if fault == "mode":
        engine.mode = "live"
    elif fault == "private":
        engine.corrupt = True
    elif fault in {"memory", "pids"}:

        def mutate(value):
            value["HostConfig"]["Memory" if fault == "memory" else "PidsLimit"] = 0
            return value

        engine.mutate = mutate
    d = supervise_campaign(
        IMAGE,
        "cleanup",
        IDENTITY,
        engine=engine,
        clock=lambda: clock[0],
        cancelled=lambda: fault == "cancel",
    )
    assert d["supervisor"]["reason"] != "completed" and engine.deleted
    assert not d["evidence"]["completed"] and "PRIVATE_PAYLOAD" not in json.dumps(d)
    if fault in {"memory", "pids", "cancel"}:
        assert not engine.started and not engine.fed


def test_campaign_bundle_reuses_true_worker_and_contains_no_fixture_or_git():
    bundle = SourceBundle(live=True, campaign=True)
    try:
        for name in (
            "ha_session_live_worker.py",
            "ha_campaign_worker.py",
            "ha_campaign_observer.py",
        ):
            assert (bundle.folder / "scripts" / name).is_file()
        assert (
            not (bundle.folder / "tests").exists()
            and not (bundle.folder / ".git").exists()
        )
    finally:
        bundle.close()
