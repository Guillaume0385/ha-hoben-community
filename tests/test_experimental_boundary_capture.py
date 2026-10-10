"""Offline crypto/context/privacy simulations; no real Hoben connection or key."""

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

from scripts import run_experimental_boundary as entry

SOURCE = Path(__file__).resolve().parents[1]
RECIPIENT_SHA256 = "f0209da5d964c02b9733610bfb4457f7bebd24fdfd32934e1165460bf0ab3246"
POLICY = {
    "schema": 1,
    "scenario": "h1h2",
    "tracking_issue": 54,
    "tracking_issue_id": 5768789242,
    "environment": "hoben-experimental",
    "candidate_sha": "a" * 40,
}
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
    (config / "hoben-experimental.json").write_text(
        json.dumps({k: v for k, v in POLICY.items() if k != "candidate_sha"})
    )
    shutil.copy(SOURCE / "tests/fixtures/hoben-experimental-recipient.pem", config)
    event = {
        "ref": "refs/heads/experimental",
        "before": "f" * 40,
        "after": MAIN,
        "created": False,
        "deleted": False,
        "forced": False,
        "sender": {"login": "Guillaume0385", "id": 18246624, "type": "User"},
        "repository": {"full_name": entry.REPOSITORY, "id": 1401398724},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    environment = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": entry.REPOSITORY,
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": entry.WORKFLOW,
        "GITHUB_SHA": MAIN,
        "GITHUB_WORKFLOW_SHA": MAIN,
        "GITHUB_RUN_ID": "123",
        "GITHUB_EVENT_PATH": str(event_path),
        "EXPERIMENTAL_APPROVED_SHA": POLICY["candidate_sha"],
        "EXPERIMENTAL_PHASE": "dry-run",
        "RUNNER_TEMP": str(storage),
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    # Model the launcher's isolated child, even when pytest itself runs inside
    # Actions. Refusal tests below reintroduce each forbidden variable explicitly.
    for key in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_RESULTS_URL",
        "ACTIONS_CACHE_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "GITHUB_STEP_SUMMARY",
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(entry, "ROOT", candidate)
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
        exports=storage / "hoben-experimental-exports",
        command=command,
    )


def live(runner, monkeypatch):
    monkeypatch.setenv("EXPERIMENTAL_PHASE", "live")
    monkeypatch.setenv("HOBEN_USER_GUID", USER)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "0" * 32)


def fake_collector(monkeypatch, runner, *, mode="complete", count=12):
    imports, calls = [], []

    async def campaign(private, **kwargs):
        assert isinstance(kwargs.pop("diagnostic"), entry.PhaseDiagnostic)
        calls.append(kwargs)
        assert not (private / "recipient.pem").exists()
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
        result = {
            "boundary_proven": False,
            "sessions": [session(i) for i in range(count)],
        }
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
        private = next(runner.storage.glob("hoben-experimental-private-*"))
        assert not (private / "recipient.pem").exists() and not list(
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
    assert not list(runner.storage.glob("hoben-experimental-private-*"))
    if runner.exports.is_dir():
        assert stat.S_IMODE(runner.exports.stat().st_mode) == 0o700
        assert set(p.name for p in runner.exports.iterdir()) <= {"report.json"}
        for p in runner.exports.iterdir():
            assert stat.S_IMODE(p.stat().st_mode) == 0o600
            assert RAW not in p.read_bytes() and USER.encode() not in p.read_bytes()


@pytest.mark.parametrize("count", [0, 1, 6, 11, 12])
def test_early_campaign_stop_exports_failure_and_nonzero_exit(
    runner, monkeypatch, count
):
    live(runner, monkeypatch)
    fake_collector(monkeypatch, runner, count=count)
    assert entry.run("live") == (0 if count == 12 else 1)
    report = json.loads((runner.exports / "report.json").read_text())
    assert report["executed_sessions"] == count
    assert report["result"] == ("inconclusive" if count == 12 else "failure")
    assert report["reason"] == (
        "hypotheses_unproven" if count == 12 else "collection_interrupted"
    )
    assert not (runner.exports / "captures.cms").exists()
    assert_private_cleanup(runner)


def test_reviewed_experimental_public_certificate_pin_and_cipher_algorithm():
    der = entry.command(
        "/usr/bin/openssl",
        "x509",
        "-in",
        str(SOURCE / "tests/fixtures/hoben-experimental-recipient.pem"),
        "-outform",
        "DER",
    )
    assert hashlib.sha256(der).hexdigest() == RECIPIENT_SHA256


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
    assert report["boundary_proven"] is False and report["experimental_sha"] == MAIN
    assert not (runner.exports / "captures.cms").exists()
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


def test_absent_secret_refuses_before_any_campaign_call(runner, monkeypatch):
    live(runner, monkeypatch)
    _, calls = fake_collector(monkeypatch, runner)
    monkeypatch.delenv("HOBEN_USER_GUID")
    assert entry.run("live") == 1
    assert calls == []
    assert not (runner.exports / "captures.cms").exists()
    assert not (runner.exports / "report.json").exists()
    assert_private_cleanup(runner)


@pytest.mark.parametrize("device", [None, "", "0" * 32])
def test_absent_or_initial_device_identity_uses_the_existing_zero_identity(
    runner, monkeypatch, device
):
    live(runner, monkeypatch)
    if device is None:
        monkeypatch.delenv("HOBEN_DEVICE_GUID")
    else:
        monkeypatch.setenv("HOBEN_DEVICE_GUID", device)
    _, calls = fake_collector(monkeypatch, runner)
    assert entry.main(["live"]) == 0
    assert len(calls) == 1 and calls[0]["device_guid"] == "0" * 32
    assert_private_cleanup(runner)


@pytest.mark.parametrize("device", ["short", "é" * 32])
def test_invalid_device_identity_has_a_fixed_phase_and_no_campaign(
    runner, monkeypatch, capsys, device
):
    live(runner, monkeypatch)
    monkeypatch.setenv("HOBEN_DEVICE_GUID", device)
    _, calls = fake_collector(monkeypatch, runner)
    assert entry.main(["live"]) == 11
    assert calls == []
    assert capsys.readouterr() == ("", "")
    assert_private_cleanup(runner)


@pytest.mark.parametrize("failure", ["context", "module", "identity", "projection"])
def test_entry_phase_survives_private_exceptions_and_cleanup(
    runner, monkeypatch, capsys, failure
):
    live(runner, monkeypatch)
    imports, calls = fake_collector(monkeypatch, runner)

    def refused(*args, **kwargs):
        raise RuntimeError(USER + RAW.decode())

    if failure == "context":
        monkeypatch.setattr(entry, "context", refused)
    elif failure == "module":
        monkeypatch.setattr(entry.importlib, "import_module", refused)
    elif failure == "identity":
        monkeypatch.delenv("HOBEN_USER_GUID")
    else:
        monkeypatch.setattr(entry, "safe_report", refused)
    assert (
        entry.main(["live"])
        == {
            "context": 10,
            "module": 10,
            "identity": 11,
            "projection": 15,
        }[failure]
    )
    assert capsys.readouterr() == ("", "")
    assert len(calls) == (1 if failure == "projection" else 0)
    assert len(imports) == (1 if failure in ("identity", "projection") else 0)
    assert not (runner.exports / "report.json").exists()
    assert_private_cleanup(runner)


def test_entry_cleanup_failure_is_nonzero_without_exception_output(
    runner, monkeypatch, capsys
):
    live(runner, monkeypatch)
    fake_collector(monkeypatch, runner)

    def refused(path):
        raise RuntimeError(USER + RAW.decode())

    monkeypatch.setattr(entry.shutil, "rmtree", refused)
    assert entry.main(["live"]) == 16
    assert capsys.readouterr() == ("", "")
    # The parent's fixed-prefix cleanup is a second attempt, never a raw upload.
    assert len(list(runner.storage.glob("hoben-experimental-private-*"))) == 1


def test_invalid_public_report_is_never_exported_but_capture_remains_sealed(
    runner, monkeypatch
):
    live(runner, monkeypatch)
    fake_collector(monkeypatch, runner, mode="bad-report")
    assert entry.run("live") == 1
    assert not (runner.exports / "captures.cms").exists()
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
        ("EXPERIMENTAL_APPROVED_SHA", "c" * 40),
        ("EXPERIMENTAL_PHASE", "arbitrary"),
        ("GITHUB_TOKEN", "SYNTHETIC-TOKEN"),
        ("GH_TOKEN", "SYNTHETIC-TOKEN"),
        ("ACTIONS_RUNTIME_TOKEN", "SYNTHETIC-TOKEN"),
        ("ACTIONS_RESULTS_URL", "https://synthetic.invalid"),
        ("ACTIONS_CACHE_URL", "https://synthetic.invalid"),
        ("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "SYNTHETIC-TOKEN"),
        ("ACTIONS_ID_TOKEN_REQUEST_URL", "https://synthetic.invalid"),
        ("GITHUB_ENV", "/synthetic/output"),
        ("GITHUB_OUTPUT", "/synthetic/output"),
        ("GITHUB_STEP_SUMMARY", "/synthetic/output"),
    ],
)
def test_wrong_context_or_inherited_token_refuses_before_exports(
    runner, monkeypatch, env, value
):
    monkeypatch.setenv(env, value)
    assert entry.run("dry-run") == 1
    assert not runner.exports.exists()
    assert_private_cleanup(runner)


def test_bad_policy_refuses_before_candidate_import_and_secret_access(
    runner, monkeypatch
):
    live(runner, monkeypatch)
    imports, calls = fake_collector(monkeypatch, runner)
    manifest = runner.trusted / ".github/config/hoben-experimental.json"
    policy = {k: v for k, v in POLICY.items() if k != "candidate_sha"}
    policy["scenario"] = "unknown"
    manifest.write_text(json.dumps(policy))
    assert entry.run("live") == 1
    assert not imports and not calls and os.environ["HOBEN_USER_GUID"] == USER
    assert_private_cleanup(runner)


def test_missing_certificate_and_unavailable_crypto_do_not_block_new_campaign(
    runner, monkeypatch
):
    live(runner, monkeypatch)
    imports, calls = fake_collector(monkeypatch, runner)
    (runner.trusted / ".github/config/hoben-experimental-recipient.pem").unlink()

    def forbid_encryption(*args, **kwargs):
        raise AssertionError("No encryption or CMS CLI may run")

    monkeypatch.setattr(entry, "encrypt", forbid_encryption)
    monkeypatch.setattr(entry, "prepare_recipient", forbid_encryption)
    monkeypatch.setattr(entry, "seal", forbid_encryption)
    assert entry.run("live") == 0
    assert len(imports) == len(calls) == 1
    assert not (runner.exports / "captures.cms").exists()
    assert_private_cleanup(runner)


def test_bad_public_report_never_falls_back_to_private_capture(runner, monkeypatch):
    live(runner, monkeypatch)
    fake_collector(monkeypatch, runner, mode="bad-report")
    assert entry.run("live") == 1
    assert not (runner.exports / "report.json").exists()
    assert not (runner.exports / "captures.cms").exists()
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


@pytest.mark.parametrize(
    "change",
    ["ref", "after", "before", "sender", "repo", "created", "deleted", "forced"],
)
def test_push_event_forgery_never_imports_candidate(runner, monkeypatch, change):
    live(runner, monkeypatch)
    imports, calls = fake_collector(monkeypatch, runner)
    if change == "sender":
        runner.event["sender"]["id"] = 123
    elif change == "repo":
        runner.event["repository"]["id"] = 123
    elif change == "ref":
        runner.event["ref"] = "refs/heads/main"
    elif change == "after":
        runner.event["after"] = "c" * 40
    elif change == "before":
        runner.event["before"] = MAIN
    else:
        runner.event[change] = True
    runner.event_path.write_text(json.dumps(runner.event))
    assert entry.run("live") == 1 and not imports and not calls
    assert not runner.exports.exists()
    assert os.environ["HOBEN_USER_GUID"] == USER


@pytest.mark.parametrize("directory", ["trusted", "candidate"])
def test_changed_checkout_is_refused_before_secret_access(
    runner, monkeypatch, directory
):
    live(runner, monkeypatch)
    imports, calls = fake_collector(monkeypatch, runner)

    def command(*args, cwd=None):
        if args[0] == "/usr/bin/git" and cwd == getattr(runner, directory):
            return ("c" * 40).encode()
        return runner.command(*args, cwd=cwd)

    monkeypatch.setattr(entry, "command", command)
    assert entry.run("live") == 1 and not imports and not calls
    assert os.environ["HOBEN_USER_GUID"] == USER


def test_new_entry_archive_roundtrip_and_wrong_recipient_refusal(tmp_path):
    """Exercise the exported entry's cipher, not just the older archive helper."""
    import io
    import subprocess
    import tarfile

    private, exports = tmp_path / "private", tmp_path / "exports"
    private.mkdir(mode=0o700)
    exports.mkdir(mode=0o700)
    key, cert = tmp_path / "synthetic.key", tmp_path / "synthetic.pem"
    command = [
        "/usr/bin/openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:3072",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=OfflineSyntheticRecipient",
        "-keyout",
        str(key),
        "-out",
        str(cert),
    ]
    subprocess.run(
        command,
        capture_output=True,
        check=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
    )
    recipient = private / "recipient.pem"
    entry.private_write(recipient, cert.read_bytes())
    entry.private_write(private / "rx.bin", RAW)
    entry.private_json(private / "journal.json", {"synthetic_private_identity": USER})
    entry.seal(private, exports, recipient)
    encrypted = exports / "captures.cms"
    assert (
        RAW not in encrypted.read_bytes()
        and USER.encode() not in encrypted.read_bytes()
    )
    decrypted = entry.command(
        "/usr/bin/openssl",
        "cms",
        "-decrypt",
        "-inform",
        "DER",
        "-in",
        str(encrypted),
        "-recip",
        str(cert),
        "-inkey",
        str(key),
    )
    with tarfile.open(fileobj=io.BytesIO(decrypted)) as archive:
        assert set(archive.getnames()) == {"rx.bin", "journal.json"}
        assert archive.extractfile("rx.bin").read() == RAW
        assert USER.encode() in archive.extractfile("journal.json").read()
    wrong_key = tmp_path / "different.key"
    entry.command(
        "/usr/bin/openssl",
        "genpkey",
        "-algorithm",
        "RSA",
        "-pkeyopt",
        "rsa_keygen_bits:3072",
        "-out",
        str(wrong_key),
    )
    with pytest.raises(ValueError):
        entry.command(
            "/usr/bin/openssl",
            "cms",
            "-decrypt",
            "-inform",
            "DER",
            "-in",
            str(encrypted),
            "-recip",
            str(cert),
            "-inkey",
            str(wrong_key),
        )
    assert not (private / "captures.tar").exists()
