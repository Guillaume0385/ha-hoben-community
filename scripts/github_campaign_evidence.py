"""Read-only, injected GitHub provenance reader; never an admission authority.

The transport is a trust boundary: it must return authenticated GitHub REST
responses and pagination metadata. No HTTP client, credentials or CLI live here.
The validator below has no IO and never accepts caller-supplied attestations.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

REPOSITORY = "Guillaume0385/ha-hoben-community"
REPOSITORY_ID, OWNER_ID = 1401398724, 18246624
PREFIX = "/repos/" + REPOSITORY
WORKFLOW = ".github/workflows/validate.yml"
WORKFLOW_ID = 373497148
CHECKS = ("tests", "ha-tests", "hacs", "hassfest")


class State(Enum):
    ATTESTED = "attested"
    UNKNOWN = "unknown"


class FactName(Enum):
    REPOSITORY = "repository"
    COMMIT = "commit"
    PR = "pr_context"
    REVIEW = "formal_manager_review"
    CI = "ci_provenance"
    CHECKS = "checks"
    DISPATCH = "dispatch_context"
    THREADS = "review_threads"
    PROTECTION = "branch_protection"
    ENVIRONMENT = "environment_approvals"
    CLAIM = "atomic_claim"
    MUTEX = "mutex"
    REPLAY = "anti_replay"
    APPROVAL_RECHECK = "recheck_after_approval"


class Error(Enum):
    INVALID_REQUEST = "invalid_request"
    API_FORBIDDEN = "api_forbidden"
    API_NOT_FOUND = "api_not_found"
    API_RATE_LIMITED = "api_rate_limited"
    API_UNAVAILABLE = "api_unavailable"
    API_HTTP = "api_http_error"
    MALFORMED = "malformed_evidence"
    PAGINATION = "pagination_unverified"
    IDENTITY = "identity_unverified"
    PR = "pr_unverified"
    REVIEW = "manager_review_unverified"
    CI = "ci_unverified"
    CHANGED = "evidence_changed"
    PREVIOUS = "previous_unverified"


@dataclass(frozen=True)
class Fact:
    name: FactName
    state: State


@dataclass(frozen=True, repr=False)
class Request:
    """Pins to compare with GitHub, never attestations or permission flags."""

    pr_number: int
    candidate_sha: str
    head_ref: str
    ci_run_id: int
    target_ref: str = "refs/heads/experimental"


@dataclass(frozen=True, repr=False)
class Reply:
    """Transport envelope; next_page comes from the authenticated Link header.

    None means a verified terminal response, not lost pagination metadata.
    No response URL, body or exception is included in any public observation.
    """

    status: int
    data: object
    next_page: int | None


class Reader(Protocol):
    """A trusted adapter implements GET only, on api.github.com, without cache.

    Authenticate and verify TLS; reject redirects to other origins, missing
    pagination metadata, truncated JSON and insufficient authorization. Never
    turn an API failure into an empty list. Credentials stay in that adapter.
    """

    def get(
        self, path: str, *, page: int | None = None, per_page: int | None = None
    ) -> Reply: ...


@dataclass(frozen=True)
class Observation:
    """Bounded projection only; no raw responses, identities or permission."""

    facts: tuple[Fact, ...]
    error: Error | None
    _binding: str | None = field(default=None, repr=False)
    _request: str | None = field(default=None, repr=False)
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)
    can_start: bool = field(default=False, init=False)

    def __bool__(self):
        return False


_PROVEN = (
    FactName.REPOSITORY,
    FactName.COMMIT,
    FactName.PR,
    FactName.REVIEW,
    FactName.CI,
    FactName.CHECKS,
)


class _Denied(Exception):
    pass


def _need(condition, error):
    if not condition:
        raise _Denied(error)


def _positive(n):
    return type(n) is int and 0 < n <= 2**53 - 1


def _sha(s):
    return (
        type(s) is str
        and re.fullmatch(r"[a-f0-9]{40}", s) is not None
        and s != "0" * 40
    )


def _match(value, expected, error):
    _need(type(value) is dict, error)
    _need(
        all(type(value[k]) is type(v) and value[k] == v for k, v in expected.items()),
        error,
    )


def _owner(user):
    _match(
        user, {"id": OWNER_ID, "login": "Guillaume0385", "type": "User"}, Error.IDENTITY
    )


def _repo(repo):
    _match(repo, {"id": REPOSITORY_ID, "full_name": REPOSITORY}, Error.IDENTITY)
    _owner(repo["owner"])


def _request_key(request):
    _need(type(request) is Request, Error.INVALID_REQUEST)
    _need(
        _positive(request.pr_number)
        and _positive(request.ci_run_id)
        and _sha(request.candidate_sha)
        and type(request.head_ref) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/._-]{0,199}", request.head_ref)
        and request.head_ref != "main"
        and type(request.target_ref) is str
        and request.target_ref == "refs/heads/experimental",
        Error.INVALID_REQUEST,
    )
    return _digest(
        (request.pr_number, request.candidate_sha, request.head_ref, request.ci_run_id)
    )


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _date(value):
    _need(type(value) is str and len(value) == 20, Error.MALFORMED)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def _get(reader, path, **params):
    try:
        reply = reader.get(PREFIX + path, **params)
    except Exception:
        raise _Denied(Error.API_UNAVAILABLE) from None
    _need(type(reply) is Reply and type(reply.status) is int, Error.MALFORMED)
    if reply.status != 200:
        error = {
            401: Error.API_FORBIDDEN,
            403: Error.API_FORBIDDEN,
            404: Error.API_NOT_FOUND,
            429: Error.API_RATE_LIMITED,
        }.get(
            reply.status,
            Error.API_UNAVAILABLE if reply.status >= 500 else Error.API_HTTP,
        )
        raise _Denied(error)
    return reply


def _one(reader, path):
    reply = _get(reader, path)
    _need(reply.next_page is None and type(reply.data) is dict, Error.MALFORMED)
    return reply.data


def _pages(reader, path, key=None):
    """Bounded complete pagination; never follow a URL supplied in a body."""
    result, total = [], None
    for page in range(1, 11):
        reply = _get(reader, path, page=page, per_page=100)
        data = reply.data
        if key is not None:
            _need(type(data) is dict, Error.MALFORMED)
            count = data["total_count"]
            _need(type(count) is int and 0 <= count <= 1000, Error.PAGINATION)
            _need(total is None or total == count, Error.PAGINATION)
            total, data = count, data[key]
        _need(type(data) is list and len(data) <= 100, Error.PAGINATION)
        result.extend(data)
        if reply.next_page is None:
            _need(
                (total is not None and len(result) == total)
                or (total is None and len(data) < 100),
                Error.PAGINATION,
            )
            return result
        _need(
            type(reply.next_page) is int
            and reply.next_page == page + 1
            and len(data) > 0
            and (total is None or len(result) < total),
            Error.PAGINATION,
        )
    raise _Denied(Error.PAGINATION)


def _collect(reader, request):
    """Only constant repository-scoped GET routes; no status/check-name search."""
    return {
        "repository": _one(reader, ""),
        "commit": _one(reader, "/git/commits/" + request.candidate_sha),
        "pr": _one(reader, f"/pulls/{request.pr_number}"),
        "ci": _one(reader, f"/actions/runs/{request.ci_run_id}"),
        "jobs": _pages(
            reader, f"/actions/runs/{request.ci_run_id}/attempts/1/jobs", "jobs"
        ),
        "reviews": _pages(reader, f"/pulls/{request.pr_number}/reviews"),
    }


def _validate(request, source):
    """Pure validation of REST payloads; return only a normalized binding."""
    _repo(source["repository"])
    candidate = source["commit"]
    _match(candidate, {"sha": request.candidate_sha}, Error.IDENTITY)
    _need(_sha(candidate["tree"]["sha"]), Error.IDENTITY)
    pr, ci = source["pr"], source["ci"]
    _match(pr, {"number": request.pr_number, "draft": False}, Error.PR)
    _match(
        pr["head"], {"sha": request.candidate_sha, "ref": request.head_ref}, Error.PR
    )
    _match(pr["base"], {"ref": "experimental"}, Error.PR)
    _repo(pr["head"]["repo"])
    _repo(pr["base"]["repo"])
    _need(
        (pr["state"] == "open" and pr["merged"] is False and pr["merged_at"] is None)
        or (pr["state"] == "closed" and pr["merged"] is True),
        Error.PR,
    )
    if pr["merged"] is True:
        _owner(pr["merged_by"])
        _need(_sha(pr["merge_commit_sha"]), Error.PR)
        _date(pr["merged_at"])
    _date(pr["updated_at"])
    _match(
        ci,
        {
            "id": request.ci_run_id,
            "head_sha": request.candidate_sha,
            "head_branch": request.head_ref,
            "event": "pull_request",
            "run_attempt": 1,
            "workflow_id": WORKFLOW_ID,
            "status": "completed",
            "conclusion": "success",
        },
        Error.CI,
    )
    _repo(ci["repository"])
    _repo(ci["head_repository"])
    _match(ci["head_commit"], {"id": request.candidate_sha}, Error.CI)
    paths = (
        WORKFLOW,
        WORKFLOW + "@refs/pull/" + str(request.pr_number) + "/merge",
        WORKFLOW + "@refs/heads/" + request.head_ref,
    )
    _need(type(ci["path"]) is str and ci["path"] in paths, Error.CI)
    created, ended = _date(ci["created_at"]), _date(ci["updated_at"])
    _need(created <= ended, Error.CI)
    if pr["merged"] is True:
        _need(ended <= _date(pr["merged_at"]), Error.CI)
    associated = ci["pull_requests"]
    _need(type(associated) is list and len(associated) == 1, Error.CI)
    _match(associated[0], {"number": request.pr_number}, Error.CI)
    _match(
        associated[0]["head"],
        {"sha": request.candidate_sha, "ref": request.head_ref},
        Error.CI,
    )
    _match(associated[0]["base"], {"ref": "experimental"}, Error.CI)

    jobs, job_ids, names, job_pins = source["jobs"], set(), set(), []
    _need(type(jobs) is list and len(jobs) == len(CHECKS), Error.CI)
    for job in jobs:
        _match(
            job,
            {
                "run_id": request.ci_run_id,
                "run_attempt": 1,
                "head_sha": request.candidate_sha,
                "head_branch": request.head_ref,
                "status": "completed",
                "conclusion": "success",
            },
            Error.CI,
        )
        _need(_positive(job["id"]) and job["id"] not in job_ids, Error.CI)
        _need(
            type(job["name"]) is str
            and job["name"] in CHECKS
            and job["name"] not in names,
            Error.CI,
        )
        began, done = _date(job["started_at"]), _date(job["completed_at"])
        _need(created <= began <= done <= ended, Error.CI)
        job_ids.add(job["id"])
        names.add(job["name"])
        job_pins.append(
            (job["name"], job["id"], job["started_at"], job["completed_at"])
        )

    reviews, ids, latest, review_pins = source["reviews"], set(), {}, []
    _need(type(reviews) is list, Error.REVIEW)
    for review in reviews:
        _need(type(review) is dict and _positive(review["id"]), Error.REVIEW)
        _need(review["id"] not in ids and _sha(review["commit_id"]), Error.REVIEW)
        ids.add(review["id"])
        user, state = review["user"], review["state"]
        _need(type(user) is dict and _positive(user["id"]), Error.REVIEW)
        _need(type(user["login"]) is str and user["type"] == "User", Error.REVIEW)
        if user["id"] == OWNER_ID or user["login"] == "Guillaume0385":
            _owner(user)
        _need(
            type(state) is str
            and state in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"},
            Error.REVIEW,
        )
        submitted = _date(review["submitted_at"])
        if pr["merged"] is True:
            _need(submitted <= _date(pr["merged_at"]), Error.REVIEW)
        pin = (
            review["submitted_at"],
            review["id"],
            user["id"],
            state,
            review["commit_id"],
        )
        review_pins.append(pin)
        # COMMENTED is not a dismissal of a previous blocking review.
        if state != "COMMENTED":
            if user["id"] not in latest or pin[:2] > latest[user["id"]][:2]:
                latest[user["id"]] = pin
    _need(not any(p[3] == "CHANGES_REQUESTED" for p in latest.values()), Error.REVIEW)
    manager = latest.get(OWNER_ID)
    _need(
        manager is not None and manager[3:] == ("APPROVED", request.candidate_sha),
        Error.REVIEW,
    )
    return _digest(
        (
            candidate["tree"]["sha"],
            pr["state"],
            pr["merged_at"],
            pr.get("merge_commit_sha"),
            pr["updated_at"],
            ci["path"],
            ci["created_at"],
            ci["updated_at"],
            sorted(job_pins),
            sorted(review_pins),
        )
    )


def read_evidence(reader: Reader, request: Request, previous=None) -> Observation:
    """Two complete reads, then optional equality with a prior observation.

    This recheck covers provenance only, never post-approval admission. A real
    transport must be independently trusted; a mock is only an offline fixture.
    """
    try:
        key = _request_key(request)
        if previous is not None:
            _need(
                type(previous) is Observation
                and previous.error is None
                and previous._request == key
                and type(previous._binding) is str
                and len(previous._binding) == 64,
                Error.PREVIOUS,
            )
        binding = _validate(request, _collect(reader, request))
        _need(_validate(request, _collect(reader, request)) == binding, Error.CHANGED)
        if previous is not None:
            _need(previous._binding == binding, Error.CHANGED)
        return Observation(
            tuple(
                Fact(n, State.ATTESTED if n in _PROVEN else State.UNKNOWN)
                for n in FactName
            ),
            None,
            binding,
            key,
        )
    except _Denied as error:
        category = error.args[0]
    except Exception:
        category = Error.MALFORMED
    return Observation(tuple(Fact(n, State.UNKNOWN) for n in FactName), category)


if __name__ == "__main__":
    raise SystemExit(1)  # no network implementation, gate, collector or admission CLI
