"""Offline consistency model only. No reader, gate, claim writer or live caller.

Attestations are supplied facts, not authenticated here. Even a coherent model
always returns NOT RUN/FAILURE; it cannot authorize execution or secret access.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

REPOSITORY = "Guillaume0385/ha-hoben-community"
REPOSITORY_ID, OWNER_ID = 1401398724, 18246624
OWNER = "Guillaume0385"
MUTEX = "hoben-read-only-observation"
CHECKS = ("tests", "ha-tests", "hacs", "hassfest")
_CAMPAIGNS = {
    "protocol": (
        ".github/workflows/hoben-protocol-manual.yml",
        "hoben-experimental",
        (
            "tls-only",
            "session-open",
            "read-v4-state",
            "h1h2",
            "session-300",
            "session-reconnect",
            "all",
        ),
    ),
    "ha": (
        ".github/workflows/hoben-ha-manual.yml",
        "hoben-live",
        (
            "hoben-live",
            "open-errors",
            "refresh-v4",
            "session-reuse",
            "session-reconnect",
            "cleanup",
            "availability",
            "all",
        ),
    ),
}


@dataclass(frozen=True)
class OfflineAssessment:
    """No execution permission, including for synthetic coherent attestations."""

    consistent: bool
    category: str
    phase: str
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)
    _binding: str | None = field(default=None, repr=False)
    _claim: str | None = field(default=None, repr=False)
    _observed_ms: int = field(default=0, repr=False)

    def __bool__(self):
        return False  # a consistency observation is never an execution permit


class _Refused(Exception):
    pass


def _need(fact, category):
    if not fact:
        raise _Refused(category)  # only fixed internal categories


def _same(a, b):
    return type(a) is type(b) and a == b


def _keys(value, names, category):
    expected = set(names.split())
    _need(type(value) is dict and len(value) == len(expected), category)
    _need(
        all(type(k) is str for k in value) and value.keys() == expected,
        category,
    )


def _record(value, names, category):
    _keys(value, names + " attested", category)
    _need(value["attested"] is True, category)


def _integer(value):
    return type(value) is int and 0 < value <= 2**53 - 1


def _sha(value, length=40):
    return (
        type(value) is str
        and len(value) == length
        and re.fullmatch(r"[a-f0-9]+", value) is not None
        and set(value) != {"0"}
    )


def _validated(s):
    _keys(
        s,
        "schema campaign observed_ms dispatch branch pr review ci "
        "environment claim concurrency",
        "shape",
    )
    _need(_same(s["schema"], 1), "shape")
    _need(type(s["campaign"]) is str and s["campaign"] in _CAMPAIGNS, "campaign")
    workflow, environment, choices = _CAMPAIGNS[s["campaign"]]
    d = s["dispatch"]
    _record(
        d,
        "repository repository_id actor actor_id triggering_actor triggering_actor_id "
        "event ref sha workflow workflow_sha workflow_ref run_id attempt "
        "scenario started_ms",
        "context",
    )
    for key, expected in {
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "actor": OWNER,
        "actor_id": OWNER_ID,
        "triggering_actor": OWNER,
        "triggering_actor_id": OWNER_ID,
        "event": "workflow_dispatch",
        "ref": "refs/heads/experimental",
        "workflow": workflow,
        "workflow_ref": f"{REPOSITORY}/{workflow}@refs/heads/experimental",
        "attempt": 1,
    }.items():
        _need(_same(d[key], expected), "context")
    _need(_sha(d["sha"]) and _same(d["workflow_sha"], d["sha"]), "context")
    _need(type(d["scenario"]) is str and d["scenario"] in choices, "context")
    _need(_integer(d["run_id"]) and _integer(d["started_ms"]), "context")
    _need(
        _integer(s["observed_ms"]) and s["observed_ms"] >= d["started_ms"], "freshness"
    )
    b, p, r, ci, e, c, lock = (
        s[k]
        for k in ("branch", "pr", "review", "ci", "environment", "claim", "concurrency")
    )
    _record(b, "head_sha protected", "branch")
    _need(_same(b["head_sha"], d["sha"]) and b["protected"] is True, "branch")
    _record(
        p,
        "number matches base_ref base_repo_id head_repo_id head_ref "
        "merge_sha candidate_sha "
        "merge_tree candidate_tree merged draft merged_by merged_by_id merged_ms",
        "pr",
    )
    for key, expected in {
        "matches": 1,
        "base_ref": "experimental",
        "base_repo_id": REPOSITORY_ID,
        "head_repo_id": REPOSITORY_ID,
        "merge_sha": d["sha"],
        "merged": True,
        "draft": False,
        "merged_by": OWNER,
        "merged_by_id": OWNER_ID,
    }.items():
        _need(_same(p[key], expected), "pr")
    _need(
        _integer(p["number"]) and _sha(p["candidate_sha"]) and _sha(p["merge_tree"]),
        "pr",
    )
    _need(_same(p["candidate_tree"], p["merge_tree"]), "pr")
    _need(
        type(p["head_ref"]) is str
        and 0 < len(p["head_ref"]) <= 200
        and p["head_ref"].isascii()
        and p["head_ref"].isprintable(),
        "pr",
    )
    _need(_integer(p["merged_ms"]) and p["merged_ms"] <= d["started_ms"], "pr")
    _record(
        r,
        "candidate_sha manager_reviewed changes_requested unresolved_threads",
        "review",
    )
    _need(
        _same(r["candidate_sha"], p["candidate_sha"])
        and r["manager_reviewed"] is True
        and r["changes_requested"] is False
        and _same(r["unresolved_threads"], 0),
        "review",
    )
    _record(
        ci,
        "id repository_id head_repository_id pr_number candidate_sha "
        "head_ref event attempt "
        "workflow status completed_ms jobs",
        "ci",
    )
    for key, expected in {
        "repository_id": REPOSITORY_ID,
        "head_repository_id": REPOSITORY_ID,
        "pr_number": p["number"],
        "candidate_sha": p["candidate_sha"],
        "head_ref": p["head_ref"],
        "event": "pull_request",
        "attempt": 1,
        "workflow": ".github/workflows/validate.yml",
        "status": "completed",
    }.items():
        _need(_same(ci[key], expected), "ci")
    _need(
        _integer(ci["id"])
        and _integer(ci["completed_ms"])
        and ci["completed_ms"] <= p["merged_ms"],
        "ci",
    )
    _need(type(ci["jobs"]) is list and len(ci["jobs"]) == len(CHECKS), "ci")
    names = []
    for job in ci["jobs"]:
        _keys(job, "name candidate_sha status conclusion", "ci")
        _need(type(job["name"]) is str and job["name"] in CHECKS, "ci")
        _need(
            _same(job["candidate_sha"], p["candidate_sha"])
            and _same(job["status"], "completed")
            and _same(job["conclusion"], "success"),
            "ci",
        )
        names.append(job["name"])
    _need(len(set(names)) == len(CHECKS), "ci")
    _record(
        e,
        "id name policy_digest policy_kind rules_known branch_allowed "
        "approval_required approval",
        "environment",
    )
    _need(
        _integer(e["id"])
        and _same(e["name"], environment)
        and _sha(e["policy_digest"], 64),
        "environment",
    )
    modes = (
        ("experimental_only", "protected_branches")
        if s["campaign"] == "ha"
        else ("experimental_only",)
    )
    _need(type(e["policy_kind"]) is str and e["policy_kind"] in modes, "environment")
    _need(
        e["rules_known"] is True
        and e["branch_allowed"] is True
        and type(e["approval_required"]) is bool,
        "environment",
    )
    if e["approval_required"]:
        a = e["approval"]
        _record(a, "run_id environment_id state independent approved_ms", "approval")
        _need(
            _same(a["run_id"], d["run_id"])
            and _same(a["environment_id"], e["id"])
            and _same(a["state"], "approved")
            and a["independent"] is True,
            "approval",
        )
        _need(
            _integer(a["approved_ms"])
            and d["started_ms"] <= a["approved_ms"] <= s["observed_ms"],
            "approval",
        )
    else:
        _need(e["approval"] is None, "approval")
    _record(
        lock, "group run_id exclusive scan_complete other_active_runs", "concurrency"
    )
    _need(
        _same(lock["group"], MUTEX)
        and _same(lock["run_id"], d["run_id"])
        and lock["exclusive"] is True
        and lock["scan_complete"] is True,
        "concurrency",
    )
    _need(
        type(lock["other_active_runs"]) is list and not lock["other_active_runs"],
        "concurrency",
    )
    # Immutable model of facts, not a signature. API job ordering is irrelevant.
    projection = {k: v for k, v in s.items() if k not in {"claim", "observed_ms"}}
    projection["ci"] = {**ci, "jobs": sorted(ci["jobs"], key=lambda j: j["name"])}
    binding = hashlib.sha256(
        json.dumps(
            projection, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _record(c, "binding object_sha created_for_run exclusive replayed", "claim")
    _need(
        _same(c["binding"], binding)
        and _sha(c["object_sha"])
        and _same(c["created_for_run"], d["run_id"])
        and c["exclusive"] is True
        and c["replayed"] is False,
        "claim",
    )
    return binding, c["object_sha"], s["observed_ms"]


def _assess(snapshot, previous, phase):
    try:
        binding, claim, observed = _validated(snapshot)
        if phase == "recheck":
            _need(
                type(previous) is OfflineAssessment
                and previous.consistent is True
                and _same(previous.phase, "admission")
                and _sha(previous._binding, 64)
                and _sha(previous._claim)
                and _integer(previous._observed_ms),
                "previous",
            )
            _need(
                binding == previous._binding
                and claim == previous._claim
                and observed > previous._observed_ms,
                "state_changed",
            )
        return OfflineAssessment(
            True,
            "coherent_offline",
            phase,
            _binding=binding,
            _claim=claim,
            _observed_ms=observed,
        )
    except _Refused as error:
        return OfflineAssessment(False, error.args[0], phase)
    except Exception:
        return OfflineAssessment(False, "malformed", phase)


def assess_admission(snapshot):
    """Model complete post-approval/reservation facts; never authorize a run."""
    return _assess(snapshot, None, "admission")


def assess_recheck(admission, snapshot):
    """Reread every fact and compare immutable pins, without retaining input refs."""
    return _assess(snapshot, admission, "recheck")


if __name__ == "__main__":
    raise SystemExit(1)  # no CLI or successful process-level admission
