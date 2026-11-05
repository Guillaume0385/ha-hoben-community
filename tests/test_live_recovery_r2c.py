"""R2-C reconstructs the unpublished permanent-first F1 fixtures; no network."""

import copy

import pytest

from scripts.campaign_runtime_contract import validate_report
from scripts.ha_campaign_evidence import project
from tests.test_campaign_runtime import ha_detail, node_accepts
from tests.test_live_recovery_r2 import report

PERMANENT = (
    "authentication",
    "authorization",
    "internal",
    "cancelled",
    "cleanup_failed",
    "closed",
    "exhausted",
)


def nominal_f1_detail(category=None, *, initial_retry=False):
    """Six decoded reads; only the F1 first event contradicts nominal safety."""
    d = ha_detail("hoben-live")
    e = d["evidence"]
    e["window"]["clock"] = "monotonic"
    d["supervisor"]["elapsed_ms"] = 300002
    owner = dict(
        role="a",
        generation=1,
        accepted=True,
        accepted_generation=1,
        close_client_subcode=None,
        close=[300000, 300000, 300001, 300001],
        stage="reaped",
        pending=0,
        last_read=[6, 250000, 50002],
    )
    owners = [owner]
    if initial_retry:
        owner["generation"] = 2
        owners.insert(
            0,
            dict(
                role="a",
                generation=1,
                accepted=False,
                accepted_generation=None,
                close_client_subcode=None,
                close=[0, 0, 0, 0],
                stage="reaped",
                pending=0,
                last_read=None,
            ),
        )
        for o in [s["observation"] for s in e["samples"]] + [
            e["window"]["observation"],
            e["cleanup"]["observation"],
        ]:
            o["attempts"] = 2
    first = (
        None
        if category is None
        else [
            "a",
            1,
            0,
            category,
            "opening" if initial_retry else "unknown",
            "transport_connect" if initial_retry else "observer",
            None,
        ]
    )
    e.update(
        diagnostic_schema=1,
        diagnostic=dict(
            end_ms=300002,
            first=first,
            terminal=None,
            cleanup=None,
            owners=owners,
            invalid=False,
        ),
    )
    return d


def expected_failure(category):
    r = report(nominal_f1_detail(category))
    # Fixed expected verdict, independent of Python's current projection.
    # This makes the Node RED check exercise its own projector as well.
    r["actions_result"] = r["stages"][0]["status"] = "FAILURE"
    r["stages"][0]["metrics"]["error"] = "unexpected"
    return r


@pytest.mark.parametrize("category", PERMANENT)
@pytest.mark.parametrize("engine", ["python", "node"])
def test_permanent_first_refuses_nominal_success_without_terminal_or_cleanup(
    category, engine
):
    r = expected_failure(category)
    before = copy.deepcopy(r)
    if engine == "python":
        assert validate_report(r) == r
    else:
        assert node_accepts(r)
    assert r == before  # No event or counter erased by validation.
    d = r["stages"][0]["detail"]
    m = project("hoben-live", d)
    assert m["reads"] == m["reads_ok"] == 6 and m["continuous"]
    assert m["cleanup"] and m["completed"] and not m["recovered"]
    assert m["error"] == "unexpected"
    assert d["evidence"]["diagnostic"]["first"][3] == category
    assert d["evidence"]["diagnostic"]["terminal"] is None
    assert d["evidence"]["diagnostic"]["cleanup"] is None
    forged = copy.deepcopy(r)
    forged["stages"][0]["metrics"]["error"] = "none"
    forged["actions_result"] = forged["stages"][0]["status"] = "SUCCESS"
    with pytest.raises(ValueError):
        validate_report(forged)
    assert not node_accepts(forged)


@pytest.mark.parametrize("category", [None, "tls", "transport", "timeout"])
@pytest.mark.parametrize("engine", ["python", "node"])
def test_healthy_nominal_and_transient_opening_retry_stay_success(category, engine):
    r = report(nominal_f1_detail(category, initial_retry=category is not None))
    assert r["actions_result"] == "SUCCESS"
    m = r["stages"][0]["metrics"]
    assert m["continuous"] and m["reads"] == m["reads_ok"] == 6
    assert m["error"] == "none" and not m["recovered"]
    assert m["opens"] == (2 if category else 1)
    assert (validate_report(r) == r) if engine == "python" else node_accepts(r)


@pytest.mark.parametrize(
    "mutation",
    [
        "first_missing",
        "schema_missing",
        "diagnostic_missing",
        "terminal_missing",
        "cleanup_missing",
        "category_invalid",
        "event_truncated",
        "extra_field",
        "tap_invalid",
        "pending_owner",
    ],
)
def test_partial_or_altered_f1_never_validates_the_permanent_first_report(mutation):
    r = expected_failure("authentication")
    e = r["stages"][0]["detail"]["evidence"]
    f = e["diagnostic"]
    if mutation == "schema_missing":
        del e["diagnostic_schema"]
    elif mutation == "diagnostic_missing":
        del e["diagnostic"]
    elif mutation == "first_missing":
        del f["first"]
    elif mutation == "terminal_missing":
        del f["terminal"]
    elif mutation == "cleanup_missing":
        del f["cleanup"]
    elif mutation == "category_invalid":
        f["first"][3] = "PRIVATE_PAYLOAD"
    elif mutation == "event_truncated":
        f["first"].pop()
    elif mutation == "extra_field":
        f["payload"] = "PRIVATE_PAYLOAD"
    elif mutation == "tap_invalid":
        f["invalid"] = True
    elif mutation == "pending_owner":
        f["owners"][0]["pending"] = 1
    with pytest.raises(ValueError):
        validate_report(r)
    assert not node_accepts(r)
