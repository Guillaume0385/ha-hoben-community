"""Cross-language closed proof contract; synthetic data, no GitHub/Hoben calls."""

import copy
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.hoben.session_observation import (
    SessionLossKind,
    SessionObservation,
)
from scripts.ha_session_proof import (
    LIMITS,
    REFRESH_AT_MS,
    InvalidProof,
    build_report,
    criteria,
    encode_report,
    outcome,
    parse_report,
    project_observation,
    validate_report,
)

ROOT = Path(__file__).resolve().parents[1]


def sample(ordinal, observation, decoded=True):
    return {
        "ordinal": ordinal,
        "decoded": decoded,
        "observation": project_observation(observation),
    }


def proof(*, recovered=False, kind=SessionLossKind.CLOSE_CLIENT):
    first = SessionObservation(
        attempts=1, generation=1, read_generation=1, read_sequence=1
    )
    samples = [sample(1, first), sample(2, replace(first, read_sequence=2))]
    current = first
    if recovered:
        loss = replace(
            first,
            read_sequence=2,
            loss_generation=1,
            loss_kind=kind,
            close_client_subcode=3 if kind is SessionLossKind.CLOSE_CLIENT else None,
            cleaned_generation=1,
        )
        samples.append(sample(3, loss, False))
        current = replace(loss, attempts=2, generation=2, read_generation=2)
        for ordinal in range(4, 7):
            samples.append(sample(ordinal, replace(current, read_sequence=ordinal - 3)))
    else:
        for ordinal in range(3, 7):
            samples.append(sample(ordinal, replace(first, read_sequence=ordinal)))
    return build_report(
        provenance={
            "merge_sha": "a" * 40,
            "pr_number": 1,
            "run_id": 2,
            "run_attempt": 1,
        },
        samples=samples,
        cleanup={
            "completed": True,
            "observation": project_observation(
                replace(
                    current,
                    read_sequence=3 if recovered else 6,
                    cleaned_generation=current.generation,
                    stopped=True,
                )
            ),
        },
        elapsed_ms=250000,
        completed=True,
    )


def node_accepts(text):
    result = subprocess.run(
        [
            "node",
            "-e",
            "const p=require('./scripts/ha-session-proof.cjs');"
            "let s='';process.stdin.on('data',x=>s+=x);"
            "process.stdin.on('end',()=>{try{p.parseReport(s);process.stdout.write('ok')}"
            "catch(e){process.stdout.write(e.message);process.exitCode=1}});",
        ],
        cwd=ROOT,
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.stderr == ""
    assert result.stdout in {"ok", "invalid offline HA session proof"}
    return result.returncode == 0


@pytest.mark.parametrize(
    "recovered,kind",
    [
        (False, None),
        (True, SessionLossKind.TRANSPORT),
        (True, SessionLossKind.CLOSE_CLIENT),
    ],
)
def test_independent_validator_accepts_bounded_synthetic_evidence(recovered, kind):
    report = proof(recovered=recovered, kind=kind)
    text = encode_report(report)
    assert parse_report(text) == report and node_accepts(text)
    assert report["criteria"]["reconnection"] == (
        "SUCCESS" if recovered else "INCONCLUSIVE"
    )
    assert "register" not in text and "guid" not in text and "payload" not in text


INVALID = [
    ((), "secret", "PRIVATE_PAYLOAD"),
    ((), "schema", True),
    ((), "outcome", "FAILURE"),
    ((), "execution", "live"),
    ((), "boundary_proven", True),
    ((), "system_enforcement", "SUCCESS"),
    ((), "elapsed_ms", -1),
    ((), "elapsed_ms", 300001),
    ((), "elapsed_ms", True),
    (("provenance",), "merge_sha", "PRIVATE_PAYLOAD"),
    (("provenance",), "pr_number", True),
    (("provenance",), "run_attempt", 2),
    (("provenance",), "run_id", 2**53),
    (("limits",), "rx_bytes", 1048577),
    (("limits",), "refreshes", True),
    (("limits",), "memory_bytes", 2**31),
    (("limits",), "process_ms", 360001),
    (("limits",), "useful_ms", 300001),
    (("limits",), "retention_days", 8),
    (("samples", 0), "ordinal", True),
    (("samples", 0), "decoded", "yes"),
    (("samples", 0, "observation"), "guid", "PRIVATE_PAYLOAD"),
    (("samples", 0, "observation"), "attempts", 3),
    (("samples", 0, "observation"), "generation", True),
    (("samples", 0, "observation"), "read_sequence", 0),
    (("samples", 0, "observation"), "read_generation", 2),
    (("samples", 1, "observation"), "read_sequence", 1),
    (("samples", 2, "observation"), "loss_kind", "tls_eof"),
    (("samples", 2, "observation"), "close_client_subcode", 256),
    (("samples", 2, "observation"), "close_client_subcode", True),
    (("samples", 3, "observation"), "cleaned_generation", 3),
    (("samples", 3, "observation"), "cleanup_failed", True),
    (("samples", 3, "observation"), "stopped", True),
    (("cleanup", "observation"), "stopped", False),
    (("cleanup", "observation"), "cleanup_failed", True),
    (("cleanup", "observation"), "cleaned_generation", 1),
    (("criteria",), "reconnection", "INCONCLUSIVE"),
    (("criteria",), "cleanup", "NOT RUN"),
]


@pytest.mark.parametrize("path,key,value", INVALID)
def test_python_and_node_reject_malformed_or_forged_proof(path, key, value):
    report = proof(recovered=True)
    target = report
    for part in path:
        target = target[part]
    target[key] = value
    text = json.dumps(report, separators=(",", ":"))
    with pytest.raises(InvalidProof, match="^invalid offline HA session proof$"):
        parse_report(text)
    assert not node_accepts(text)


def test_opening_alone_stale_read_and_unconfirmed_cleanup_never_prove_recovery():
    report = proof(recovered=True)
    for s in report["samples"][3:]:
        s["decoded"] = False
        s["observation"]["read_generation"] = None
        s["observation"]["read_sequence"] = None
    report["criteria"] = criteria(report)
    report["outcome"] = outcome(report["criteria"])
    assert report["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert node_accepts(encode_report(report))
    report = proof(recovered=True)
    for s in report["samples"][2:]:
        s["observation"]["cleaned_generation"] = None
    report["criteria"] = criteria(report)
    report["outcome"] = outcome(report["criteria"])
    assert report["criteria"]["reconnection"] == "INCONCLUSIVE"
    assert node_accepts(encode_report(report))


def test_not_run_and_partial_failure_are_separate_from_recovery_success():
    report = proof()
    report["samples"] = []
    report["completed"] = False
    report["criteria"] = criteria(report)
    report["outcome"] = outcome(report["criteria"])
    assert (
        report["criteria"]["collection"]
        == report["criteria"]["reconnection"]
        == "NOT RUN"
    )
    assert node_accepts(encode_report(report))
    report = proof(recovered=True)
    report["completed"] = False
    report["criteria"] = criteria(report)
    report["outcome"] = outcome(report["criteria"])
    assert report["criteria"]["collection"] == "FAILURE"
    assert report["criteria"]["reconnection"] == "SUCCESS"
    assert node_accepts(encode_report(report))


@pytest.mark.parametrize(
    "malformed",
    [
        "{}",
        "[]",
        "null",
        "{",
        "PRIVATE_PAYLOAD",
        " " * 8193,
    ],
)
def test_input_limits_and_errors_do_not_echo_rejected_content(malformed):
    with pytest.raises(InvalidProof, match="^invalid offline HA session proof$"):
        parse_report(malformed)
    assert not node_accepts(malformed)


def test_canonical_encoding_rejects_duplicate_keys_and_noncanonical_numbers():
    text = encode_report(proof())
    variants = [
        " " + text,
        text.replace('"schema":1', '"schema":1,"schema":1'),
        text.replace('"schema":1', '"schema":1.0'),
    ]
    for variant in variants:
        with pytest.raises(InvalidProof):
            parse_report(variant)
        assert not node_accepts(variant)


@pytest.mark.parametrize("subcode", [0, 255])
def test_unknown_numeric_close_subcodes_remain_payload_free(subcode):
    report = proof(recovered=True)
    for sample in report["samples"][2:]:
        sample["observation"]["close_client_subcode"] = subcode
    report["cleanup"]["observation"]["close_client_subcode"] = subcode
    assert node_accepts(encode_report(report))


@pytest.mark.parametrize("field", ["cleanup_failed", "stopped"])
def test_terminal_evidence_cannot_be_erased_in_later_samples(field):
    report = proof(recovered=True)
    report["samples"][2]["observation"][field] = True
    report["criteria"] = criteria(report)
    report["outcome"] = outcome(report["criteria"])
    text = json.dumps(report, separators=(",", ":"))
    with pytest.raises(InvalidProof):
        parse_report(text)
    assert not node_accepts(text)


def test_six_report_slots_and_budget_reserve_are_bounded():
    report = proof()
    oversized = copy.deepcopy(report)
    oversized["samples"].append(copy.deepcopy(oversized["samples"][-1]))
    with pytest.raises(InvalidProof):
        validate_report(oversized)
    assert not node_accepts(json.dumps(oversized, separators=(",", ":")))
    assert len(REFRESH_AT_MS) == LIMITS["refreshes"] == 6
    assert sorted(set(REFRESH_AT_MS)) == list(REFRESH_AT_MS)
    # Two connects/handshakes/closes, one retry and six read deadlines fit.
    # Late recovery is truncated by the absolute deadline, never extended.
    worst_io = (
        2
        * (LIMITS["connect_ms"] + LIMITS["handshake_ms"] + LIMITS["transport_close_ms"])
        + LIMITS["retry_ms"]
        + 6 * LIMITS["read_ms"]
    )
    assert worst_io < LIMITS["useful_ms"]
    assert REFRESH_AT_MS[-1] + LIMITS["read_ms"] < LIMITS["useful_ms"]
    assert LIMITS["useful_ms"] + LIMITS["cleanup_ms"] + 1000 < LIMITS["process_ms"]
