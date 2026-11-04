"""Invented scalar receipts: independent Python/Node HA-F1 acceptance/refusal."""

import base64
import copy
import json

import pytest

from scripts.campaign_runtime_contract import stage, validate_report
from scripts.ha_campaign_evidence import project
from scripts.ha_session_supervisor import SourceBundle
from tests.test_campaign_publication import node
from tests.test_campaign_runtime import envelope, ha_detail, node_accepts
from tests.test_dual_session_contract import proof as dual_proof
from tests.test_dual_session_recovery_033 import recovered_proof


def diagnostic(detail, dual=False):
    """Wholly invented fixtures, never a production reconstruction or attestation."""
    e = detail["evidence"]
    end = detail["supervisor"]["elapsed_ms"]
    if dual:
        offset = e["t0_ms"]
        owners = []
        for o in e["owners"]:
            reads = [
                s
                for s in e["reads"]
                if s["decoded"] and s["generation"] == o["generation"]
            ]
            seq, at = (
                (reads[-1]["sequence"], reads[-1]["end_ms"])
                if o["role"] == "a"
                else (1, e["b"]["read_ms"])
            )
            close = offset + o["closed_ms"]
            owners.append(
                dict(
                    role=o["role"],
                    generation=o["generation"],
                    accepted=True,
                    accepted_generation=o["generation"],
                    close_client_subcode=(
                        e["incident"]["subcode"]
                        if e["incident"]
                        and e["incident"]["role"] == o["role"]
                        and e["incident"]["generation"] == o["generation"]
                        else None
                    ),
                    close=[close, close, close, offset + o["cleaned_ms"]],
                    stage="reaped",
                    pending=0,
                    last_read=[seq, offset + at, end - offset - at],
                )
            )
        incident = e["incident"]
        first = (
            None
            if incident is None
            else [
                incident["role"],
                incident["generation"],
                offset + incident["at_ms"],
                incident["kind"],
                incident["phase"],
                "transport_read" if incident["kind"] == "eof" else "session",
                incident["subcode"],
            ]
        )
    else:
        last = e["samples"][-1]
        owners = [
            dict(
                role="a",
                generation=1,
                accepted=True,
                accepted_generation=1,
                close_client_subcode=None,
                close=[7000] * 4,
                stage="reaped",
                pending=0,
                last_read=[
                    last["observation"]["read_sequence"],
                    last["at_ms"],
                    end - last["at_ms"],
                ],
            )
        ]
        first = None
    e.update(
        diagnostic_schema=1,
        diagnostic=dict(
            end_ms=end,
            first=first,
            terminal=None,
            cleanup=None,
            owners=owners,
            invalid=False,
        ),
    )
    return detail


def proof(kind="solo"):
    return (
        diagnostic(ha_detail("session-reuse"))
        if kind == "solo"
        else diagnostic(
            dual_proof() if kind == "dual" else recovered_proof(kind), dual=True
        )
    )


def report(detail, kind="solo"):
    scenario = "session-reuse" if kind == "solo" else "dual-session-observation"
    return envelope(
        "ha",
        scenario,
        [
            stage(
                "ha",
                scenario,
                started=True,
                reason="observed",
                elapsed_ms=detail["supervisor"]["elapsed_ms"],
                metrics=project(scenario, detail),
                detail=detail,
            )
        ],
    )


@pytest.mark.parametrize("kind", ["solo", "dual", "timeout", "eof", "close_client"])
def test_f1_never_changes_legacy_metrics_or_scenario_verdict(kind):
    d = proof(kind)
    r = report(d, kind)
    assert validate_report(r) and node_accepts(r)
    legacy = copy.deepcopy(d)
    del legacy["evidence"]["diagnostic_schema"], legacy["evidence"]["diagnostic"]
    old = report(legacy, kind)
    assert r["stages"][0]["metrics"] == old["stages"][0]["metrics"]
    assert r["stages"][0]["status"] == old["stages"][0]["status"]
    assert len(json.dumps(d, separators=(",", ":")).encode()) <= 8192


def refuse(r):
    with pytest.raises(ValueError):
        validate_report(r)
    assert not node_accepts(r)


@pytest.mark.parametrize("missing", ["diagnostic_schema", "diagnostic"])
def test_versioned_pair_cannot_be_partially_omitted(missing):
    r = report(proof())
    del r["stages"][0]["detail"]["evidence"][missing]
    refuse(r)


@pytest.mark.parametrize(
    "path,value",
    [
        (("diagnostic_schema",), True),
        (("diagnostic_schema",), 2),
        (("diagnostic", "invalid"), True),
        (("diagnostic", "raw"), "PRIVATE_PAYLOAD"),
        (("diagnostic", "end_ms"), 1000000),
        (("diagnostic", "owners", 0, "raw"), "PRIVATE_PAYLOAD"),
        (("diagnostic", "owners", 0, "generation"), True),
        (("diagnostic", "owners", 0, "role"), "b"),
        (("diagnostic", "owners", 0, "pending"), 1),
        (("diagnostic", "owners", 0, "pending"), True),
        (("diagnostic", "owners", 0, "pending"), 128),
        (("diagnostic", "owners", 0, "pending"), None),
        (("diagnostic", "owners", 0, "close", 0), 7500),
        (("diagnostic", "owners", 0, "close", 1), None),
        (("diagnostic", "owners", 0, "close", 2), True),
        (("diagnostic", "owners", 0, "stage"), "active"),
        (("diagnostic", "owners", 0, "accepted"), False),
        (("diagnostic", "owners", 0, "accepted_generation"), True),
        (("diagnostic", "owners", 0, "accepted_generation"), None),
        (("diagnostic", "owners", 0, "close_client_subcode"), True),
        (("diagnostic", "owners", 0, "close_client_subcode"), "PRIVATE_PAYLOAD"),
        (("diagnostic", "owners", 0, "last_read"), None),
        (("diagnostic", "owners", 0, "last_read", 0), 6),
        (("diagnostic", "owners", 0, "last_read", 1), 8001),
        (("diagnostic", "owners", 0, "last_read", 2), 0),
    ],
)
def test_closed_shape_order_resources_and_read_age_reject_tampering(path, value):
    r = report(proof())
    target = r["stages"][0]["detail"]["evidence"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    refuse(r)


@pytest.mark.parametrize(
    "index,value",
    [
        (0, "b"),
        (1, True),
        (1, 2),
        (2, 799999),
        (3, "PRIVATE_PAYLOAD"),
        (3, "close_client"),
        (3, "eof"),
        (3, "authentication"),
        (4, "PRIVATE_PAYLOAD"),
        (5, "PRIVATE_PAYLOAD"),
        (6, 3),
    ],
)
def test_first_incident_never_becomes_an_invented_close_eof_or_other_generation(
    index, value
):
    r = report(proof("timeout"), "timeout")
    r["stages"][0]["detail"]["evidence"]["diagnostic"]["first"][index] = value
    refuse(r)


def test_existing_incident_cannot_be_erased_in_current_version():
    r = report(proof("timeout"), "timeout")
    r["stages"][0]["detail"]["evidence"]["diagnostic"]["first"] = None
    refuse(r)


def test_metadata_tap_sanitizes_rejected_scalars_without_logging_them():
    from scripts.ha_incident_observer import Recorder

    d = Recorder(lambda: 0)
    d.event(
        None,
        "PRIVATE_PAYLOAD",
        "PRIVATE_PAYLOAD",
        "PRIVATE_PAYLOAD",
        b"PRIVATE_PAYLOAD",
    )
    value = d.snapshot()
    assert value["invalid"]
    assert "PRIVATE_PAYLOAD" not in json.dumps(value)


@pytest.mark.parametrize(
    "missing", ["end_ms", "first", "terminal", "cleanup", "owners", "invalid"]
)
def test_every_f1_slot_is_required_even_when_none(missing):
    r = report(proof())
    del r["stages"][0]["detail"]["evidence"]["diagnostic"][missing]
    refuse(r)


@pytest.mark.parametrize(
    "missing",
    [
        "role",
        "generation",
        "accepted",
        "accepted_generation",
        "close_client_subcode",
        "close",
        "stage",
        "pending",
        "last_read",
    ],
)
def test_owner_projection_never_defaults_missing_proof(missing):
    r = report(proof())
    del r["stages"][0]["detail"]["evidence"]["diagnostic"]["owners"][0][missing]
    refuse(r)


def test_forged_close_subcode_without_corresponding_owner_evidence_is_rejected():
    r = report(proof("timeout"), "timeout")
    e = r["stages"][0]["detail"]["evidence"]
    event = e["diagnostic"]["first"]
    event[3], event[4], event[6] = "close_client", "post_open", 3
    refuse(r)


def test_completed_close_cannot_be_relabelled_as_failed_cleanup_or_unattested():
    r = report(proof())
    d = r["stages"][0]["detail"]["evidence"]["diagnostic"]
    event = ["a", 1, 7000, "transport", "cleanup", "transport_close", None]
    d["first"], d["cleanup"] = event.copy(), event.copy()
    refuse(r)
    r = report(proof())
    row = r["stages"][0]["detail"]["evidence"]["diagnostic"]["owners"][0]
    row["close"][3], row["stage"] = None, "tls_closed"
    refuse(r)


def test_publication_renders_only_validated_first_terminal_cleanup_and_age(tmp_path):
    r = report(proof())
    encoded = base64.b64encode(json.dumps(r, separators=(",", ":")).encode()).decode()
    assert (
        node("publish", tmp_path, "ha", "session-reuse", encoded=encoded).returncode
        == 0
    )
    text = (tmp_path / "summary").read_text()
    for value in (
        "Premier incident",
        "Erreur terminale",
        "Erreur de nettoyage",
        "fermeture demandée",
        "cleanup attesté",
        "dernière lecture",
        "âge 6000 ms",
    ):
        assert value in text
    assert "PRIVATE_PAYLOAD" not in text


def test_f1_helpers_are_only_in_the_existing_readonly_campaign_bundle():
    for campaign in (False, True):
        bundle = SourceBundle(live=True, campaign=campaign)
        try:
            for name in ("ha_incident_observer.py", "ha_incident_evidence.py"):
                path = bundle.folder / "scripts" / name
                assert path.exists() is campaign
                if campaign:
                    assert path.stat().st_mode & 0o777 == 0o444
        finally:
            bundle.close()
