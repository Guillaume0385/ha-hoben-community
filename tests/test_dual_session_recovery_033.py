"""Independent invented receipts: recovery cannot claim continuity or hide loss."""

import base64
import copy
import json

import pytest

from scripts.campaign_runtime_contract import validate_report
from scripts.ha_dual_evidence import empty_stats, owner_record, phase
from tests.test_campaign_publication import node
from tests.test_campaign_runtime import node_accepts
from tests.test_dual_session_contract import proof, report


def recovered_proof(kind="timeout"):
    d = proof()
    e = d["evidence"]
    incident_at = 390000 if kind == "timeout" else 361000
    opened = incident_at + 60000
    e.update(end_ms=780000)
    e["b"]["closed_ms"] = 362000
    e["resources"]["a"].update(opens=2, close_calls=2)
    e["owners"] = [
        owner_record(role, generation)
        | dict(
            opens=1,
            accepted=True,
            close_calls=1,
            close_completed=True,
            cleanup=True,
            open_ms=open_at,
            accepted_ms=accepted,
            closed_ms=closed,
            cleaned_ms=closed,
        )
        for role, generation, open_at, accepted, closed in (
            ("a", 1, None, 0, incident_at),
            ("b", 1, 180000, 180000, 362000),
            ("a", 2, opened, opened, 780000),
        )
    ]
    error = {"timeout": "timeout", "eof": "transport", "close_client": "closed"}[kind]
    e["incident"] = dict(
        role="a",
        generation=1,
        at_ms=incident_at,
        category=error,
        phase="request_correlation"
        if kind == "timeout"
        else "tls_read"
        if kind == "eof"
        else "post_open",
        subcode=3 if kind == "close_client" else None,
        kind=kind,
        read_ms=360000,
        deadline_ms=390000 if kind == "timeout" else None,
        frame=None,
        late_frame=None,
    )
    if kind == "close_client":
        e["incident"]["frame"] = dict(
            event="error",
            generation=1,
            message_type="close_client",
            expected_total_bytes=2,
            received_bytes=2,
            length_scope="post_open_hypothesis",
            provenance="fixed_contract",
            phase="post_open",
            category="closed",
            status="complete",
            at_ms=incident_at,
        )
    e["reads"] = []
    last_success = None
    for ordinal in range(14):
        at = ordinal * 60000
        decoded = ordinal not in {6, 7}
        end = incident_at if ordinal == 6 else at
        if decoded:
            last_success = end
        e["reads"].append(
            dict(
                scheduled_ms=at,
                at_ms=at,
                end_ms=end,
                decoded=decoded,
                available=decoded or kind == "timeout",
                state="connected" if decoded else "reconnecting",
                generation=1 if ordinal < 8 else 2,
                sequence=ordinal + 1
                if ordinal < 6
                else 6
                if ordinal < 8
                else ordinal - 7,
                error="none" if decoded else error,
                attempted=ordinal != 7,
                held=not decoded and kind == "timeout",
                last_success_ms=last_success,
                age_ms=end - last_success,
            )
        )
    for p in e["phases"]:
        p.update(a=empty_stats(), b=empty_stats())
    for s in e["reads"]:
        stat = e["phases"][phase(s["at_ms"])]["a"]
        stat["requests"] += s["attempted"]
        stat["types"][4] += s["decoded"]
    e["phases"][0]["a"]["types"][1] = 1
    e["phases"][2]["a"]["types"][1] = 1
    e["phases"][2]["a"]["eof"] = int(kind == "eof")
    e["phases"][2]["a"]["types"][3] = int(kind == "close_client")
    e["phases"][1]["b"]["requests"] = 1
    e["phases"][1]["b"]["types"][1] = 1
    e["phases"][1]["b"]["types"][4] = 1
    e["transitions"] = sorted(
        [
            dict(role=role, at_ms=at, state=state)
            for role, at, state in (
                ("a", 0, "connected"),
                ("b", 180000, "connected"),
                ("a", incident_at, "reconnecting"),
                ("b", 362000, "disconnected"),
                ("a", opened, "connected"),
                ("a", 780000, "disconnected"),
            )
        ],
        key=lambda x: x["at_ms"],
    )
    d["supervisor"]["elapsed_ms"] = 782000
    return d


@pytest.mark.parametrize("kind", ["timeout", "eof", "close_client"])
def test_python_node_recovery_is_success_with_failed_acquisition_visible(kind):
    r = report(recovered_proof(kind))
    assert validate_report(r) and node_accepts(r)
    stage = r["stages"][0]
    assert stage["status"] == "SUCCESS"
    assert stage["metrics"]["recovered"] and not stage["metrics"]["continuous"]
    assert stage["metrics"]["reads_ok"] < stage["metrics"]["reads"]
    assert stage["detail"]["evidence"]["incident"]["kind"] == kind


@pytest.mark.parametrize(
    "path,value",
    [
        (("incident", "at_ms"), 389999),
        (("incident", "deadline_ms"), None),
        (("incident", "role"), "b"),
        (("incident", "kind"), "unexpected"),
        (("incident", "subcode"), 3),
        (("owners", 0, "cleaned_ms"), 390001),
        (("owners", 2, "open_ms"), 449999),
        (("owners", 2, "accepted_ms"), None),
        (("owners", 0, "cleanup"), False),
        (("owners", 0, "closed_ms"), None),
        (("owners", 2, "cleaned_ms"), 800000),
        (("reads", 6, "decoded"), True),
        (("reads", 6, "attempted"), False),
        (("reads", 7, "attempted"), True),
        (("reads", 6, "last_success_ms"), 390000),
        (("reads", 6, "held"), False),
        (("reads", 8, "generation"), 1),
        (("reads", 8, "sequence"), 2),
        (("reads", 8, "age_ms"), False),
        (("end_ms",), 779999),
        (("b", "closed_ms"), 360000),
        (("phases", 2, "b", "eof"), 1),
        (("phases", 2, "a", "types", 3), 1),
        (("transitions",), []),
        (("raw",), "PRIVATE_PAYLOAD"),
    ],
)
def test_both_validators_refuse_invented_recovery_or_hidden_failure(path, value):
    r = report(recovered_proof())
    e = r["stages"][0]["detail"]["evidence"]
    for key in path[:-1]:
        e = e[key]
    e[path[-1]] = value
    assert not node_accepts(r)
    with pytest.raises((ValueError, TypeError)):
        validate_report(r)


@pytest.mark.parametrize("field,value", [("frame", None), ("subcode", None)])
def test_closeclient_needs_complete_original_frame_evidence(field, value):
    r = report(recovered_proof("close_client"))
    r["stages"][0]["detail"]["evidence"]["incident"][field] = value
    assert not node_accepts(r)
    with pytest.raises((ValueError, TypeError)):
        validate_report(r)


def failed_cleanup_proof():
    d = recovered_proof()
    e = d["evidence"]
    e.update(completed=False, error="timeout")
    e.update(a_end_active=False, end_ms=390000)
    e["reads"] = e["reads"][:7]
    e["owners"] = e["owners"][:2]
    e["owners"][0].update(
        cleanup=False, close_completed=False, closed_ms=None, cleaned_ms=None
    )
    e["resources"]["a"].update(
        opens=1, close_calls=1, cleanup=False, close_completed=False
    )
    e["phases"][2]["a"] = empty_stats()
    e["phases"][2]["a"]["requests"] = 1
    e["transitions"] = [t for t in e["transitions"] if t["at_ms"] <= 390000]
    d["supervisor"]["elapsed_ms"] = 392000
    e["failure"] = {
        k: e["incident"][k] for k in ("role", "at_ms", "category", "phase", "subcode")
    }
    e["terminal"] = dict(
        role="a", at_ms=390001, category="transport", phase="cleanup", subcode=None
    )
    e["cleanup_errors"] = [
        dict(role="a", generation=1, at_ms=390001, category="transport")
    ]
    return d


def test_original_timeout_and_secondary_cleanup_failure_are_both_public():
    d = failed_cleanup_proof()
    e = d["evidence"]
    r = report(d)
    assert validate_report(r) and node_accepts(r)
    assert r["stages"][0]["status"] == "FAILURE"
    assert (
        r["stages"][0]["detail"]["evidence"]["failure"]["phase"]
        == "request_correlation"
    )
    changed = copy.deepcopy(r)
    changed["stages"][0]["detail"]["evidence"]["failure"] = e["terminal"]
    assert not node_accepts(changed)
    with pytest.raises(ValueError):
        validate_report(changed)


def late_proof():
    d = recovered_proof()
    e = d["evidence"]
    e["incident"]["late_frame"] = dict(
        event="header",
        generation=1,
        message_type="data_response_client",
        expected_total_bytes=50,
        received_bytes=7,
        length_scope="frame",
        provenance="validated_header",
        phase="frame_boundary",
        category="none",
        status="partial",
        at_ms=390000,
    )
    e["phases"][2]["a"]["types"][4] += 1
    return d


def test_old_late_header_never_increments_decoded_acquisitions():
    r = report(late_proof())
    assert validate_report(r) and node_accepts(r)
    assert r["stages"][0]["status"] == "SUCCESS"
    assert r["stages"][0]["metrics"]["reads_ok"] == 13
    assert not r["stages"][0]["detail"]["evidence"]["reads"][6]["decoded"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", 2),
        ("at_ms", 389999),
        ("at_ms", 390001),
        ("expected_total_bytes", "unknown"),
        ("category", "protocol"),
        ("message_type", "unknown"),
        ("raw", "PRIVATE_PAYLOAD"),
    ],
)
def test_late_header_proof_cannot_hide_new_generation_or_unknown_input(field, value):
    r = report(late_proof())
    r["stages"][0]["detail"]["evidence"]["incident"]["late_frame"][field] = value
    assert not node_accepts(r)
    with pytest.raises((ValueError, TypeError)):
        validate_report(r)


def test_schema_one_historical_continuity_remains_readable():
    d = proof()
    e = d["evidence"]
    e["schema"] = 1
    for k in ("owners", "incident", "terminal", "cleanup_errors"):
        del e[k]
    for s in e["reads"]:
        for k in ("attempted", "held", "last_success_ms", "age_ms"):
            del s[k]
    r = report(d)
    assert validate_report(r) and node_accepts(r)
    assert r["stages"][0]["status"] == "SUCCESS"


@pytest.mark.parametrize("kind", ["eof", "close_client"])
def test_idle_loss_keeps_polls_distinct_from_emitted_requests(kind):
    d = recovered_proof(kind)
    e = d["evidence"]
    e["incident"].update(at_ms=359000, read_ms=None)
    if e["incident"]["frame"] is not None:
        e["incident"]["frame"]["at_ms"] = 359000
    e["owners"][0].update(closed_ms=359000, cleaned_ms=359000)
    e["owners"][2].update(
        open_ms=419000, accepted_ms=419000, closed_ms=720000, cleaned_ms=720000
    )
    e["reads"] = e["reads"][:13]
    e["reads"][6].update(
        attempted=False, end_ms=360000, error="transport", age_ms=60000
    )
    for i in range(7, 13):
        at = i * 60000
        e["reads"][i].update(
            decoded=True,
            attempted=True,
            available=True,
            state="connected",
            generation=2,
            sequence=i - 6,
            error="none",
            last_success_ms=at,
            age_ms=0,
        )
    for p in e["phases"]:
        p["a"] = empty_stats()
    for s in e["reads"]:
        p = e["phases"][phase(s["at_ms"])]["a"]
        p["requests"] += s["attempted"]
        p["types"][4] += s["decoded"]
    e["phases"][0]["a"]["types"][1] = 1
    e["phases"][2]["a"]["types"][1] = 1
    e["phases"][1]["a"]["eof"] = int(kind == "eof")
    e["phases"][1]["a"]["types"][3] = int(kind == "close_client")
    for t in e["transitions"]:
        if t["role"] == "a" and t["state"] == "reconnecting":
            t["at_ms"] = 359000
        elif t["role"] == "a" and t["state"] == "connected" and t["at_ms"]:
            t["at_ms"] = 419000
        elif t["role"] == "a" and t["state"] == "disconnected":
            t["at_ms"] = 720000
    e["transitions"].sort(key=lambda t: t["at_ms"])
    e["end_ms"] = 720000
    d["supervisor"]["elapsed_ms"] = 722000
    r = report(d)
    assert validate_report(r) and node_accepts(r)
    m = r["stages"][0]["metrics"]
    assert m["recovered"] and not m["continuous"] and m["reads"] == m["reads_ok"] == 13
    assert r["stages"][0]["status"] == "SUCCESS"


@pytest.mark.parametrize("failed", [False, True])
def test_publication_shows_incident_and_cleanup_without_false_continuity(
    tmp_path, failed
):
    r = report(failed_cleanup_proof() if failed else recovered_proof())
    encoded = base64.b64encode(json.dumps(r, separators=(",", ":")).encode()).decode()
    result = node(
        "publish",
        tmp_path,
        "ha",
        "dual-session-observation",
        encoded=encoded,
        collect="success",
    )
    assert (result.returncode == 0) == (not failed)
    summary = (tmp_path / "summary").read_text()
    assert "Premier incident : a / génération 1 / timeout" in summary
    if failed:
        assert "Échec de nettoyage" in summary and "request_correlation" in summary
        assert "non attesté" in summary
    else:
        assert "récupération prouvée" in summary and "demandes échouées 1" in summary
    assert "PRIVATE_PAYLOAD" not in summary


def test_last_poll_cannot_be_omitted_while_claiming_later_stability():
    r = report(recovered_proof())
    stage = r["stages"][0]
    e = stage["detail"]["evidence"]
    e["reads"].pop()
    e["phases"][2]["a"]["requests"] -= 1
    e["phases"][2]["a"]["types"][4] -= 1
    stage["metrics"]["reads"] -= 1
    stage["metrics"]["reads_ok"] -= 1
    assert not node_accepts(r)
    with pytest.raises(ValueError):
        validate_report(r)
