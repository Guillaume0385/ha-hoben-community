"""One-use launch capability and no identity access before authenticated proof."""

import copy
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from scripts import launch_info_manual as launch
from scripts.info_manual_contract import OBSERVATION, PROCESS, build_report
from tests.test_info_manual_process_186 import PROOF

CAPTURE = "One passive Info session with independent OS guardian"


def setup_admission(monkeypatch, tmp_path):
    trusted, candidate = tmp_path / "trusted", tmp_path / "candidate"
    for folder in (trusted, candidate):
        (folder / "scripts").mkdir(parents=True)
        (folder / ".github").mkdir()
        (folder / "scripts/fixed.py").write_text("# offline source-integrity fixture\n")
    manifest = {
        "schema": 2,
        "files": {
            "scripts/fixed.py": hashlib.sha256(
                (trusted / "scripts/fixed.py").read_bytes()
            ).hexdigest()
        },
    }
    serialized = json.dumps(manifest, separators=(",", ":"))
    (trusted / ".github/info-manual-route.json").write_text(serialized)
    proof = {
        **PROOF,
        "contract_digest": hashlib.sha256(serialized.encode()).hexdigest(),
    }
    private = tmp_path / "hoben-info-private"
    private.mkdir(mode=0o700)
    permit = private / "permit.json"
    nonce = secrets.token_hex(32)
    permit.write_text(json.dumps({"schema": 2, "proof": proof, "nonce": nonce}))
    permit.chmod(0o600)
    source = {
        "GITHUB_JOB": "collect-info",
        "MANUAL_HOBEN_CI": str(proof["ci_run_id"]),
        "MANUAL_HOBEN_ENVIRONMENT": str(proof["environment_id"]),
        "MANUAL_HOBEN_POLICY": proof["environment_digest"],
        "MANUAL_HOBEN_CONTRACT": proof["contract_digest"],
        "MANUAL_HOBEN_CLAIM": proof["claim_sha"],
        "MANUAL_HOBEN_LAUNCH": proof["launch_tag_sha"],
        "INFO_MANUAL_ADMISSION_TOKEN": "offline-api-double",
        "RUNNER_TEMP": str(tmp_path),
    }
    base = {
        k: v
        for k, v in proof.items()
        if k in {"merge_sha", "candidate_sha", "run_id", "run_attempt", "pr_number"}
    }

    def local_context(s, root, plans):
        assert root == candidate and plans == {"hoben-live": ("hoben-live",)}
        return "hoben-live", copy.deepcopy(base)

    name = "hoben-info-start-" + str(proof["run_id"]) + "-attempt1"
    tag = {
        "sha": proof["launch_tag_sha"],
        "tag": name,
        "object": {"type": "commit", "sha": proof["merge_sha"]},
        "tagger": {"date": datetime.now(timezone.utc).isoformat()},
        "message": json.dumps(
            {
                "schema": 1,
                "kind": "info-launch-permit",
                "proof": {k: v for k, v in proof.items() if k != "launch_tag_sha"},
                "nonce_digest": hashlib.sha256(nonce.encode()).hexdigest(),
            }
        ),
    }
    responses = {
        "branches/experimental": {
            "protected": True,
            "commit": {"sha": proof["merge_sha"]},
        },
        "git/ref/tags/" + name: {
            "ref": "refs/tags/" + name,
            "object": {"type": "tag", "sha": proof["launch_tag_sha"], "url": "unused"},
        },
        "git/tags/" + proof["launch_tag_sha"]: tag,
        "actions/runs/" + str(proof["run_id"]) + "/jobs?per_page=100": {
            "jobs": [
                {
                    "name": "collect-info",
                    "run_id": proof["run_id"],
                    "run_attempt": 1,
                    "head_sha": proof["merge_sha"],
                    "status": "in_progress",
                    "steps": [
                        {
                            "name": "Info post-approval admission",
                            "number": 4,
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": CAPTURE,
                            "number": 5,
                            "status": "in_progress",
                        },
                    ],
                }
            ]
        },
    }
    calls = []

    def github_read(path, token):
        assert token == "offline-api-double"
        calls.append(path)
        return responses[path]

    monkeypatch.setattr(launch, "ROOT", trusted)
    monkeypatch.setattr(launch, "context_proof", local_context)
    monkeypatch.setattr(launch, "github_read", github_read)
    return source, proof, private, permit, responses, calls


def test_nonce_is_anchored_by_github_and_consumed_before_identity(
    monkeypatch, tmp_path
):
    source, expected, folder, permit, _, calls = setup_admission(monkeypatch, tmp_path)
    proof, actual = launch.provenance(source)
    assert proof == expected and actual == folder
    assert len(calls) == 4 and not permit.exists()
    assert "INFO_MANUAL_ADMISSION_TOKEN" not in source
    with pytest.raises((ValueError, OSError)):
        launch.provenance(source)


@pytest.mark.parametrize(
    "mutation",
    [
        "nonce",
        "reference",
        "head",
        "job",
        "attempt",
        "old",
        "future",
        "mode",
        "symlink",
        "source",
        "missing_token",
        "wrong_job",
    ],
)
def test_invalid_admission_never_reaches_identity_or_process(
    monkeypatch, tmp_path, mutation
):
    source, proof, folder, permit, responses, calls = setup_admission(
        monkeypatch, tmp_path
    )
    tag = responses["git/tags/" + proof["launch_tag_sha"]]
    if mutation == "nonce":
        message = json.loads(tag["message"])
        message["nonce_digest"] = "0" * 64
        tag["message"] = json.dumps(message)
    if mutation == "reference":
        next(v for k, v in responses.items() if k.startswith("git/ref/"))["object"][
            "sha"
        ] = "0" * 40
    if mutation == "head":
        responses["branches/experimental"]["commit"]["sha"] = "0" * 40
    if mutation in {"job", "attempt"}:
        job = next(v for k, v in responses.items() if k.startswith("actions/"))["jobs"][
            0
        ]
        if mutation == "job":
            job["steps"][1]["status"] = "completed"
        else:
            job["run_attempt"] = 2
    if mutation in {"old", "future"}:
        tag["tagger"]["date"] = (
            datetime.now(timezone.utc)
            + timedelta(seconds=-180 if mutation == "old" else 30)
        ).isoformat()
    if mutation == "mode":
        permit.chmod(0o644)
    if mutation == "symlink":
        alternate = folder / "alternate"
        permit.rename(alternate)
        permit.symlink_to(alternate)
    if mutation == "source":
        (tmp_path / "candidate/scripts/fixed.py").write_text("# altered\n")
    if mutation == "missing_token":
        source.pop("INFO_MANUAL_ADMISSION_TOKEN")
    if mutation == "wrong_job":
        source["GITHUB_JOB"] = "tests"

    class IdentityGuard(dict):
        def pop(self, key, *args):
            assert key not in {"HOBEN_USER_GUID", "HOBEN_DEVICE_GUID"}
            return super().pop(key, *args)

    monkeypatch.setattr(launch.os, "environ", IdentityGuard(source))
    monkeypatch.setattr(launch.sys, "argv", [str(launch.__file__)])
    monkeypatch.setattr(
        launch, "run_process", lambda *a, **kw: pytest.fail("process before admission")
    )
    assert launch.main() == 1
    assert not (folder / "attestation.key").exists()
    assert not (folder / "sealed-report.json").exists()


def test_unreaped_child_cannot_obtain_a_signing_key(tmp_path):
    process = dict(PROCESS)
    process.update(launch_attempted=True, spawned=True, isolated=True)
    report = build_report(PROOF, dict(OBSERVATION), process)
    assert report["result"] == "FAILURE"
    with pytest.raises(ValueError):
        launch.write_sealed(tmp_path, PROOF, report)
    assert not (tmp_path / "attestation.key").exists()


def test_provenance_checked_identity_refusal_is_authenticated_not_run(
    monkeypatch, tmp_path
):
    proof = dict(PROOF)
    monkeypatch.setattr(launch, "provenance", lambda s: (proof, tmp_path))
    monkeypatch.setattr(launch.sys, "argv", [str(launch.__file__)])
    monkeypatch.setattr(launch.os, "environ", {})
    monkeypatch.setattr(
        launch, "run_process", lambda *a, **kw: pytest.fail("invalid identity launched")
    )
    assert launch.main() == 0
    envelope = json.loads((tmp_path / "sealed-report.json").read_text())
    assert envelope["report"]["result"] == "NOT RUN"
    assert not envelope["report"]["process"]["launch_attempted"]
    assert len((tmp_path / "attestation.key").read_bytes()) == 32


def test_no_redirect_of_github_admission_token():
    with pytest.raises(ValueError):
        launch.NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://invalid.invalid"
        )


def test_no_public_cli_command_or_fixture_selector(monkeypatch):
    monkeypatch.setattr(launch.sys, "argv", [str(launch.__file__), "--fixture"])
    monkeypatch.setattr(
        launch, "provenance", lambda s: pytest.fail("unsupported CLI used")
    )
    assert launch.main() == 1
