"""Fixed, protected D7 entry. Never invoked with real identities by DEV/CI.

Consume a one-use post-approval permit and verify both reviewed checkouts before
accessing identity. The child inherits no Actions/token/identity environment.
"""

import hashlib
import hmac
import json
import os
import re
import signal
import stat
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_TTL_SECONDS = 120
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.hoben.myhoben import normalize_user_guid  # noqa: E402
from scripts.info_manual_contract import (  # noqa: E402
    OBSERVATION,
    PROCESS,
    build_report,
    need,
    validate_proof,
    validate_report,
)
from scripts.info_manual_process import run_process  # noqa: E402
from scripts.manual_hoben_context import proof as context_proof  # noqa: E402


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("admission_redirect_refused")


def github_read(path, token):
    # The permit is a capability anchored by GitHub after the API recheck, not
    # a local JSON flag. Never send this token to the stove or another host.
    url = "https://api.github.com/repos/Guillaume0385/ha-hoben-community/" + path
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hoben-info-manual",
        },
    )
    with urllib.request.build_opener(NoRedirect()).open(
        request, timeout=10
    ) as response:
        need(response.status == 200 and response.geturl() == url)
        raw = response.read(131073)
        need(len(raw) <= 131072)
        return json.loads(raw)


def private_read(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(fd)
        need(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid())
        need(stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_size <= maximum)
        data = os.read(fd, maximum + 1)
        need(len(data) == metadata.st_size)
        return data
    finally:
        os.close(fd)


def provenance(source):
    need(source.get("GITHUB_JOB") == "collect-info")
    _, proof = context_proof(
        source, ROOT.parent / "candidate", plans={"hoben-live": ("hoben-live",)}
    )
    for key, target in (
        ("MANUAL_HOBEN_CI", "ci_run_id"),
        ("MANUAL_HOBEN_ENVIRONMENT", "environment_id"),
    ):
        need(re.fullmatch(r"[1-9][0-9]{0,15}", source.get(key, "")))
        proof[target] = int(source[key])
    proof.update(
        environment_digest=source.get("MANUAL_HOBEN_POLICY"),
        contract_digest=source.get("MANUAL_HOBEN_CONTRACT"),
        claim_sha=source.get("MANUAL_HOBEN_CLAIM"),
        launch_tag_sha=source.get("MANUAL_HOBEN_LAUNCH"),
    )
    proof = validate_proof(proof)
    folder = Path(source["RUNNER_TEMP"]).resolve(strict=True) / "hoben-info-private"
    metadata = folder.lstat()
    need(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid())
    need(stat.S_IMODE(metadata.st_mode) == 0o700)
    permit_path = folder / "permit.json"
    permit = json.loads(private_read(permit_path, 2048))
    need(type(permit) is dict and set(permit) == {"schema", "proof", "nonce"})
    need(type(permit["schema"]) is int and permit["schema"] == 2)
    need(validate_proof(permit["proof"]) == proof)
    nonce = permit["nonce"]
    need(type(nonce) is str and re.fullmatch(r"[a-f0-9]{64}", nonce))
    token = source.pop("INFO_MANUAL_ADMISSION_TOKEN", "")
    need(type(token) is str and 0 < len(token) <= 4096)
    name = "hoben-info-start-" + str(proof["run_id"]) + "-attempt1"
    branch = github_read("branches/experimental", token)
    need(
        branch.get("protected") is True
        and branch.get("commit", {}).get("sha") == proof["merge_sha"]
    )
    ref = github_read("git/ref/tags/" + name, token)
    need(ref.get("ref") == "refs/tags/" + name)
    need(
        ref.get("object")
        == {
            "type": "tag",
            "sha": proof["launch_tag_sha"],
            "url": ref.get("object", {}).get("url"),
        }
    )
    tag = github_read("git/tags/" + proof["launch_tag_sha"], token)
    need(tag.get("sha") == proof["launch_tag_sha"] and tag.get("tag") == name)
    need(tag.get("object", {}).get("type") == "commit")
    need(tag.get("object", {}).get("sha") == proof["merge_sha"])
    issued = datetime.fromisoformat(tag["tagger"]["date"].replace("Z", "+00:00"))
    need(issued.tzinfo is not None)
    issued = issued.timestamp()
    need(-2 <= time.time() - issued <= LAUNCH_TTL_SECONDS)
    message = json.loads(tag["message"])
    need(
        type(message) is dict
        and set(message) == {"schema", "kind", "proof", "nonce_digest"}
    )
    need(message["schema"] == 1 and message["kind"] == "info-launch-permit")
    need(message["proof"] == {k: v for k, v in proof.items() if k != "launch_tag_sha"})
    need(message["nonce_digest"] == hashlib.sha256(nonce.encode()).hexdigest())
    jobs = github_read(
        "actions/runs/" + str(proof["run_id"]) + "/jobs?per_page=100", token
    )
    need(type(jobs) is dict and type(jobs.get("jobs")) is list)
    selected = [j for j in jobs["jobs"] if j.get("name") == "collect-info"]
    need(len(selected) == 1)
    job = selected[0]
    need(job.get("run_id") == proof["run_id"] and job.get("run_attempt") == 1)
    need(
        job.get("head_sha") == proof["merge_sha"] and job.get("status") == "in_progress"
    )
    admission = [
        s for s in job["steps"] if s.get("name") == "Info post-approval admission"
    ]
    capture = [
        s
        for s in job["steps"]
        if s.get("name") == "One passive Info session with independent OS guardian"
    ]
    need(len(admission) == len(capture) == 1)
    need(
        admission[0].get("status") == "completed"
        and admission[0].get("conclusion") == "success"
    )
    need(capture[0].get("status") == "in_progress")
    need(
        type(admission[0].get("number")) is int
        and type(capture[0].get("number")) is int
    )
    need(0 < admission[0]["number"] < capture[0]["number"] <= 100)
    manifest = json.loads((ROOT / ".github/info-manual-route.json").read_text())
    encoded = json.dumps(manifest, separators=(",", ":"), ensure_ascii=False).encode()
    need(hashlib.sha256(encoded).hexdigest() == proof["contract_digest"])
    for checkout in (ROOT, ROOT.parent / "candidate"):
        for name, digest in manifest["files"].items():
            need(
                type(name) is str
                and not Path(name).is_absolute()
                and ".." not in Path(name).parts
            )
            source_path = checkout / name
            need(source_path.is_file() and not source_path.is_symlink())
            need(source_path.stat().st_size <= 262144)
            need(hashlib.sha256(source_path.read_bytes()).hexdigest() == digest)
    need(-2 <= time.time() - issued <= LAUNCH_TTL_SECONDS)
    permit_path.unlink()  # A second capture cannot reuse the post-approval permit.
    return proof, folder


def write_sealed(folder, proof, report):
    report = validate_report(report, proof)
    # The signing key is born only AFTER every owned child has been reaped.
    # An unproven process cleanup cannot mint an authenticated live report.
    p = report["process"]
    need(
        (not p["launch_attempted"] and not report["observation"]["started"])
        or (p["group_empty"] and p["guardian_waited"] and p["control_closed"])
    )
    data = json.dumps(report, separators=(",", ":"), allow_nan=False).encode()
    need(len(data) <= 8192)
    key = os.urandom(32)
    signature = hmac.new(key, data, hashlib.sha256).hexdigest()
    for name, content in (
        ("attestation.key", key),
        (
            "sealed-report.json",
            json.dumps(
                {"report": report, "signature": signature},
                separators=(",", ":"),
                allow_nan=False,
            ).encode(),
        ),
    ):
        fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            need(os.write(fd, content) == len(content))
        finally:
            os.close(fd)


def main():
    phase = "context"
    proof = folder = None
    try:
        need(len(sys.argv) == 1)
        proof, folder = provenance(os.environ)
        phase = "identity"
        identity = {
            "user": os.environ.pop("HOBEN_USER_GUID", ""),
            "device": os.environ.pop("HOBEN_DEVICE_GUID", ""),
        }
        identity["user"] = normalize_user_guid(identity["user"])
        need(
            type(identity["device"]) is str
            and re.fullmatch(r"[a-fA-F0-9]{32}", identity["device"])
        )
        need(set(identity["device"]) != {"0"})
        stopped = False

        def stop(signum, frame):
            nonlocal stopped
            stopped = True

        previous = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
        phase = "process"
        try:
            report = run_process(proof, identity, cancelled=lambda: stopped)
        finally:
            identity.clear()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        phase = "report"
        write_sealed(folder, proof, report)
        return 0  # Scientific verdict is independent of collection/publication.
    except (Exception, KeyboardInterrupt):
        if phase == "identity" and proof is not None:
            # Provenance was verified, but no process launch was attempted.
            # This is the only pre-launch absence claim the collector makes.
            try:
                process = dict(PROCESS)
                process["first_error"] = "identity"
                write_sealed(
                    folder, proof, build_report(proof, dict(OBSERVATION), process)
                )
                return 0
            except (Exception, KeyboardInterrupt):
                pass
        print(
            "INFO_MANUAL_DIAGNOSTIC category=" + phase + " status=refused",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt):
        raise SystemExit(1) from None
