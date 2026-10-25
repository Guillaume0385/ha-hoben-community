"""Offline engine doubles for actual supervisor paths; no claims or Hoben I/O."""

import copy
import io
import json
import tarfile

import pytest

from scripts.ha_session_supervisor import (
    Limits,
    OfflineCase,
    SourceBundle,
    Unavailable,
    supervise,
)
from tests.test_ha_live_proof import PROVENANCE, report

IMAGE = "sha256:" + "a" * 64


class Engine:
    def __init__(self):
        self.calls, self.config = [], None
        self.info = {
            "CgroupVersion": "2",
            "MemoryLimit": True,
            "SwapLimit": True,
            "PidsLimit": True,
        }
        self.started, self.stopped, self.deleted = False, False, False
        self.mutate = lambda x: x
        self.reason = "completed"
        self.forever = False

    def request(self, method, path, body=None, **kwargs):
        self.calls.append((method, path))
        if path == "/info":
            return self.info
        if path.startswith("/images/"):
            return {"Id": IMAGE}
        if path.startswith("/containers/create"):
            self.config = body
            return {"Id": "c" * 64}
        if method == "PUT":
            return None
        if path.endswith("/start"):
            self.started = True
            return None
        if path.endswith("/json"):
            running = self.started and self.forever and not self.stopped
            current = {
                "Image": IMAGE,
                "HostConfig": copy.deepcopy(self.config["HostConfig"]),
                "State": {
                    "Running": running,
                    "Pid": 123 if running else 0,
                    "OOMKilled": False,
                },
            }
            return self.mutate(current)
        if "?signal=" in path:
            self.stopped = True
            if "SIGUSR1" in path:
                self.reason = "cancelled"
            return None
        if "/archive?" in path:
            if self.forever and not self.stopped:
                raise Unavailable("http_404")
            r = report(True)
            data = {
                "started": True,
                "reason": self.reason,
                "oom_killed": False,
                "pids_limited": False,
                "evidence": {
                    k: r[k] for k in ("completed", "samples", "window", "cleanup")
                },
            }
            raw = json.dumps(data, separators=(",", ":")).encode()
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as archive:
                item = tarfile.TarInfo("receipt.json")
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
            return buf.getvalue()
        if method == "DELETE":
            self.deleted = True
            return None
        raise AssertionError("unexpected test engine request")


def test_actual_path_verifies_before_start_and_reaps_before_receipt():
    engine = Engine()
    result = supervise(OfflineCase.HEALTHY, IMAGE, PROVENANCE, engine=engine)
    assert (
        result["criteria"]["reconnection"] == "SUCCESS"
        and result["supervisor"]["reaped"]
    )
    assert engine.started and engine.deleted
    assert engine.config["Env"] == [] and engine.config["NetworkDisabled"]
    assert engine.config["HostConfig"]["LogConfig"] == {"Type": "none"}
    calls = [p for m, p in engine.calls]
    assert next(
        i for i, p in enumerate(calls) if p.endswith("/json") and "/containers/" in p
    ) < next(i for i, p in enumerate(calls) if p.endswith("/start"))


@pytest.mark.parametrize(
    "field", ["CgroupVersion", "MemoryLimit", "SwapLimit", "PidsLimit"]
)
def test_absent_capability_denies_before_any_container(field):
    engine = Engine()
    del engine.info[field]
    r = supervise(OfflineCase.HEALTHY, IMAGE, PROVENANCE, engine=engine)
    assert r["outcome"] == "NOT RUN" and engine.config is None and not engine.started


@pytest.mark.parametrize(
    "field,value",
    [
        ("Memory", 1024**3 + 1),
        ("MemorySwap", -1),
        ("PidsLimit", 0),
        ("NetworkMode", "bridge"),
        ("ReadonlyRootfs", False),
        ("Privileged", True),
        ("PidMode", "host"),
        ("CgroupnsMode", "host"),
        ("CapDrop", []),
        ("CapAdd", ["SYS_ADMIN"]),
        ("SecurityOpt", []),
        ("LogConfig", {"Type": "json-file"}),
    ],
)
def test_effective_config_mismatch_never_starts_worker(field, value):
    engine = Engine()

    def mutate(current):
        current["HostConfig"][field] = value
        return current

    engine.mutate = mutate
    r = supervise(OfflineCase.HEALTHY, IMAGE, PROVENANCE, engine=engine)
    assert r["outcome"] == "NOT RUN" and not engine.started and engine.deleted


def test_external_cancel_does_not_reuse_prior_recovery_as_success():
    engine = Engine()
    engine.forever = True
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls > 1

    r = supervise(
        OfflineCase.HEALTHY,
        IMAGE,
        PROVENANCE,
        engine=engine,
        cancelled=cancel,
        sleep=lambda _: None,
    )
    assert engine.stopped and engine.deleted
    assert r["outcome"] == "FAILURE" and r["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert r["supervisor"]["reason"] == "cancelled"


def test_original_deadline_is_not_reset_by_polling_or_cleanup():
    engine = Engine()
    engine.forever = True
    now = 0.0

    def sleep(delay):
        nonlocal now
        now += delay

    r = supervise(
        OfflineCase.RESISTANT,
        IMAGE,
        PROVENANCE,
        engine=engine,
        clock=lambda: now,
        sleep=sleep,
        limits=Limits(useful_ms=1000, process_ms=3000),
    )
    assert r["outcome"] == "FAILURE" and r["supervisor"]["reason"] == "timeout"
    assert r["supervisor"]["elapsed_ms"] <= 3000 and engine.stopped and engine.deleted


def test_missing_backend_returns_not_run_without_host_fallback():
    class Absent:
        def request(self, *args, **kwargs):
            raise Unavailable()

    r = supervise(OfflineCase.HEALTHY, IMAGE, PROVENANCE, engine=Absent())
    assert r["outcome"] == "NOT RUN" and not r["supervisor"]["started"]


def test_cancellation_before_start_never_executes_worker():
    engine = Engine()
    r = supervise(
        OfflineCase.HEALTHY, IMAGE, PROVENANCE, engine=engine, cancelled=lambda: True
    )
    assert not engine.started and engine.deleted
    assert r["criteria"]["collection"] == "NOT RUN" and r["outcome"] == "FAILURE"


def test_source_snapshot_contains_public_read_only_runtime_only():
    bundle = SourceBundle()
    directory = bundle.folder
    try:
        assert not (directory / ".git").exists()
        assert not (directory / ".github").exists()
        for path in directory.rglob("*"):
            assert not path.is_symlink()
            if path.is_file():
                assert path.stat().st_mode & 0o777 == 0o444
        assert (directory / "scripts/ha_session_guard.py").is_file()
    finally:
        bundle.close()
    assert not directory.exists()


def test_source_snapshot_rejects_a_directory_symlink(monkeypatch, tmp_path):
    from scripts import ha_session_supervisor as supervisor

    private = tmp_path / "outside"
    private.mkdir()
    (private / "payload.py").write_text("PRIVATE_PAYLOAD")
    root = tmp_path / "repo"
    (root / "custom_components").mkdir(parents=True)
    (root / "custom_components/hoben").symlink_to(private, target_is_directory=True)
    monkeypatch.setattr(supervisor, "ROOT", root)
    with pytest.raises(Unavailable):
        SourceBundle()


def test_guardian_missing_metrics_refuses_before_worker(monkeypatch):
    from unittest.mock import Mock

    from scripts import ha_session_guard as guard

    monkeypatch.setattr(guard.os, "getpid", lambda: 1)
    monkeypatch.setattr(guard.os, "getuid", lambda: 0)

    def absent():
        raise OSError("PRIVATE_PAYLOAD")

    monkeypatch.setattr(guard, "metrics", absent)
    spawn = Mock()
    monkeypatch.setattr(guard.subprocess, "Popen", spawn)
    with pytest.raises(OSError):
        guard.run(
            "healthy",
            {
                "memory_bytes": 1024**3,
                "pids": 128,
                "useful_ms": 300000,
                "process_ms": 360000,
            },
            10**18,
        )
    spawn.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("memory_bytes", 1024**3 + 1),
        ("pids", 129),
        ("useful_ms", 300001),
        ("process_ms", 360001),
        ("process_ms", True),
    ],
)
def test_limits_cannot_be_enlarged(field, value):
    with pytest.raises(ValueError):
        Limits(**{field: value})


def test_guardian_allows_final_proof_and_cleanup_after_300_not_after_360():
    from scripts.ha_session_guard import worker_deadline

    limits = {"useful_ms": 300000, "process_ms": 360000}
    end = worker_deadline(limits, 360_000_000_000, 0)
    assert 300_000_000_000 < end == 340_000_000_000
    # A delayed bootstrap cannot move the original final margin.
    assert worker_deadline(limits, 360_000_000_000, 30_000_000_000) == end
    assert end + 10_000_000_000 < 360_000_000_000  # terminate + reaping margin


@pytest.mark.parametrize("at", [300, 359.999, 360])
def test_cancellation_and_cleanup_never_reset_original_360_deadline(at):
    engine = Engine()
    engine.forever = True
    now = 0.0

    def sleep(delay):
        nonlocal now
        now = at  # clock jumps while the controller is waiting, never sleeping live

    r = supervise(
        OfflineCase.RESISTANT,
        IMAGE,
        PROVENANCE,
        engine=engine,
        clock=lambda: now,
        sleep=sleep,
        cancelled=lambda: now >= at,
    )
    assert r["supervisor"]["elapsed_ms"] <= 360000
    assert r["outcome"] == "FAILURE"
    assert r["criteria"]["continuous_300s"] != "SUCCESS"
