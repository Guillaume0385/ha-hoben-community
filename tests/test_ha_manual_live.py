"""Admission/report/private-channel doubles only. Never start a live worker."""

import copy
import io
import json
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from scripts.ha_manual_live_report import (
    EVIDENCE_KEYS,
    build_live_report,
    not_run,
    validate_live_report,
)
from scripts.ha_session_supervisor import SourceBundle, supervise_live
from tests.test_ha_live_proof import report
from tests.test_ha_session_supervisor import IMAGE, Engine

ROOT = Path(__file__).resolve().parents[1]
PROOF = {
    "merge_sha": "a" * 40,
    "candidate_sha": "b" * 40,
    "pr_number": 128,
    "ci_run_id": 10,
    "run_id": 20,
    "run_attempt": 1,
    "environment_id": 30,
    "environment_digest": "c" * 64,
    "claim_sha": "d" * 40,
}
IDENTITY = (
    b'{"user_guid":"11111111111111111111111111111111",'
    b'"device_guid":"DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"}\n'
)


def live_report():
    r = report()
    r["supervisor"]["elapsed_ms"] = 309000
    r["window"]["clock"] = "monotonic"
    return build_live_report(PROOF, r["supervisor"], {k: r[k] for k in EVIDENCE_KEYS})


def node_accepts(r, expected=PROOF):
    result = subprocess.run(
        [
            "node",
            "-e",
            "const a=require('./.github/scripts/ha-manual-live-report.cjs');"
            "let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{"
            "try{const [r,p]=JSON.parse(s);a.validate(r,p);a.decode(a.encode(r,p),p);"
            "process.stdout.write('ok')}catch(_){process.exitCode=1}});",
        ],
        input=json.dumps([r, expected]),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.stderr == ""
    return result.returncode == 0


def test_live_contract_is_distinct_bound_and_not_a_relabelled_synthetic_proof():
    r = live_report()
    assert r["schema"] == 3 and r["execution"] == "live"
    assert r["outcome"] == "SUCCESS" and r["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert validate_live_report(r, PROOF) == r and node_accepts(r)
    for old in (report(), {**r, "schema": 2}):
        with pytest.raises(ValueError):
            validate_live_report(old, PROOF)
        assert not node_accepts(old)
    synthetic = report()
    with pytest.raises(ValueError):
        build_live_report(
            PROOF, synthetic["supervisor"], {k: synthetic[k] for k in EVIDENCE_KEYS}
        )


@pytest.mark.parametrize("key", list(PROOF))
def test_every_admission_field_is_bound_independently(key):
    r = live_report()
    r["proof"][key] = "private-invalid"
    with pytest.raises(ValueError):
        validate_live_report(r, PROOF)
    assert not node_accepts(r)


@pytest.mark.parametrize(
    "path,key,value",
    [
        ((), "extra", "private-invalid"),
        ((), "outcome", "INCONCLUSIVE"),
        (("window",), "clock", "synthetic"),
        (("window",), "elapsed_ms", 299999),
        (("supervisor",), "network", "none"),
        (("supervisor",), "elapsed_ms", 360001),
        (("supervisor",), "reaped", False),
        (("window",), "active", False),
    ],
)
def test_false_clock_or_cleanup_never_publishes_success(path, key, value):
    r = live_report()
    target = r
    for part in path:
        target = target[part]
    target[key] = value
    with pytest.raises(ValueError):
        validate_live_report(r, PROOF)
    assert not node_accepts(r)


def test_unavailable_is_not_run_with_no_attested_start():
    r = not_run(PROOF)
    assert r["execution"] == r["outcome"] == "NOT RUN"
    assert node_accepts(r)


class LiveEngine(Engine):
    """Fake Docker only; no call to a daemon or Hoben network is made."""

    def __init__(self, clock):
        super().__init__()
        self.clock, self.fed = clock, []
        self.mode = "live"

    def feed(self, name, payload, **kwargs):
        self.fed.append(payload)

    def request(self, method, path, body=None, **kwargs):
        if path.endswith("/start"):
            self.clock[0] = 309
        if "/archive?" in path and method == "GET":
            r = live_report()
            data = {
                "started": True,
                "reason": "completed",
                "oom_killed": False,
                "pids_limited": False,
                "mode": self.mode,
                "evidence": {k: r[k] for k in EVIDENCE_KEYS},
            }
            raw = json.dumps(data, separators=(",", ":")).encode()
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as archive:
                item = tarfile.TarInfo("receipt.json")
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
            return buf.getvalue()
        r = super().request(method, path, body, **kwargs)
        if path.endswith("/json") and "/containers/" in path:
            r["Config"] = self.config
        return r


def test_shared_supervisor_live_path_uses_only_private_stdin_and_verified_bounds():
    clock = [0]
    engine = LiveEngine(clock)
    r = supervise_live(IMAGE, PROOF, IDENTITY, engine=engine, clock=lambda: clock[0])
    assert r["outcome"] == "SUCCESS" and r["supervisor"]["reaped"]
    assert engine.fed == [IDENTITY] and engine.deleted
    assert engine.config["HostConfig"]["NetworkMode"] == "bridge"
    assert engine.config["HostConfig"]["Memory"] == 1024**3
    assert engine.config["HostConfig"]["PidsLimit"] == 128
    assert engine.config["Cmd"][0] == "live" and engine.config["Env"] == []
    assert "11111111111111111111111111111111" not in json.dumps(engine.config)
    assert "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD" not in json.dumps(r)
    assert node_accepts(r)


def test_offline_receipt_cannot_be_promoted_by_live_supervisor():
    clock = [0]
    engine = LiveEngine(clock)
    engine.mode = "offline"
    r = supervise_live(IMAGE, PROOF, IDENTITY, engine=engine, clock=lambda: clock[0])
    assert r["outcome"] == "FAILURE" and engine.deleted
    assert r["criteria"]["continuous_300s"] == "NOT RUN"


def test_missing_backend_never_falls_back_to_host_or_feeds_identity():
    engine = Mock()
    engine.request.side_effect = OSError("private-invalid")
    r = supervise_live(IMAGE, PROOF, IDENTITY, engine=engine)
    assert r["outcome"] == "NOT RUN"
    engine.feed.assert_not_called()


def test_live_source_contains_fixed_worker_not_fixture_or_git():
    bundle = SourceBundle(live=True)
    try:
        assert (bundle.folder / "scripts/ha_session_live_worker.py").is_file()
        assert not (bundle.folder / "tests/fixtures/ha_session_worker.py").exists()
        assert not (bundle.folder / ".git").exists()
    finally:
        bundle.close()


def test_live_workflow_has_separate_environment_publication_and_no_all_expansion():
    w = yaml.load(
        (ROOT / ".github/workflows/hoben-manual.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    jobs = w["jobs"]
    assert jobs["collect-ha"]["environment"] == "hoben-live"
    assert "selection != 'hoben-live'" in jobs["collect"]["if"]
    assert "selection == 'hoben-live'" in jobs["collect-ha"]["if"]
    assert "environment" not in jobs["publish-ha"]
    assert "environment" not in jobs["result-ha"]
    capture = next(s for s in jobs["collect-ha"]["steps"] if s.get("id") == "capture")
    assert capture["if"] == "steps.recheck.outputs.approved == 'true'"
    assert capture["run"] == "python -I trusted/scripts/launch_ha_manual_live.py"
    for name in ("publish-ha", "result-ha"):
        assert set(jobs[name]["permissions"]) == {"contents"}
    from scripts.manual_hoben_context import PLANS

    assert PLANS["all"] == ("h1h2", "session-300", "session-reconnect")


@pytest.mark.parametrize(
    "mutation", ["entrypoint", "network", "stdin", "mount", "writable_source"]
)
def test_live_effective_config_is_checked_before_any_identity_stream(mutation):
    clock = [0]
    engine = LiveEngine(clock)

    def mutate(current):
        current["Config"] = copy.deepcopy(engine.config)
        if mutation == "entrypoint":
            current["Config"]["Entrypoint"] = ["other"]
        elif mutation == "network":
            current["Config"]["NetworkDisabled"] = True
        elif mutation == "stdin":
            current["Config"]["OpenStdin"] = False
        elif mutation == "writable_source":
            current["HostConfig"]["Mounts"][0]["ReadOnly"] = False
        else:
            current["HostConfig"]["Mounts"] = []
        return current

    engine.mutate = mutate
    # Preserve the altered Config rather than the base double's generated one.
    original = engine.request

    def request(method, path, body=None, **kwargs):
        result = original(method, path, body, **kwargs)
        return (
            mutate(result)
            if "/containers/" in path and path.endswith("/json")
            else result
        )

    engine.request = request
    r = supervise_live(IMAGE, PROOF, IDENTITY, engine=engine, clock=lambda: clock[0])
    assert r["outcome"] == "NOT RUN" and not engine.started and not engine.fed


@pytest.mark.parametrize(
    "raw",
    [
        IDENTITY,
        b"{}\n",
        b"X" * 513,
        b"",
        b'{"user_guid":"a","device_guid":"b","extra":1}\n',
    ],
)
def test_private_guardian_channel_is_closed_bounded_and_never_echoed(monkeypatch, raw):
    import os
    import time

    from scripts import ha_session_guard as guard

    class Selector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def select(self, *args):
            return [True]

    original = os.read
    monkeypatch.setattr(guard.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(
        guard.os, "read", lambda fd, size: raw[:size] if fd == 0 else original(fd, size)
    )
    if raw == IDENTITY:
        fd = guard.identity_pipe(time.monotonic_ns() + 10_000_000_000)
        try:
            assert original(fd, 513) == IDENTITY
        finally:
            os.close(fd)
    else:
        with pytest.raises(ValueError) as error:
            guard.identity_pipe(time.monotonic_ns() + 10_000_000_000)
        assert "user_guid" not in str(error.value) and "DDDD" not in str(error.value)


def source_context(tmp_path, monkeypatch):
    from scripts import launch_ha_manual_live as launch
    from scripts.manual_hoben_context import WORKFLOW

    candidate, trusted, storage = (
        tmp_path / name for name in ("candidate", "trusted", "storage")
    )
    for folder in (candidate, trusted, storage):
        folder.mkdir()
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
    source = {
        "GITHUB_ACTIONS": "true",
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
        "RUNNER_TEMP": str(storage),
        "MANUAL_HOBEN_SCENARIO": "hoben-live",
        "MANUAL_HOBEN_SHA": PROOF["merge_sha"],
        "MANUAL_HOBEN_CANDIDATE": PROOF["candidate_sha"],
        "MANUAL_HOBEN_PR": str(PROOF["pr_number"]),
        "MANUAL_HOBEN_CI": str(PROOF["ci_run_id"]),
        "MANUAL_HOBEN_ENVIRONMENT": str(PROOF["environment_id"]),
        "MANUAL_HOBEN_CLAIM": PROOF["claim_sha"],
        "MANUAL_HOBEN_POLICY": PROOF["environment_digest"],
    }
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **k: PROOF["merge_sha"].encode()
    )
    monkeypatch.setattr(launch, "ROOT", trusted)
    return launch, candidate, storage, source


def test_capture_checks_local_provenance_and_image_before_identity(
    tmp_path, monkeypatch
):
    launch, candidate, storage, source = source_context(tmp_path, monkeypatch)
    assert launch.provenance(source, candidate) == PROOF
    for key in (
        "GITHUB_REF",
        "GITHUB_RUN_ATTEMPT",
        "MANUAL_HOBEN_POLICY",
        "MANUAL_HOBEN_CI",
        "MANUAL_HOBEN_CLAIM",
    ):
        with pytest.raises((ValueError, OSError)):
            launch.provenance(source | {key: "PRIVATE_INVALID"}, candidate)
    for key, value in source.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(launch.sys, "argv", ["launch_ha_manual_live.py"])
    # No image => refuse BEFORE missing identity keys are accessed.
    with pytest.raises(ValueError):
        launch.main()
    (storage / "hoben-ha-runtime.id").write_text(IMAGE)
    monkeypatch.setenv("HOBEN_USER_GUID", "1" * 32)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "D" * 32)
    called = Mock(return_value=not_run(PROOF))
    monkeypatch.setattr(launch, "supervise_live", called)
    assert launch.main() == 0
    assert called.call_args.args[:2] == (IMAGE, PROOF)
    assert called.call_args.args[2] == IDENTITY
    public = json.loads((storage / "hoben-ha-live-public/report.json").read_text())
    assert public["outcome"] == "NOT RUN" and node_accepts(public)
    assert not (storage / "hoben-ha-live-public/report.json").stat().st_mode & 0o077


def test_publication_refuses_missing_noncanonical_and_private_reports(tmp_path):
    r = live_report()
    file = tmp_path / "report.json"
    for raw in (
        "",
        "{}",
        json.dumps(r),
        json.dumps(r, separators=(",", ":")) + " ",
        "X" * 8193,
    ):
        file.write_text(raw)
        result = subprocess.run(
            [
                "node",
                "-e",
                "const a=require('./.github/scripts/ha-manual-live-report.cjs');"
                "try{a.read(process.argv[1],JSON.parse(process.argv[2]));process.exitCode=2}catch(_){}",
                str(file),
                json.dumps(PROOF),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0 and result.stdout == result.stderr == ""


def test_boolean_is_not_an_admitted_attempt_number():
    r = live_report()
    r["proof"]["run_attempt"] = True
    with pytest.raises(ValueError):
        validate_live_report(r, PROOF)
    assert not node_accepts(r)
