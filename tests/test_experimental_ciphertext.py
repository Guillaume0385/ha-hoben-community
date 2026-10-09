"""Validate final CMS uploads with real OpenSSL and synthetic private fixtures."""

import hashlib
import json
import os
import shutil
import subprocess

import pytest
import yaml
from test_experimental_request_gate import ROOT, execute, live
from test_experimental_request_gate import api as api

HELPER = ROOT / ".github/scripts/hoben-experimental-ciphertext.cjs"
CERTIFICATE = ROOT / ".github/config/hoben-experimental-recipient.pem"
PRIVATE = b"SYNTHETIC_PRIVATE_TOKEN_PACKET"
MAX_BYTES = 64 * 1024 * 1024
DRIVER = r"""
const fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
if(input.rejectCrypto)require('node:child_process').execFileSync=()=>{
 throw Error('SYNTHETIC_PRIVATE_TOKEN_PACKET');
};
try {
 require(input.helper).prepare(input.temp,input.certificate,input.fingerprint);
 process.stdout.write('VERIFIED');
} catch { process.stdout.write('REFUSED'); }
"""


def openssl(args, *, data=None):
    result = subprocess.run(
        ["openssl", *args], input=data, capture_output=True, check=True, timeout=20
    )
    return result.stdout


@pytest.fixture(scope="module")
def recipients(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-cms")
    certificates = []
    for name in ("expected", "other"):
        cert, key = root / f"{name}.pem", root / f"{name}.key"
        # Same issuer name, different serial/key: issuer alone must not suffice.
        openssl(
            [
                "req",
                "-x509",
                "-newkey",
                "rsa:3072",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "2",
                "-subj",
                "/CN=synthetic-offline-only",
            ]
        )
        os.chmod(key, 0o600)
        der = openssl(["x509", "-in", str(cert), "-outform", "DER"])
        certificates.append((cert, key, hashlib.sha256(der).hexdigest()))
    return certificates


def encrypt(cert, *, cipher="aes-256-gcm", options=None, data=PRIVATE, other=None):
    args = [
        "cms",
        "-encrypt",
        "-binary",
        f"-{cipher}",
        "-outform",
        "DER",
        "-recip",
        str(cert),
    ]
    args += (
        options
        if options is not None
        else ["-keyopt", "rsa_padding_mode:oaep", "-keyopt", "rsa_oaep_md:sha256"]
    )
    if other:
        args += [
            "-recip",
            str(other),
            "-keyopt",
            "rsa_padding_mode:oaep",
            "-keyopt",
            "rsa_oaep_md:sha256",
        ]
    return openssl(args, data=data)


def source(tmp_path, data):
    folder = tmp_path / "hoben-experimental-exports"
    folder.mkdir(exist_ok=True)
    file = folder / "captures.cms"
    file.write_bytes(data)
    return file


def validate(tmp_path, recipient, *, reject_crypto=False):
    cert, _, fingerprint = recipient
    result = subprocess.run(
        [shutil.which("node"), "-e", DRIVER],
        input=json.dumps(
            {
                "helper": str(HELPER),
                "temp": str(tmp_path),
                "certificate": str(cert),
                "fingerprint": fingerprint,
                "rejectCrypto": reject_crypto,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
        env={"PATH": os.environ["PATH"]},
    )
    assert not result.stderr and PRIVATE.decode() not in result.stdout
    return result.stdout


def assert_refused(tmp_path, recipient):
    assert validate(tmp_path, recipient) == "REFUSED"
    assert not (tmp_path / "hoben-experimental-ciphertext").exists()


def test_verified_snapshot_is_private_and_decrypts_to_synthetic_input(
    tmp_path, recipients
):
    cert, key, _ = recipients[0]
    original = source(tmp_path, encrypt(cert))
    assert validate(tmp_path, recipients[0]) == "VERIFIED"
    folder = tmp_path / "hoben-experimental-ciphertext"
    verified = folder / "captures.cms"
    assert folder.stat().st_mode & 0o777 == 0o700
    assert verified.stat().st_mode & 0o777 == 0o600
    assert (
        verified.read_bytes() != original.read_bytes()
        and PRIVATE not in verified.read_bytes()
    )
    original.write_bytes(PRIVATE)  # Later candidate edits cannot alter this copy.
    inner = openssl(
        [
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-in",
            str(verified),
            "-recip",
            str(cert),
            "-inkey",
            str(key),
        ]
    )
    assert PRIVATE not in inner
    assert (
        openssl(
            [
                "cms",
                "-decrypt",
                "-binary",
                "-inform",
                "DER",
                "-recip",
                str(cert),
                "-inkey",
                str(key),
            ],
            data=inner,
        )
        == PRIVATE
    )
    assert not list(tmp_path.glob("hoben-experimental-seal-*"))


@pytest.mark.parametrize(
    "profile",
    [
        "cbc",
        "pkcs1",
        "sha1",
        "mgf-sha1",
        "oaep-label",
        "other",
        "two-recipients",
        "empty",
    ],
)
def test_wrong_crypto_profile_or_recipient_is_not_exported(
    tmp_path, recipients, profile
):
    cert = recipients[0][0]
    kwargs = {}
    if profile == "cbc":
        kwargs["cipher"] = "aes-256-cbc"
    elif profile == "pkcs1":
        kwargs["options"] = []
    elif profile == "sha1":
        kwargs["options"] = ["-keyopt", "rsa_padding_mode:oaep"]
    elif profile in {"mgf-sha1", "oaep-label"}:
        kwargs["options"] = [
            "-keyopt",
            "rsa_padding_mode:oaep",
            "-keyopt",
            "rsa_oaep_md:sha256",
            "-keyopt",
            "rsa_mgf1_md:sha1" if profile == "mgf-sha1" else "rsa_oaep_label:01",
        ]
    elif profile == "other":
        cert = recipients[1][0]
    elif profile == "two-recipients":
        kwargs["other"] = recipients[1][0]
    else:
        kwargs["data"] = b""
    source(tmp_path, encrypt(cert, **kwargs))
    assert_refused(tmp_path, recipients[0])


@pytest.mark.parametrize(
    "malformation",
    [
        "plaintext",
        "truncated",
        "trailing",
        "indefinite",
        "nonminimal",
        "oversized-length",
        "wrong-content",
        "wrong-mac-tag",
    ],
)
def test_malformed_der_cannot_hide_a_plaintext_fallback(
    tmp_path, recipients, malformation
):
    cms = encrypt(recipients[0][0])
    if malformation == "plaintext":
        cms = b'{"fallback":"' + PRIVATE + b'"}'
    elif malformation == "truncated":
        cms = cms[:-1]
    elif malformation == "trailing":
        cms += PRIVATE
    elif malformation == "indefinite":
        cms = b"\x30\x80" + cms[4:] + b"\x00\x00"
    elif malformation == "nonminimal":
        cms = b"\x30\x83\x00" + cms[2:]
    elif malformation == "oversized-length":
        cms = b"\x30\x84\xff\xff\xff\xff" + cms[4:]
    elif malformation == "wrong-content":
        cms = cms.replace(
            bytes.fromhex("2a864886f70d0109100117"),
            bytes.fromhex("2a864886f70d0109100116"),
            1,
        )
    else:
        assert cms[-18:-16] == b"\x04\x10"
        cms = cms[:-18] + b"\x80" + cms[-17:]
    source(tmp_path, cms)
    assert_refused(tmp_path, recipients[0])


@pytest.mark.parametrize(
    "kind",
    ["missing", "symlink", "parent-symlink", "directory", "fifo", "too-large", "empty"],
)
def test_upload_source_must_be_a_bounded_regular_file(tmp_path, recipients, kind):
    file = source(tmp_path, b"")
    if kind == "missing":
        file.unlink()
    elif kind == "symlink":
        file.unlink()
        target = tmp_path / "private"
        target.write_bytes(PRIVATE)
        file.symlink_to(target)
    elif kind == "parent-symlink":
        file.parent.rename(tmp_path / "private-folder")
        file.parent.symlink_to(tmp_path / "private-folder", target_is_directory=True)
    elif kind in {"directory", "fifo"}:
        file.unlink()
        file.mkdir() if kind == "directory" else os.mkfifo(file, 0o600)
    elif kind == "too-large":
        with file.open("wb") as stream:
            stream.truncate(MAX_BYTES + 1)
    assert_refused(tmp_path, recipients[0])


def test_wrong_certificate_pin_is_refused(tmp_path, recipients):
    source(tmp_path, encrypt(recipients[0][0]))
    cert, key, _ = recipients[0]
    assert_refused(tmp_path, (cert, key, "0" * 64))


@pytest.mark.parametrize("change", ["tampered-tag", "plaintext-payload"])
def test_unverifiable_candidate_bytes_are_always_sealed_by_main(
    tmp_path, recipients, change
):
    cert, key, _ = recipients[0]
    cms = bytearray(encrypt(cert))
    if change == "tampered-tag":
        cms[-1] ^= 1
    else:
        assert cms[-20 - len(PRIVATE) : -18 - len(PRIVATE)] == bytes(
            [0x80, len(PRIVATE)]
        )
        cms[-18 - len(PRIVATE) : -18] = PRIVATE
    source(tmp_path, cms)
    # Only private-key decryption can authenticate the candidate's tag. A proper
    # public DER profile alone could still contain plaintext in its payload.
    # Trusted main seals every byte, including such an unverified inner payload.
    assert validate(tmp_path, recipients[0]) == "VERIFIED"
    sealed = tmp_path / "hoben-experimental-ciphertext/captures.cms"
    assert PRIVATE not in sealed.read_bytes()
    inner = openssl(
        [
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-in",
            str(sealed),
            "-recip",
            str(cert),
            "-inkey",
            str(key),
        ]
    )
    assert inner == cms
    result = subprocess.run(
        [
            "openssl",
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-recip",
            str(cert),
            "-inkey",
            str(key),
        ],
        input=inner,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode != 0


def test_trusted_sealing_failure_exports_nothing_and_removes_private_staging(
    tmp_path, recipients
):
    source(tmp_path, encrypt(recipients[0][0]))
    assert validate(tmp_path, recipients[0], reject_crypto=True) == "REFUSED"
    assert not (tmp_path / "hoben-experimental-ciphertext").exists()
    assert not list(tmp_path.glob("hoben-experimental-seal-*"))


@pytest.mark.parametrize("valid", [False, True])
def test_trusted_gate_checks_final_file_after_a_failed_collection(api, tmp_path, valid):
    live(api)
    work = tmp_path / "work"
    work.mkdir()
    cms = encrypt(CERTIFICATE) if valid else b'{"private":"' + PRIVATE + b'"}'
    source(work, cms)
    result = execute(
        api,
        tmp_path,
        operations=[{"name": "prepare-ciphertext"}],
        env={"EXPERIMENTAL_COLLECT_RESULT": "failure"},
    )
    observed = result["results"][0]
    assert not result["writes"] and PRIVATE.decode() not in json.dumps(result)
    verified = work / "hoben-experimental-ciphertext/captures.cms"
    if valid:
        assert not observed["failed"] and observed["outputs"]["verified"] == "true"
        assert verified.read_bytes() != cms and PRIVATE not in verified.read_bytes()
    else:
        assert observed["failed"] and "verified" not in observed["outputs"]
        assert not verified.exists()


def test_ciphertext_upload_is_guarded_by_main_validation_on_failure_paths():
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-experimental-request.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"]["observations"]["steps"]
    verifier = next(s for s in steps if s.get("id") == "ciphertext")
    upload = next(
        s
        for s in steps
        if "experimental-ciphertext-" in s.get("with", {}).get("name", "")
    )
    assert steps.index(verifier) < steps.index(upload)
    assert (
        "always()" in verifier["if"]
        and "steps.collect.outcome != 'skipped'" in verifier["if"]
    )
    assert (
        "trusted/.github/scripts/hoben-experimental-request.cjs"
        in verifier["with"]["script"]
    )
    assert "gate.prepareCiphertext({context, core})" in verifier["with"]["script"]
    assert (
        upload["if"] == "${{ always() && steps.ciphertext.outputs.verified == 'true' }}"
    )
    assert (
        upload["with"]["path"]
        == "${{ runner.temp }}/hoben-experimental-ciphertext/captures.cms"
    )
    assert all(
        "hoben-experimental-exports" not in s.get("with", {}).get("path", "")
        for s in steps
        if s.get("uses", "").startswith("actions/upload-artifact@")
    )
