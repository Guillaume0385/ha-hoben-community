"""Offline crypto/context/privacy simulations; no real Hoben connection or key."""

import copy
import hashlib
import json
import os
import shutil
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_boundary_request as entry

SOURCE = Path(__file__).resolve().parents[1]
POLICY = json.loads((SOURCE / ".github/config/hoben-boundary.json").read_text())
MAIN = "a" * 40
USER = "SYNTHETIC-PRIVATE-IDENTITY"
RAW = b"SYNTHETIC-PRIVATE-RX-REGISTER-VALUES"


def session(index=0):
    return {
        "mode": "H1" if index < 6 else "H2",
        "pause_seconds": (0, 0.1, 1)[(index % 6) // 2],
        "repetition": index % 2 + 1,
        "boundary_proven": False,
        "partial": False,
        "prefix_complete": True,
        "rx_bytes": 120,
        "read_calls": 10,
        "pongs_before_open": 1,
        "pongs_under_h2": 2 if index >= 6 else 0,
        "v4_requests": 2 if index >= 6 else 0,
        "correlated_responses": 2 if index >= 6 else 0,
        "exception_responses": 0,
        "stop": "observation_budget",
        "emission_stop": None,
        "opening_context": {"eligible": True, "status": "accepted_v4_prefix"},
        "h1": {"status": "compatible"},
        "h2": {"status": "compatible"},
        "comparison": "compatible_with_both",
        "untrusted": USER,
    }


@pytest.fixture
def runner(tmp_path, monkeypatch):
    trusted, candidate, storage = [
        tmp_path / n for n in ("trusted", "candidate", "storage")
    ]
    for p in (trusted, candidate, storage):
        p.mkdir()
    config = trusted / ".github/config"
    config.mkdir(parents=True)
    for filename in ("hoben-boundary.json", "hoben-capture-recipient.pem"):
        shutil.copy(SOURCE / ".github/config" / filename, config)
    event = {
        "action": "labeled",
        "label": {"name": "manager-hoben-boundary-dry-run"},
        "sender": {"login": "Guillaume0385", "id": 18246624, "type": "User"},
        "repository": {"full_name": entry.REPOSITORY, "id": 1401398724},
        "pull_request": {
            "number": 49,
            "state": "open",
            "draft": True,
            "head": {
                "sha": POLICY["candidate_sha"],
                "ref": "codex/issue-48",
                "repo": {"full_name": entry.REPOSITORY},
            },
            "base": {"ref": "main", "repo": {"full_name": entry.REPOSITORY}},
        },
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    environment = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": entry.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "pull_request_target",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": entry.WORKFLOW,
        "GITHUB_SHA": MAIN,
        "GITHUB_WORKFLOW_SHA": MAIN,
        "GITHUB_RUN_ID": "123",
        "GITHUB_EVENT_PATH": str(event_path),
        "HOBEN_BOUNDARY_APPROVED_SHA": POLICY["candidate_sha"],
        "BOUNDARY_PHASE": "dry-run",
        "RUNNER_TEMP": str(storage),
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "HOBEN_USER_GUID", "HOBEN_DEVICE_GUID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(entry, "ROOT", trusted)
    monkeypatch.setattr(entry, "utcnow", lambda: datetime(2026, 10, 9, tzinfo=UTC))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    original = entry.command

    def command(*args, cwd=None):
        if args[0] == "/usr/bin/git":
            assert args[1:] == ("rev-parse", "HEAD")
            return (MAIN if cwd == trusted else POLICY["candidate_sha"]).encode()
        return original(*args, cwd=cwd)

    monkeypatch.setattr(entry, "command", command)
    return SimpleNamespace(
        trusted=trusted,
        candidate=candidate,
        storage=storage,
        event=event,
        event_path=event_path,
        exports=storage / "hoben-boundary-request-exports",
        command=command,
    )


def live(runner, monkeypatch):
    runner.event["label"]["name"] = "manager-hoben-boundary-live"
    runner.event_path.write_text(json.dumps(runner.event))
    monkeypatch.setenv("BOUNDARY_PHASE", "live")
    monkeypatch.setenv("HOBEN_USER_GUID", USER)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "0" * 32)


def fake_collector(monkeypatch, runner, *, mode="complete"):
    imports, calls = [], []

    async def campaign(private, **kwargs):
        calls.append(kwargs)
        assert (private / "recipient.pem").is_file()
        assert not list(private.glob("preflight*"))
        assert kwargs == {
            "mode": "both",
            "seconds": 90,
            "user_guid": USER,
            "device_guid": "0" * 32,
        }
        assert not os.environ.get("HOBEN_USER_GUID") and not os.environ.get(
            "HOBEN_DEVICE_GUID"
        )
        entry.private_write(private / "rx.bin", RAW)
        result = {"boundary_proven": False, "sessions": [session(i) for i in range(12)]}
        if mode == "bad-report":
            result["sessions"][0]["stop"] = USER
        if mode == "cancel":
            import asyncio

            partial = private / "session-01"
            partial.mkdir(mode=0o700)
            data = session()
            data.update(partial=True, stop="cancelled")
            entry.private_json(partial / "analysis.json", data)
            raise asyncio.CancelledError
        print(USER)
        return result

    def load(name):
        imports.append(name)
        assert name == "scripts.probe_opened_client_boundary"
        private = next(runner.storage.glob("hoben-request-private-*"))
        assert (private / "recipient.pem").is_file() and not list(
            private.glob("preflight*")
        )
        return SimpleNamespace(
            normalize_user_guid=lambda value: value,
            INITIAL_DEVICE_GUID="0" * 32,
            campaign_with_signals=campaign,
        )

    monkeypatch.setattr(entry.importlib, "import_module", load)
    return imports, calls


def assert_private_cleanup(runner):
    assert not list(runner.storage.glob("hoben-request-private-*"))
    if runner.exports.is_dir():
        assert stat.S_IMODE(runner.exports.stat().st_mode) == 0o700
        assert set(p.name for p in runner.exports.iterdir()) <= {
            "captures.cms",
            "report.json",
        }
        for p in runner.exports.iterdir():
            assert stat.S_IMODE(p.stat().st_mode) == 0o600
            assert RAW not in p.read_bytes() and USER.encode() not in p.read_bytes()


def test_real_main_public_certificate_pin_and_cipher_algorithm():
    der = entry.command(
        "/usr/bin/openssl",
        "x509",
        "-in",
        str(SOURCE / ".github/config/hoben-capture-recipient.pem"),
        "-outform",
        "DER",
    )
    assert hashlib.sha256(der).hexdigest() == POLICY["recipient_sha256"]


def test_installed_channel_dry_run_simulates_crypto_without_candidate_or_secret(
    runner, monkeypatch, capsys
):
    def forbidden(*args):
        raise AssertionError("Candidate import forbidden in dry-run")

    monkeypatch.setattr(entry.importlib, "import_module", forbidden)
    # Deliberately present: a dry-run must not even consume this synthetic secret.
    monkeypatch.setenv("HOBEN_USER_GUID", USER)
    assert entry.run("dry-run") == 0
    assert os.environ["HOBEN_USER_GUID"] == USER
    report = json.loads((runner.exports / "report.json").read_text())
    assert report["result"] == "dry_run_pass" and report["executed_sessions"] == 0
    assert report["boundary_proven"] is False and report["main_sha"] == MAIN
    structure = entry.command(
        "/usr/bin/openssl",
        "cms",
        "-cmsout",
        "-print",
        "-inform",
        "DER",
        "-in",
        str(runner.exports / "captures.cms"),
    )
    assert b"authEnvelopedData" in structure and b"aes-256-gcm" in structure
    assert b"rsaesOaep" in structure and b"sha256" in structure
    assert not capsys.readouterr().out
    assert_private_cleanup(runner)


def test_live_simulation_calls_exact_reviewed_library_with_fixed_bounds_and_safe_report(
    runner, monkeypatch, capsys
):
    live(runner, monkeypatch)
    imports, calls = fake_collector(monkeypatch, runner)
    assert entry.run("live") == 0
    assert imports == ["scripts.probe_opened_client_boundary"] and len(calls) == 1
    report = json.loads((runner.exports / "report.json").read_text())
    assert report["executed_sessions"] == 12 and report["observation_seconds"] == 90
    assert report["result"] == "inconclusive" and report["boundary_proven"] is False
    assert len(report["sessions"]) == 12 and "untrusted" not in report["sessions"][0]
    assert not capsys.readouterr().out
    assert_private_cleanup(runner)


def test_cancellation_seals_partial_rx_and_fixed_failure_report(runner, monkeypatch):
    live(runner, monkeypatch)
    fake_collector(monkeypatch, runner, mode="cancel")
    assert entry.run("live") == 1
    report = json.loads((runner.exports / "report.json").read_text())
    assert report["result"] == "failure" and report["executed_sessions"] == 1
    assert report["sessions"][0]["stop"] == "cancelled"
    assert_private_cleanup(runner)


def test_invalid_public_report_is_never_exported_but_capture_remains_sealed(
    runner, monkeypatch
):
    live(runner, monkeypatch)
    fake_collector(monkeypatch, runner, mode="bad-report")
    assert entry.run("live") == 1
    assert (runner.exports / "captures.cms").is_file()
    assert not (runner.exports / "report.json").exists()
    assert_private_cleanup(runner)


@pytest.mark.parametrize(
    "env,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("GITHUB_ACTOR", "other"),
        ("GITHUB_TRIGGERING_ACTOR", "other"),
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_REF", "refs/heads/candidate"),
        ("GITHUB_REPOSITORY", "fork/repo"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_SHA", "b" * 40),
        ("GITHUB_WORKFLOW_SHA", "b" * 40),
        ("GITHUB_WORKFLOW_REF", "candidate.yml"),
        ("HOBEN_BOUNDARY_APPROVED_SHA", "b" * 40),
        ("BOUNDARY_PHASE", "arbitrary"),
        ("GITHUB_TOKEN", "SYNTHETIC-TOKEN"),
        ("GH_TOKEN", "SYNTHETIC-TOKEN"),
    ],
)
def test_wrong_context_or_inherited_token_refuses_before_exports(
    runner, monkeypatch, env, value
):
    monkeypatch.setenv(env, value)
    assert entry.run("dry-run") == 1
    assert not runner.exports.exists()
    assert_private_cleanup(runner)


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "wrong-pin",
        "private-key",
        "symlink",
        "expired",
        "future",
        "scenario",
        "crypto-unavailable",
    ],
)
def test_certificate_or_scenario_failure_precedes_candidate_import_and_secret_access(
    runner, monkeypatch, problem
):
    live(runner, monkeypatch)
    imports, calls = fake_collector(monkeypatch, runner)
    file = runner.trusted / ".github/config/hoben-capture-recipient.pem"
    if problem == "missing":
        file.unlink()
    elif problem == "private-key":
        file.write_text("-----BEGIN PRIVATE KEY-----\nSYNTHETIC-PRIVATE\n")
    elif problem == "symlink":
        file.unlink()
        file.symlink_to(SOURCE / ".github/config/hoben-capture-recipient.pem")
    elif problem == "expired":
        monkeypatch.setattr(
            entry, "utcnow", lambda: datetime(2027, 10, 8, 7, tzinfo=UTC)
        )
    elif problem == "future":
        monkeypatch.setattr(
            entry, "utcnow", lambda: datetime(2026, 10, 8, 7, tzinfo=UTC)
        )
    elif problem == "crypto-unavailable":

        def fail(*args):
            raise ValueError("SYNTHETIC-PRIVATE")

        monkeypatch.setattr(entry, "encrypt", fail)
    else:
        manifest = runner.trusted / ".github/config/hoben-boundary.json"
        policy = copy.deepcopy(POLICY)
        policy["recipient_sha256" if problem == "wrong-pin" else "scenario"] = (
            "b" * 64 if problem == "wrong-pin" else "other"
        )
        manifest.write_text(json.dumps(policy))
    assert entry.run("live") == 1
    assert not imports and not calls and os.environ["HOBEN_USER_GUID"] == USER
    assert_private_cleanup(runner)


def test_encryption_failure_after_collection_never_falls_back_to_plaintext(
    runner, monkeypatch
):
    live(runner, monkeypatch)
    fake_collector(monkeypatch, runner)
    original = entry.command

    def fail(*args, cwd=None):
        if args[1] == "cms" and any(s.endswith("/captures.cms") for s in args):
            raise ValueError("SYNTHETIC-PRIVATE")
        return original(*args, cwd=cwd)

    monkeypatch.setattr(entry, "command", fail)
    assert entry.run("live") == 1 and not list(runner.exports.iterdir())
    assert_private_cleanup(runner)


@pytest.mark.parametrize(
    "change", ["count", "order", "stop", "numeric", "nan", "proof", "free-text"]
)
def test_public_projection_rejects_unsafe_values_instead_of_logging(runner, change):
    data = {"boundary_proven": False, "sessions": [session()]}
    s = data["sessions"][0]
    if change == "count":
        data["sessions"] *= 13
    elif change == "order":
        s["mode"] = "H2"
    elif change == "stop":
        s["stop"] = USER
    elif change == "numeric":
        s["rx_bytes"] = -1
    elif change == "nan":
        s["rx_bytes"] = float("nan")
    elif change == "proof":
        data["boundary_proven"] = True
    else:
        s["v4_requests"] = USER
    with pytest.raises(ValueError, match="Boundary request prerequisite unavailable"):
        entry.safe_report(data, interrupted=False)


def test_private_storage_rejects_symlink_export_or_storage_inside_checkouts(
    runner, monkeypatch
):
    runner.exports.symlink_to(runner.candidate, target_is_directory=True)
    assert entry.run("dry-run") == 1 and not list(runner.candidate.iterdir())
    runner.exports.unlink()
    monkeypatch.setenv("RUNNER_TEMP", str(runner.trusted))
    assert entry.run("dry-run") == 1
    assert_private_cleanup(runner)
