"""Fixed experimental H1/H2 entry, admitted by the reviewed experimental gate.

Only the reviewed post-merge experimental SHA is launched. The fixed launcher
removes runner/GitHub tokens first; GitHub independently gates the environment.
No CMS key or certificate is required for new runs. Unknown boundaries remain
hypotheses; raw streams live only under RUNNER_TEMP and are always removed.
"""

import argparse
import asyncio
import contextlib
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Guillaume0385/ha-hoben-community"
WORKFLOW = (
    f"{REPOSITORY}/.github/workflows/hoben-experimental.yml@refs/heads/experimental"
)
STOP = {
    "observation_budget",
    "peer_eof",
    "pending_response_eof",
    "response_timeout",
    "opening_timeout",
    "rx_limit",
    "authorization_required",
    "opening_rejected",
    "unexpected_opening_type",
    "unsupported_opening",
    "invalid_opening_prefix",
    "unusable_pending_session",
    "modbus_exception",
    "invalid_correlation",
    "cancelled",
    "transport_or_capture_error",
}
ANOMALY = {
    None,
    "terminal_close_h2",
    "invalid_mbap_h2",
    "unsupported_type_h2",
    "invalid_correlation",
}
OPENING = {
    "missing_opening",
    "invalid_opening_offset",
    "incomplete_opening_prefix",
    "unsupported_opening",
    "unaccepted_opening_prefix",
    "accepted_v4_prefix",
    "invalid_opening_prefix",
}
COMPARISON = {
    "compatible_with_both",
    "h2_contradicted",
    "neither_model_supported",
    "h2_compatible_h1_inconclusive",
    "insufficient_data",
}
PHASE_EXIT_CODES = {
    "context": 10,
    "identity": 11,
    "dns_tls": 12,
    "open": 13,
    "collect": 14,
    "projection": 15,
    "cleanup": 16,
}


class PhaseDiagnostic:
    """Remember only fixed phases, never exceptions or private input.

    The first observed failure survives partial-report projection and cleanup.
    A successful overall run still returns zero. The isolated CLI uses a fixed
    nonzero exit code to pass the phase to the parent, with no child output.
    """

    def __init__(self) -> None:
        self.current = "context"
        self.failure: str | None = None
        self.cleanup_failed = False

    def __call__(self, phase: str, failed: bool = False) -> None:
        require(type(phase) is str and phase in PHASE_EXIT_CODES)
        require(type(failed) is bool)
        self.current = phase
        if failed and phase == "cleanup":
            self.cleanup_failed = True
        if failed and self.failure is None:
            self.failure = phase


class SafeParser(argparse.ArgumentParser):
    """Refuse malformed arguments without echoing their potentially private text."""

    def error(self, message: str) -> None:
        raise ValueError("Invalid experimental arguments")


def require(fact: bool) -> None:
    if not fact:
        raise ValueError("Boundary request prerequisite unavailable")


def utcnow() -> datetime:
    return datetime.now(UTC)


def command(*args: str, cwd: Path | None = None) -> bytes:
    """Never pass a token/identity to a subprocess or expose arbitrary output."""
    result = subprocess.run(
        args,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    require(result.returncode == 0)
    return result.stdout


def private_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def private_json(path: Path, value: dict) -> None:
    private_write(path, json.dumps(value, allow_nan=False, sort_keys=True).encode())


def encrypt(source: Path, target: Path, certificate: Path) -> None:
    """Same reviewed CMS contract as #49; never substitute plaintext on failure."""
    private_write(target, b"")
    try:
        command(
            "/usr/bin/openssl",
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
            str(certificate),
            "-keyopt",
            "rsa_padding_mode:oaep",
            "-keyopt",
            "rsa_oaep_md:sha256",
        )
        require(target.stat().st_size > 0)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def prepare_recipient(private: Path, fingerprint: str) -> Path:
    source = ROOT.parent / "trusted/.github/config/hoben-experimental-recipient.pem"
    require(source.is_file() and not source.is_symlink())
    pem = source.read_text(encoding="ascii")
    require(
        len(pem) <= 16384
        and "PRIVATE KEY" not in pem
        and pem.count("-----BEGIN CERTIFICATE-----") == 1
        and pem.count("-----END CERTIFICATE-----") == 1
    )
    recipient = private / "recipient.pem"
    private_write(recipient, pem.encode("ascii"))
    der = command("/usr/bin/openssl", "x509", "-in", str(recipient), "-outform", "DER")
    require(hashlib.sha256(der).hexdigest() == fingerprint)
    dates = command(
        "/usr/bin/openssl", "x509", "-in", str(recipient), "-noout", "-dates"
    )
    start, end = [
        datetime.strptime(line.split("=", 1)[1], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=UTC
        )
        for line in dates.decode("ascii").splitlines()
    ]
    require(start <= utcnow() and end >= utcnow() + timedelta(hours=1))
    public = private / "public.pem"
    private_write(
        public,
        command("/usr/bin/openssl", "x509", "-in", str(recipient), "-noout", "-pubkey"),
    )
    details = command(
        "/usr/bin/openssl", "pkey", "-pubin", "-in", str(public), "-text", "-noout"
    )
    bits = re.search(rb"Public-Key: \((\d+) bit\)", details)
    require(b"Modulus:" in details and bits is not None and int(bits[1]) >= 3072)
    sample, encrypted = private / "preflight.json", private / "preflight.cms"
    private_json(sample, {"purpose": "synthetic_encryption_preflight"})
    encrypt(sample, encrypted, recipient)
    sample.unlink()
    encrypted.unlink()
    public.unlink()
    return recipient


def seal(private: Path, exports: Path, recipient: Path) -> None:
    bundle = private / "captures.tar"
    private_write(bundle, b"")
    try:
        with tarfile.open(bundle, "w") as archive:
            for item in sorted(private.rglob("*")):
                if item in (bundle, recipient):
                    continue
                require(not item.is_symlink())
                if item.is_file():
                    archive.add(
                        item, arcname=str(item.relative_to(private)), recursive=False
                    )
        encrypt(bundle, exports / "captures.cms", recipient)
    finally:
        bundle.unlink(missing_ok=True)


def context(phase: str) -> tuple[dict, Path]:
    """Check immutable experimental checkouts and original push provenance.

    The admission gate additionally verifies GitHub decision, merge, HEAD,
    environment and approval APIs; these local checks do not replace it.
    """
    expected = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
        "EXPERIMENTAL_PHASE": phase,
    }
    require(all(os.environ.get(key) == value for key, value in expected.items()))
    merged_sha = os.environ.get("GITHUB_SHA", "")
    candidate_sha = os.environ.get("EXPERIMENTAL_APPROVED_SHA", "")
    trusted = ROOT.parent / "trusted"
    require(
        phase in ("dry-run", "live")
        and re.fullmatch(r"[0-9a-f]{40}", merged_sha) is not None
        and re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is not None
        and candidate_sha == merged_sha
        and os.environ.get("GITHUB_WORKFLOW_SHA") == merged_sha
        and re.fullmatch(r"[1-9][0-9]{0,19}", os.environ.get("GITHUB_RUN_ID", ""))
        is not None
        and ROOT.is_dir()
        and not ROOT.is_symlink()
        and trusted.is_dir()
        and not trusted.is_symlink()
        and command("/usr/bin/git", "rev-parse", "HEAD", cwd=ROOT).decode().strip()
        == candidate_sha
        and command("/usr/bin/git", "rev-parse", "HEAD", cwd=trusted).decode().strip()
        == merged_sha
    )
    config = trusted / ".github/config/hoben-experimental.json"
    require(config.is_file() and not config.is_symlink())
    policy = json.loads(config.read_text())
    require(
        policy["schema"] == 1
        and policy["scenario"] == "h1h2"
        and policy["environment"] == "hoben-experimental"
    )
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    require(
        event["sender"]["login"] == "Guillaume0385"
        and event["sender"]["id"] == 18246624
        and event["sender"]["type"] == "User"
        and event["repository"]["full_name"] == REPOSITORY
        and event["repository"]["id"] == 1401398724
        and event["ref"] == "refs/heads/experimental"
        and event["after"] == merged_sha
        and re.fullmatch(r"[0-9a-f]{40}", event["before"]) is not None
        and event["before"] != merged_sha
        and all(event[k] is False for k in ("created", "deleted", "forced"))
    )
    storage = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    require(
        storage.is_dir()
        and all(storage != p and not storage.is_relative_to(p) for p in (ROOT, trusted))
    )
    policy["candidate_sha"] = candidate_sha
    return policy, storage


def number(value, maximum: int = 1048576):
    require(type(value) is int and math.isfinite(value) and 0 <= value <= maximum)
    return value


def category(value, allowed):
    require(value in allowed)
    return value


def safe_report(report: dict, *, interrupted: bool) -> dict:
    """Project only fixed numeric/categorical fields; never publish free text."""
    # The CLI is launched with python -I: repository imports are possible only
    # after context() accepted the checkout and collect() installed its path.
    # In particular, dry-run must not import a repository module at startup.
    from scripts.boundary_public_timeline import safe_timeline

    sessions = report["sessions"]
    require(
        report["boundary_proven"] is False
        and type(sessions) is list
        and len(sessions) <= 12
    )
    public = []
    for index, s in enumerate(sessions):
        mode = "H1" if index < 6 else "H2"
        require(
            s["mode"] == mode
            and s["pause_seconds"] == (0, 0.1, 1)[(index % 6) // 2]
            and s["repetition"] == index % 2 + 1
            and s["boundary_proven"] is False
            and type(s["partial"]) is bool
            and type(s["prefix_complete"]) is bool
            and type(s["opening_context"]["eligible"]) is bool
            and s["opening_context"]["eligible"]
            == (s["opening_context"]["status"] == "accepted_v4_prefix")
            and type(s["v4_requests"]) is int
            and type(s["correlated_responses"]) is int
            and s["v4_requests"] <= (0 if mode == "H1" else 2)
            and s["correlated_responses"] <= s["v4_requests"]
            and s["exception_responses"] <= s["v4_requests"]
            and s["correlated_responses"] + s["exception_responses"] <= s["v4_requests"]
            and (mode == "H2" or s["pongs_under_h2"] == 0)
        )
        item = {
            k: s[k]
            for k in (
                "mode",
                "pause_seconds",
                "repetition",
                "partial",
                "prefix_complete",
            )
        }
        item.update(
            {
                k: number(s[k])
                for k in (
                    "rx_bytes",
                    "read_calls",
                    "pongs_before_open",
                    "pongs_under_h2",
                )
            }
        )
        item.update(
            {
                k: number(s[k], 2)
                for k in ("v4_requests", "correlated_responses", "exception_responses")
            }
        )
        item.update(
            stop=category(s["stop"], STOP),
            emission_stop=category(s["emission_stop"], ANOMALY),
            opening_context={
                "eligible": s["opening_context"]["eligible"],
                "status": category(s["opening_context"]["status"], OPENING),
            },
            h1_status=category(s["h1"]["status"], {"compatible", "inconclusive"}),
            h2_status=category(
                s["h2"]["status"], {"compatible", "contradicted", "inconclusive"}
            ),
            comparison=category(s["comparison"], COMPARISON),
        )
        if "timing_observations" in s:
            item["timing_observations"] = safe_timeline(
                s["timing_observations"],
                rx_bytes=item["rx_bytes"],
                read_calls=item["read_calls"],
            )
        public.append(item)
    interrupted = interrupted or len(public) != 12
    return {
        "schema": 1,
        "scenario": "h1h2",
        "phase": "live",
        "observation_seconds": 90,
        "experimental_sha": os.environ["GITHUB_SHA"],
        "candidate_sha": os.environ["EXPERIMENTAL_APPROVED_SHA"],
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "boundary_proven": False,
        "result": "failure" if interrupted else "inconclusive",
        "reason": "collection_interrupted" if interrupted else "hypotheses_unproven",
        "planned_sessions": 12,
        "executed_sessions": len(public),
        "eligible_sessions": sum(s["opening_context"]["eligible"] for s in public),
        "sessions": public,
    }


def collect(
    private: Path, *, diagnostic: PhaseDiagnostic | None = None
) -> tuple[dict, bool]:
    # Only after local context/token checks and the workflow's admission/recheck.
    # The reviewed #55 collector retains its dispatch-only CLI; call the fixed
    # library without forging that context or exporting any raw capture.
    diagnostic = diagnostic or PhaseDiagnostic()
    diagnostic("context")
    sys.path.insert(0, str(ROOT))
    probe = importlib.import_module("scripts.probe_opened_client_boundary")
    diagnostic("identity")
    user = probe.normalize_user_guid(os.environ.pop("HOBEN_USER_GUID"))
    device = os.environ.pop("HOBEN_DEVICE_GUID", "") or probe.INITIAL_DEVICE_GUID
    require(len(device) == 32 and device.isascii())
    diagnostic("collect")
    try:
        return asyncio.run(
            probe.campaign_with_signals(
                private,
                mode="both",
                seconds=90,
                user_guid=user,
                device_guid=device,
                diagnostic=diagnostic,
            )
        ), False
    except (KeyboardInterrupt, asyncio.CancelledError, Exception):
        diagnostic(diagnostic.current, True)
        # Preserve the failure phase while reading the saved partial analysis.
        # Its public projection is independently validated; raw files stay private.
        diagnostic("projection")
        sessions = [
            json.loads(p.read_text())
            for p in sorted(private.glob("session-*/analysis.json"))
        ]
        return {"boundary_proven": False, "sessions": sessions}, True


def run(phase: str, *, diagnostic: PhaseDiagnostic | None = None) -> int:
    diagnostic = diagnostic or PhaseDiagnostic()
    private = None
    result = 1
    try:
        policy, storage = context(phase)
        # The collector needs no GitHub token. Never inherit one from an action.
        require(
            not any(
                os.environ.get(k)
                for k in (
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
                )
            )
        )
        private = Path(
            tempfile.mkdtemp(prefix="hoben-experimental-private-", dir=storage)
        )
        exports = storage / "hoben-experimental-exports"
        exports.mkdir(mode=0o700)
        if phase == "dry-run":
            # No candidate import, identity read, DNS, transport or Hoben socket.
            private_json(private / "synthetic.json", {"purpose": "dry_run_no_hoben"})
            report = {
                "schema": 1,
                "scenario": "h1h2",
                "phase": phase,
                "result": "dry_run_pass",
                "reason": "no_hoben_connection",
                "boundary_proven": False,
                "experimental_sha": os.environ["GITHUB_SHA"],
                "candidate_sha": policy["candidate_sha"],
                "run_id": int(os.environ["GITHUB_RUN_ID"]),
                "executed_sessions": 0,
            }
            interrupted = False
        else:
            with (
                open(os.devnull, "w") as quiet,
                contextlib.redirect_stdout(quiet),
                contextlib.redirect_stderr(quiet),
            ):
                raw_report, interrupted = collect(private, diagnostic=diagnostic)
            diagnostic("projection")
            # Preserve full reviewed annotations privately, never as public JSON.
            private_json(private / "request-report.json", raw_report)
            # Raw capture and internal journals never leave private storage.
            report = safe_report(raw_report, interrupted=interrupted)
            interrupted = report["result"] == "failure"
        diagnostic("projection")
        private_json(exports / "report.json", report)
        result = 1 if interrupted or diagnostic.cleanup_failed else 0
        if interrupted:
            diagnostic("collect", True)
    except (Exception, KeyboardInterrupt, asyncio.CancelledError):
        diagnostic(diagnostic.current, True)
        # No arbitrary JSON or plaintext fallback on a refused projection.
    finally:
        if private is not None:
            diagnostic("cleanup")
            try:
                shutil.rmtree(private)
            except (Exception, KeyboardInterrupt):
                diagnostic("cleanup", True)
                result = 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("phase", choices=("dry-run", "live"))
    diagnostic = PhaseDiagnostic()
    try:
        args = parser.parse_args(argv)
        result = run(args.phase, diagnostic=diagnostic)
    except (Exception, KeyboardInterrupt, asyncio.CancelledError):
        diagnostic(diagnostic.current, True)
        result = 1
    return (
        0 if result == 0 else PHASE_EXIT_CODES[diagnostic.failure or diagnostic.current]
    )


if __name__ == "__main__":
    raise SystemExit(main())
