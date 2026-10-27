"""Seal private #48 captures before any artifact leaves a GitHub runner.

OpenSSL CMS AuthEnvelopedData uses AES-256-GCM and the MANAGER's public RSA
certificate. The decryption key is never configured on GitHub or the runner.
"""

import hashlib
import os
import re
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.boundary_capture import private_json


class ArchiveError(Exception):
    """A fixed error without raw data, certificate contents or subprocess output."""


def _openssl(*args: str) -> bytes:
    """No shell, inherited GitHub token, arbitrary output, or stderr propagation."""
    result = subprocess.run(
        ["/usr/bin/openssl", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    if result.returncode:
        raise ArchiveError("Capture encryption failed")
    return result.stdout


def prepare_recipient(directory: Path, pem: str, expected_sha256: str) -> Path:
    """Validate the public certificate and encryption support BEFORE network I/O."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or (
        len(pem) > 16384
        or "PRIVATE KEY" in pem
        or pem.count("-----BEGIN CERTIFICATE-----") != 1
        or pem.count("-----END CERTIFICATE-----") != 1
    ):
        raise ArchiveError("Invalid capture recipient")
    path = directory / "recipient.pem"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(pem)
    der = _openssl("x509", "-in", str(path), "-outform", "DER")
    if hashlib.sha256(der).hexdigest() != expected_sha256:
        raise ArchiveError("Capture recipient fingerprint mismatch")
    # -checkend alone checks expiry, not notBefore. A pinned public recipient
    # must already be valid and remain valid for the whole bounded campaign.
    try:
        dates = dict(
            line.split("=", 1)
            for line in _openssl("x509", "-in", str(path), "-noout", "-dates")
            .decode("ascii")
            .splitlines()
        )
        if set(dates) != {"notBefore", "notAfter"}:
            raise ValueError
        start, end = (
            datetime.strptime(dates[key], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
            for key in ("notBefore", "notAfter")
        )
    except (UnicodeDecodeError, ValueError):
        raise ArchiveError("Invalid capture recipient validity") from None
    now = datetime.now(UTC)
    if start > now or end < now + timedelta(hours=1):
        raise ArchiveError("Capture recipient is not valid for the next hour")
    public_key = _openssl("x509", "-in", str(path), "-pubkey", "-noout")
    # The key is public; only use the output internally and do not log it.
    key_path = directory / "recipient-public.pem"
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(public_key)
    key_text = _openssl("pkey", "-pubin", "-in", str(key_path), "-text", "-noout")
    match = re.search(rb"Public-Key: \((\d+) bit\)", key_text)
    if b"Modulus:" not in key_text or match is None or int(match[1]) < 3072:
        raise ArchiveError("A public RSA certificate of at least 3072 bits is required")
    # Exercise the actual cipher/recipient before releasing the Hoben identity.
    sample = directory / "encryption-preflight.json"
    private_json(sample, {"purpose": "encryption_preflight"})
    encrypted = directory / "encryption-preflight.cms"
    encrypt_file(sample, encrypted, path)
    sample.unlink()
    encrypted.unlink()
    key_path.unlink()
    return path


def encrypt_file(source: Path, target: Path, recipient: Path) -> None:
    """Authenticated encryption with no plaintext fallback or partial output."""
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    try:
        _openssl(
            "cms",
            "-encrypt",
            "-binary",
            "-aes-256-gcm",
            "-outform",
            "DER",
            "-in",
            str(source),
            "-out",
            str(target),
            "-recip",
            str(recipient),
            "-keyopt",
            "rsa_padding_mode:oaep",
            "-keyopt",
            "rsa_oaep_md:sha256",
        )
        if target.stat().st_size == 0:
            raise ArchiveError("Capture encryption failed")
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def seal_captures(private: Path, exports: Path, recipient: Path) -> None:
    """Bundle complete raw/journal/identity files; export one ciphertext only."""
    bundle = private / "captures.tar"
    fd = os.open(bundle, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with tarfile.open(bundle, "w") as archive:
            for item in sorted(private.rglob("*")):
                if item == bundle or item == recipient:
                    continue
                if item.is_symlink():
                    raise ArchiveError("Unexpected capture member")
                if item.is_file():
                    archive.add(
                        item, arcname=str(item.relative_to(private)), recursive=False
                    )
        encrypt_file(bundle, exports / "captures.cms", recipient)
    finally:
        bundle.unlink(missing_ok=True)
