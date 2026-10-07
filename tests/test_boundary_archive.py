"""Real offline encryption round trips and local/live CLI trust boundaries."""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts.boundary_archive import ArchiveError, prepare_recipient, seal_captures
from scripts.boundary_capture import PrivateCapture
from scripts.probe_opened_client_boundary import (
    WORKFLOW_REF,
    main,
    verify_actions_context,
)

PRIVATE = b"SYNTHETIC-PRIVATE-RX-IDENTITY-and-household-data"


def openssl(*args, check=True):
    return subprocess.run(
        ["/usr/bin/openssl", *map(str, args)],
        capture_output=True,
        check=check,
        timeout=30,
    )


@pytest.fixture(scope="module")
def recipient(tmp_path_factory):
    directory = tmp_path_factory.mktemp("synthetic-recipient")
    key = directory / "key.pem"
    cert = directory / "certificate.pem"
    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:3072",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=SyntheticBoundaryRecipient",
        "-keyout",
        key,
        "-out",
        cert,
    )
    der = openssl("x509", "-in", cert, "-outform", "DER").stdout
    return cert, key, hashlib.sha256(der).hexdigest()


def test_authenticated_ciphertext_roundtrip_and_tamper_detection(tmp_path, recipient):
    cert, key, fingerprint = recipient
    private = tmp_path / "private"
    exports = tmp_path / "exports"
    private.mkdir(mode=0o700)
    exports.mkdir(mode=0o700)
    capture = PrivateCapture(private / "session-01")
    capture._raw.write(PRIVATE)
    capture.event({"kind": "synthetic_annotation", "offset": 0, "length": len(PRIVATE)})
    capture.close()
    path = prepare_recipient(private, cert.read_text(), fingerprint)
    seal_captures(private, exports, path)
    encrypted = exports / "captures.cms"
    assert PRIVATE not in encrypted.read_bytes()
    assert encrypted.stat().st_mode & 0o777 == 0o600
    assert not (private / "captures.tar").exists()
    assert set(p.name for p in exports.iterdir()) == {"captures.cms"}
    decrypted = openssl(
        "cms",
        "-decrypt",
        "-binary",
        "-inform",
        "DER",
        "-in",
        encrypted,
        "-recip",
        cert,
        "-inkey",
        key,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(decrypted)) as archive:
        assert archive.extractfile("session-01/rx.bin").read() == PRIVATE
        assert all(member.mode == 0o600 for member in archive.getmembers())
    # CMS AuthEnvelopedData detects alterations; ordinary CBC would not meet
    # this contract. No decoded byte goes to console or a public artifact.
    changed = bytearray(encrypted.read_bytes())
    changed[-1] ^= 1
    damaged = tmp_path / "damaged.cms"
    damaged.write_bytes(changed)
    failure = openssl(
        "cms",
        "-decrypt",
        "-binary",
        "-inform",
        "DER",
        "-in",
        damaged,
        "-recip",
        cert,
        "-inkey",
        key,
        check=False,
    )
    assert failure.returncode != 0


@pytest.mark.parametrize("fingerprint", ["0" * 64, "A" * 64, "private-input", "0" * 63])
def test_bad_recipient_fails_before_capture(tmp_path, recipient, fingerprint):
    cert, _, _ = recipient
    with pytest.raises(ArchiveError) as error:
        prepare_recipient(tmp_path, cert.read_text(), fingerprint)
    assert "PRIVATE" not in str(error.value)
    assert not (tmp_path / "encryption-preflight.cms").exists()


def test_never_accept_private_key_or_symlink_capture(tmp_path, recipient):
    cert, key, fingerprint = recipient
    with pytest.raises(ArchiveError):
        prepare_recipient(tmp_path, cert.read_text() + key.read_text(), fingerprint)
    private = tmp_path / "private"
    exports = tmp_path / "exports"
    private.mkdir()
    exports.mkdir()
    path = prepare_recipient(private, cert.read_text(), fingerprint)
    (private / "unsafe-link").symlink_to(key)
    with pytest.raises(ArchiveError):
        seal_captures(private, exports, path)
    assert not (exports / "captures.cms").exists()


def actions_context(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "HOBEN_BOUNDARY_APPROVED_SHA": sha,
        "RUNNER_TEMP": str(tmp_path),
        "HOBEN_USER_GUID": "0123456789abcdef0123456789abcdef",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("GITHUB_REPOSITORY", "fork/repo"),
        ("GITHUB_REF", "refs/heads/codex/issue-48"),
        ("GITHUB_EVENT_NAME", "schedule"),
        ("GITHUB_ACTOR", "guillaume0385"),
        ("GITHUB_TRIGGERING_ACTOR", "other"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_WORKFLOW_REF", "candidate-workflow"),
        ("HOBEN_BOUNDARY_APPROVED_SHA", "a" * 40),
    ],
)
def test_cli_refuses_local_untrusted_replayed_or_changed_context(
    monkeypatch, tmp_path, key, value
):
    actions_context(monkeypatch, tmp_path)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        verify_actions_context()


def test_cli_preflight_seals_synthetic_data_and_exports_only_safe_report(
    monkeypatch, tmp_path, recipient, capsys
):
    from scripts import probe_opened_client_boundary as cli

    cert, _, fingerprint = recipient
    actions_context(monkeypatch, tmp_path)
    monkeypatch.setenv("HOBEN_CAPTURE_CERTIFICATE", cert.read_text())
    calls = []

    async def campaign(private, **kwargs):
        calls.append(kwargs)
        capture = PrivateCapture(private / "session-01")
        capture._raw.write(PRIVATE)
        capture.close()
        return {"schema": 1, "executed_sessions": 1, "boundary_proven": False}

    monkeypatch.setattr(cli, "campaign_with_signals", campaign)
    assert main(["--live", "--mode", "H1", "--recipient-sha256", fingerprint]) == 0
    output = capsys.readouterr()
    assert PRIVATE.decode() not in output.out + output.err
    exports = tmp_path / "hoben-boundary-exports"
    assert set(p.name for p in exports.iterdir()) == {"captures.cms", "report.json"}
    report = json.loads((exports / "report.json").read_text())
    assert report == {"schema": 1, "executed_sessions": 1, "boundary_proven": False}
    assert len(calls) == 1
    assert not list(tmp_path.glob("hoben-boundary-private-*"))


def test_cli_missing_encryption_channel_never_calls_campaign(
    monkeypatch, tmp_path, recipient, capsys
):
    from scripts import probe_opened_client_boundary as cli

    cert, _, _ = recipient
    actions_context(monkeypatch, tmp_path)
    monkeypatch.setenv("HOBEN_CAPTURE_CERTIFICATE", cert.read_text())

    async def forbidden(*args, **kwargs):
        pytest.fail("No collection before recipient preflight")

    monkeypatch.setattr(cli, "campaign_with_signals", forbidden)
    assert main(["--live", "--mode", "H2", "--recipient-sha256", "0" * 64]) == 1
    assert "PRIVATE" not in capsys.readouterr().err
    assert not (tmp_path / "hoben-boundary-exports/captures.cms").exists()


def test_cli_argument_error_never_echoes_accidental_private_value(capsys):
    with pytest.raises(SystemExit):
        main(["--live", "--mode", PRIVATE.decode()])
    assert PRIVATE.decode() not in capsys.readouterr().err
