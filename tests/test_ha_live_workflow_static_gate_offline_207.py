"""#207 D4-C1: deterministic adversarial audit; no workflow dispatch or secrets."""

import base64
import copy
import hashlib
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from scripts.ha_live_workflow_static_gate_offline import (
    ALWAYS,
    CHECKOUT,
    CLAIM_IF,
    COLLECT_IF,
    ENTRY,
    ROOT,
    WORKER_IF,
    WORKFLOW,
    audit_workflow,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
M = "a" * 40
CHECKOUT_STEP = {
    "id": "checkout",
    "uses": CHECKOUT,
    "with": {"ref": "${{ github.sha }}", "persist-credentials": False},
}


def script(name, *, condition=None, env=None):
    step = {"id": name, "shell": "bash", "run": f"echo synthetic-{name}"}
    if condition is not None:
        step["if"] = condition
    if env is not None:
        step["env"] = env
    return step


def job(
    name, steps, *, needs=None, condition, permissions, outputs=None, environment=None
):
    result = {
        "runs-on": "ubuntu-latest",
        "timeout-minutes": 5,
        "permissions": permissions,
        "steps": [copy.deepcopy(CHECKOUT_STEP), *steps],
        "if": condition,
    }
    if needs is not None:
        result["needs"] = needs
    if outputs is not None:
        result["outputs"] = outputs
    if environment is not None:
        result["environment"] = environment
    return result


def candidate():
    return {
        "name": "Vérification réelle Home Assistant",
        "on": {
            "workflow_dispatch": {
                "inputs": {
                    "scenario": {
                        "type": "choice",
                        "required": True,
                        "default": "hoben-live",
                        "options": ["hoben-live"],
                    }
                }
            }
        },
        "permissions": {},
        "concurrency": {
            "group": "hoben-read-only-observation",
            "cancel-in-progress": False,
            "queue": "max",
        },
        "jobs": {
            "preflight": job(
                "preflight",
                [script("preflight")],
                condition=ENTRY,
                permissions={},
                outputs={"admitted": "${{ steps.preflight.outputs.admitted }}"},
            ),
            "claim": job(
                "claim",
                [script("claim")],
                needs="preflight",
                condition=CLAIM_IF,
                permissions={"contents": "write"},
                outputs={"claim_ref": "${{ steps.claim.outputs.claim_ref }}"},
            ),
            "collect": job(
                "collect",
                [
                    script(
                        "recheck",
                        env={"CLAIM_REF": "${{ needs.claim.outputs.claim_ref }}"},
                    ),
                    script(
                        "worker",
                        condition=WORKER_IF,
                        env={"HOBEN_USER_GUID": "${{ secrets.HOBEN_USER_GUID }}"},
                    ),
                    script("cleanup", condition=ALWAYS),
                ],
                needs="claim",
                condition=COLLECT_IF,
                permissions={"contents": "read"},
                environment="hoben-live",
            ),
            "result": job(
                "result",
                [script("publish")],
                needs="collect",
                condition=ALWAYS,
                permissions={"contents": "read"},
            ),
        },
    }


def mock_source(tree=None):
    payload = yaml.safe_dump(
        tree if tree is not None else candidate(), sort_keys=False, allow_unicode=True
    ).encode("utf8")
    blob = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    return {
        "request": f"{ROOT}/contents/{WORKFLOW}?ref={M}",
        "status": 200,
        "items": {
            "path": WORKFLOW,
            "sha": hashlib.sha1(blob).hexdigest(),
            "encoding": "base64",
            "content": base64.b64encode(payload).decode(),
        },
        "next": None,
    }


def refused(value, **kwargs):
    v = audit_workflow(value, **kwargs)
    assert asdict(v) == {
        "execution": "offline",
        "admission": "NOT RUN",
        "secrets_allowed": False,
        "live_ready": False,
        "complete": False,
        "structure": "REFUSED",
    }


def test_positive_synthetic_is_only_structural_and_never_live():
    for value, args in [
        (candidate(), {}),
        (yaml.safe_dump(candidate(), allow_unicode=True), {}),
        (mock_source(), {"expected_commit_sha": M}),
    ]:
        v = audit_workflow(value, **args)
        assert v.structure == "CANDIDATE_ONLY"
        assert (
            v.execution,
            v.admission,
            v.complete,
            v.live_ready,
            v.secrets_allowed,
        ) == ("offline", "NOT RUN", False, False, False)


def test_actual_ha_workflow_is_not_d4_admissible():
    # This is the unchanged, *real* workflow in the checkout under test.
    current = (ROOT_DIR / WORKFLOW).read_text(encoding="utf8")
    refused(current)


MUTATIONS = [
    ("jobs.preflight.if", "${{ github.ref == 'refs/heads/main' }}"),
    ("jobs.claim.if", "${{ always() }}"),
    ("jobs.collect.if", "${{ always() || needs.claim.result == 'success' }}"),
    ("jobs.result.if", "${{ success() }}"),
    ("jobs.claim.needs", "collect"),
    ("jobs.collect.needs", ["claim", "preflight"]),
    ("jobs.result.needs", "claim"),
    ("jobs.collect.environment", "none"),
    ("jobs.collect.permissions", {"contents": "write"}),
    ("jobs.claim.permissions", {"contents": "read", "id-token": "write"}),
    ("jobs.preflight.permissions", {"contents": "read"}),
    ("jobs.collect.steps.1.env", {}),
    ("jobs.collect.steps.1.run", "echo ${{ secrets.HOBEN_USER_GUID }}"),
    ("jobs.collect.steps.2.if", "${{ always() }}"),
    (
        "jobs.collect.steps.2.env",
        {"HOBEN_USER_GUID": "${{ secrets.HOBEN_DEVICE_GUID }}"},
    ),
    ("jobs.collect.steps.3.if", "${{ success() }}"),
    ("jobs.collect.steps.0.uses", "actions/checkout@v4"),
    ("jobs.collect.steps.0.with.ref", "refs/heads/main"),
    ("jobs.claim.steps.0.with.persist-credentials", True),
    ("jobs.collect.steps.2.continue-on-error", True),
    ("concurrency.cancel-in-progress", True),
    ("concurrency.group", "other-group"),
    ("concurrency.queue", "replace"),
    ("on.workflow_dispatch.inputs.scenario.options", ["hoben-live", "all"]),
    ("jobs.collect.timeout-minutes", 200),
    ("jobs.claim.outputs.claim_ref", "${{ github.sha }}"),
]


def mutate(root, path, replacement):
    parts = path.split(".")
    obj = root
    for key in parts[:-1]:
        obj = obj[int(key)] if type(obj) is list else obj[key]
    last = parts[-1]
    if type(obj) is list:
        obj[int(last)] = replacement
    else:
        obj[last] = replacement


@pytest.mark.parametrize(("path", "replacement"), MUTATIONS)
def test_structural_tampering_refuses(path, replacement):
    bad = candidate()
    mutate(bad, path, replacement)
    refused(bad)


@pytest.mark.parametrize("name", ["preflight", "claim", "collect", "result"])
def test_missing_job_refuses(name):
    bad = candidate()
    del bad["jobs"][name]
    refused(bad)


def test_removed_or_reordered_security_steps_refuse():
    for index in range(4):
        bad = candidate()
        del bad["jobs"]["collect"]["steps"][index]
        refused(bad)
    bad = candidate()
    steps = bad["jobs"]["collect"]["steps"]
    steps[1], steps[2] = steps[2], steps[1]
    refused(bad)


def test_secrets_must_not_be_in_preflight_claim_job_or_cleanup():
    for name in ("preflight", "claim", "collect", "result"):
        bad = candidate()
        bad["jobs"][name]["env"] = {"TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
        refused(bad)
    bad = candidate()
    bad["jobs"]["collect"]["steps"][3]["env"] = {
        "LEAK": "${{ secrets.HOBEN_USER_GUID }}"
    }
    refused(bad)


@pytest.mark.parametrize(
    "suffix",
    [
        "&page=2",
        "&ref=main",
        "#fragment",
        "?",
        "&redirect=https://example.org",
    ],
)
def test_source_request_must_be_exactly_pinned(suffix):
    src = mock_source()
    src["request"] += suffix
    refused(src, expected_commit_sha=M)


def test_source_sha_content_encoding_status_size_and_unknown_fields():
    variants = []
    bad = mock_source()
    bad["items"]["sha"] = "b" * 40
    variants.append(bad)
    bad = mock_source()
    bad["items"]["encoding"] = "utf-16"
    variants.append(bad)
    bad = mock_source()
    bad["items"]["content"] += "!"
    variants.append(bad)
    bad = mock_source()
    bad["items"]["path"] = "README.md"
    variants.append(bad)
    bad = mock_source()
    bad["items"]["content"] = "YWJj\nZGVm"
    variants.append(bad)
    bad = mock_source()
    bad["status"] = 403
    variants.append(bad)
    bad = mock_source()
    bad["next"] = "/next"
    variants.append(bad)
    bad = mock_source()
    bad["headers"] = {"Authorization": "VERY_PRIVATE_TOKEN"}
    variants.append(bad)
    for variant in variants:
        refused(variant, expected_commit_sha=M)
    refused(mock_source(), expected_commit_sha="b" * 40)
    refused(mock_source())
    refused(mock_source(), expected_commit_sha="main")


@pytest.mark.parametrize(
    "text",
    [
        "on: 1\non: 2\n",
        "a: &alias 1\nb: *alias\n",
        "a: !!python/object:os.system 1",
        "a: !unknown 1",
        "a: [unfinished",
        "a: 1\n---\na: 2",
        "a: {<<: value}",
        "a: [yes, off]",
        "x: " + ("X" * 50000),
    ],
)
def test_yamls_with_duplicate_anchor_tag_malformed_or_oversized_refuse(text):
    refused(text)


def test_non_json_ast_and_cycles_refuse_without_exceptions_or_echo():
    bad = candidate()
    bad["unknown"] = object()
    refused(bad)
    bad = candidate()
    bad["jobs"]["collect"]["steps"].append(bad)
    refused(bad)
    refused({"body": "VERY_PRIVATE_TOKEN", "jobs": {}})


def test_node_adversarial_tests_are_part_of_python_suite():
    p = subprocess.run(
        ["node", "--test", "tests/js/ha-live-workflow-static-gate-offline.test.cjs"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert "VERY_PRIVATE_TOKEN" not in p.stdout + p.stderr


def test_source_stays_isolated_from_network_secret_and_workflow_entrypoints():
    source = (ROOT_DIR / "scripts/ha_live_workflow_static_gate_offline.py").read_text()
    assert "requests." not in source
    assert "urlopen(" not in source
    assert "subprocess." not in source
    assert "os.environ" not in source
    assert "__main__" not in source
    assert "workflow_dispatch" in source  # AST guard, not a dispatch call
