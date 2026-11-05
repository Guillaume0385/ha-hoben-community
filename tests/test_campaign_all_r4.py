"""R4 exercises the real parent and independent Node contracts, without I/O."""

import copy

import pytest

from scripts.campaign_runtime_contract import CHOICES, stage, validate_report
from scripts.ha_campaign_evidence import project
from tests.test_campaign_runtime import envelope, ha_detail, node_accepts, observed
from tests.test_campaign_verdicts_continue import campaign
from tests.test_live_recovery_r2c import nominal_f1_detail

NAMES = CHOICES["ha"][:-1]
UNSAFE = (
    ("cleanup_first", "cleanup_failed"),
    ("cleanup_event", "cleanup_failed"),
    ("cancel_first", "cancelled"),
    ("cancel_terminal", "cancelled"),
    ("auth", "identity_refused"),
    ("authorization", "identity_refused"),
    ("internal", "worker_failure"),
    ("pending_unaccepted", "cleanup_failed"),
    ("unclosed_unaccepted", "cleanup_failed"),
)


def value(scenario, detail):
    return stage(
        "ha",
        scenario,
        started=True,
        reason="observed",
        elapsed_ms=detail["supervisor"]["elapsed_ms"],
        metrics=project(scenario, detail),
        detail=detail,
    )


def unsafe_value(kind):
    d = nominal_f1_detail()
    e, f = d["evidence"], d["evidence"]["diagnostic"]
    category = {
        "cleanup_first": "cleanup_failed",
        "cancel_first": "cancelled",
        "auth": "authentication",
    }.get(kind, kind)
    if kind in {"cleanup_event", "cancel_terminal"}:
        f["first"] = ["a", 1, 0, "timeout", "tls_read", "transport_read", None]
        f["cleanup" if kind == "cleanup_event" else "terminal"] = [
            "a",
            1,
            300000,
            "cleanup_failed" if kind == "cleanup_event" else "cancelled",
            "cleanup",
            "observer",
            None,
        ]
    elif kind in {"pending_unaccepted", "unclosed_unaccepted"}:
        for s in e["samples"]:
            s["decoded"] = False
        for o in [s["observation"] for s in e["samples"]] + [
            e["window"]["observation"],
            e["cleanup"]["observation"],
        ]:
            o.update(
                generation=None,
                read_generation=None,
                read_sequence=None,
                cleaned_generation=None,
            )
        e["window"]["active"] = False
        f["first"] = ["a", 1, 0, "timeout", "opening", "transport_connect", None]
        f["owners"][0].update(
            accepted=False,
            accepted_generation=None,
            last_read=None,
            close=[0, 0, None, None],
            stage="tls_close",
            pending=1 if kind == "pending_unaccepted" else 0,
        )
    else:
        f["first"] = ["a", 1, 0, category, "unknown", "observer", None]
    return value("hoben-live", d)


@pytest.mark.parametrize("kind,reason", UNSAFE)
def test_all_never_starts_a_new_worker_after_unsafe_f1(kind, reason):
    first = unsafe_value(kind)
    assert first["metrics"]["cleanup"]  # A summary flag alone is insufficient.
    r, visited = campaign(
        lambda name: first if name == "hoben-live" else observed("ha", name)
    )
    assert visited == ["hoben-live"]
    assert r["stages"][0]["status"] == "FAILURE"
    assert all(
        s["status"] == "NOT RUN" and s["reason"] == reason for s in r["stages"][1:]
    )
    assert r["actions_result"] == "FAILURE"


@pytest.mark.parametrize("kind,reason", UNSAFE)
@pytest.mark.parametrize("engine", ["python", "node"])
def test_both_validators_refuse_forged_continuation_after_unsafe_f1(
    kind, reason, engine
):
    stages = [unsafe_value(kind)] + [observed("ha", name) for name in NAMES[1:]]
    r = envelope("ha", "all", stages)
    if engine == "python":
        with pytest.raises(ValueError):
            validate_report(r)
    else:
        assert not node_accepts(r)


def functional_failure(name):
    d = ha_detail(name)
    e = d["evidence"]
    e["completed"] = False
    last = e["samples"][-1]
    end = e["window"]["elapsed_ms"] + 1
    e.update(
        diagnostic_schema=1,
        diagnostic=dict(
            end_ms=end,
            first=None,
            terminal=None,
            cleanup=None,
            invalid=False,
            owners=[
                dict(
                    role="a",
                    generation=1,
                    accepted=True,
                    accepted_generation=1,
                    close_client_subcode=None,
                    close=[end - 1, end - 1, end, end],
                    stage="reaped",
                    pending=0,
                    last_read=[
                        last["observation"]["read_sequence"],
                        last["at_ms"],
                        end - last["at_ms"],
                    ],
                )
            ],
        ),
    )
    return value(name, d)


@pytest.mark.parametrize("failed_at", range(7))
def test_every_safe_functional_failure_with_full_f1_runs_all_seven(failed_at):
    failed = functional_failure(NAMES[failed_at])
    r, visited = campaign(
        lambda name: failed if name == NAMES[failed_at] else observed("ha", name)
    )
    assert visited == list(NAMES) and len(visited) == 7
    assert all(s["started"] for s in r["stages"])
    assert r["stages"][failed_at] == failed
    assert r["actions_result"] == "FAILURE"
    assert "dual-session-observation" not in visited


@pytest.mark.parametrize(
    "reason", ["previous_failure", "not_started", "not_observed", "observed"]
)
@pytest.mark.parametrize("engine", ["python", "node"])
def test_safe_functional_failure_cannot_justify_unexplained_not_run(reason, engine):
    stages = [functional_failure("hoben-live")] + [
        stage("ha", name, reason=reason) for name in NAMES[1:]
    ]
    r = envelope("ha", "all", stages)
    if engine == "python":
        with pytest.raises(ValueError):
            validate_report(r)
    else:
        assert not node_accepts(r)


def test_individual_receipts_and_other_campaigns_keep_their_existing_contract():
    for kind, _ in UNSAFE:
        v = unsafe_value(kind)
        r = envelope("ha", "hoben-live", [v])
        assert validate_report(r) and node_accepts(r)
        assert r["stages"][0] == v
    old = observed("ha", "open-errors")
    before = copy.deepcopy(old)
    assert validate_report(envelope("ha", "open-errors", [old]))
    assert old == before


@pytest.mark.parametrize("category", ["authentication", "authorization"])
def test_legacy_identity_refusal_stops_all_without_f1(category):
    d = ha_detail("open-errors")
    d["evidence"].update(completed=False, terminal=category)
    failed = value("open-errors", d)
    r, visited = campaign(
        lambda name: failed if name == "open-errors" else observed("ha", name)
    )
    assert visited == list(NAMES[:2])
    assert all(
        s["status"] == "NOT RUN" and s["reason"] == "identity_refused"
        for s in r["stages"][2:]
    )
    assert r["actions_result"] == "FAILURE"


@pytest.mark.parametrize("category", ["eof", "close_client", "timeout", "protocol"])
def test_cleaned_transient_incident_is_not_a_blanket_reason_to_stop_all(category):
    from tests.test_live_recovery_r2 import recovered_detail

    d = recovered_detail(category)
    d["evidence"]["completed"] = False  # Functional criteria remain unfulfilled.
    failed = value("hoben-live", d)
    r, visited = campaign(
        lambda name: failed if name == "hoben-live" else observed("ha", name)
    )
    assert visited == list(NAMES)
    assert r["stages"][0] == failed and failed["status"] == "FAILURE"
    assert r["actions_result"] == "FAILURE"


@pytest.mark.parametrize("unsafe", [False, True])
def test_publication_preserves_all_seven_verdicts_and_the_safety_reason(
    tmp_path, unsafe
):
    import base64
    import json

    from tests.test_campaign_publication import node

    first = (
        unsafe_value("cleanup_first") if unsafe else functional_failure("hoben-live")
    )
    r, visited = campaign(
        lambda name: first if name == "hoben-live" else observed("ha", name)
    )
    encoded = base64.b64encode(json.dumps(r, separators=(",", ":")).encode()).decode()
    result = node("publish", tmp_path, "ha", "all", encoded=encoded)
    assert result.returncode == 1
    public = json.loads((tmp_path / "hoben-campaign-published/report.json").read_text())
    assert public == r and public["actions_result"] == "FAILURE"
    summary = (tmp_path / "summary").read_text()
    for s in r["stages"]:
        assert f"| {s['scenario']} | {s['status']} |" in summary
    assert "dual-session-observation" not in [s["scenario"] for s in r["stages"]]
    if unsafe:
        assert visited == ["hoben-live"]
        assert "Premier incident : a / génération 1 / cleanup_failed" in summary
        assert all(s["reason"] == "cleanup_failed" for s in r["stages"][1:])
    else:
        assert visited == list(NAMES)
    assert "PRIVATE_PAYLOAD" not in summary
