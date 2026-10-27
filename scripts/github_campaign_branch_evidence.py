"""Partial experimental branch HEAD evidence, independent of dispatch facts.

Pure payload checks and injected GET only. No HTTP backend, protection-policy
reader, execution permit, credentials, environment or default reader.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

REPOSITORY = "Guillaume0385/ha-hoben-community"
REPOSITORY_ID, OWNER_ID = 1401398724, 18246624
REF = "refs/heads/experimental"
PREFIX = "/repos/" + REPOSITORY
BRANCH_ROUTE = PREFIX + "/branches/experimental"


class State(Enum):
    """Only individually verified facts may be attested."""

    ATTESTED = "attested"
    UNKNOWN = "unknown"


class FactName(Enum):
    """Branch HEAD is separate from run SHA, policy and execution authority."""

    REPOSITORY = "repository"
    BRANCH_NAME = "branch_name"
    HEAD = "observed_branch_head"
    PROTECTION = "effective_branch_protection"
    MANAGER_REVIEW = "manager_review"
    ENVIRONMENT = "environment_policy_and_approvals"
    WORKFLOW_REF = "workflow_ref"
    WORKFLOW_YAML = "workflow_yaml_sha_and_content"
    DISPATCH = "dispatch_and_reported_run_sha"
    PR_CI = "pr_and_ci"
    CLAIM = "atomic_claim"
    MUTEX = "mutex"
    REPLAY = "anti_replay"
    FRESHNESS = "global_freshness"
    ATOMICITY = "atomic_snapshot"
    POST_APPROVAL = "recheck_after_approval"
    UI_MAIN = "ui_and_main_selection"
    AUTHORIZATION = "execution_authorization"


class Error(Enum):
    """No API payload, URL or exception string may leave this boundary."""

    EXPECTED = "invalid_expected_branch"
    SHAPE = "malformed_branch_response"
    REPOSITORY = "repository_unverified"
    BRANCH = "branch_name_unverified"
    HEAD = "branch_head_unverified_or_changed"
    FORBIDDEN = "api_forbidden"
    NOT_FOUND = "api_not_found"
    RATE_LIMIT = "api_rate_limited"
    API = "api_unavailable"
    PAGINATION = "pagination_unverified"
    CHANGED = "branch_facts_changed"
    PREVIOUS = "previous_branch_observation_unverified"


@dataclass(frozen=True, repr=False)
class Expected:
    """Independent pin; never constructed from a received commit.sha here."""

    sha: str
    repository: str = REPOSITORY
    ref: str = REF


@dataclass(frozen=True)
class Fact:
    """One closed fact/state pair, without caller-provided free text."""

    name: FactName
    state: State


@dataclass(frozen=True)
class Observation:
    """Immutable partial evidence, always NOT RUN/FAILURE without permission."""

    facts: tuple[Fact, ...]
    error: Error | None
    _binding: str | None = field(default=None, repr=False)
    _expected: str | None = field(default=None, repr=False)
    can_start: bool = field(default=False, init=False)
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)

    def __bool__(self):
        return False


class Response(Protocol):
    """Existing GET reply shape, independent of any HTTP implementation."""

    status: int
    data: object
    next_page: int | None


class Reader(Protocol):
    """Trusted authenticated GET port, with no backend imported by this module."""

    def get(self, path: str) -> Response: ...


_PROVEN = frozenset({FactName.REPOSITORY, FactName.BRANCH_NAME, FactName.HEAD})


class _Denied(Exception):
    pass


def _need(condition, error):
    if not condition:
        raise _Denied(error)


def _match(value, expected, error):
    _need(type(value) is dict, error)
    _need(
        all(type(value[k]) is type(v) and value[k] == v for k, v in expected.items()),
        error,
    )


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _key(expected):
    _need(type(expected) is Expected, Error.EXPECTED)
    _need(
        type(expected.repository) is str
        and expected.repository == REPOSITORY
        and type(expected.ref) is str
        and expected.ref == REF
        and type(expected.sha) is str
        and re.fullmatch(r"[a-f0-9]{40}", expected.sha) is not None
        and expected.sha != "0" * 40,
        Error.EXPECTED,
    )
    return _digest((expected.repository, expected.ref, expected.sha))


def _repository(payload):
    _match(payload, {"id": REPOSITORY_ID, "full_name": REPOSITORY}, Error.REPOSITORY)
    _match(
        payload["owner"],
        {"id": OWNER_ID, "login": "Guillaume0385", "type": "User"},
        Error.REPOSITORY,
    )


def _validated(expected, repository, branch):
    """Pure checks: protected/protection_url/permissions are deliberately unread."""
    _repository(repository)
    _match(branch, {"name": "experimental"}, Error.BRANCH)
    _match(branch["commit"], {"sha": expected.sha}, Error.HEAD)
    return _digest((_key(expected), branch["name"], branch["commit"]["sha"]))


def _result(error=None, binding=None, key=None):
    return Observation(
        tuple(
            Fact(n, State.ATTESTED if error is None and n in _PROVEN else State.UNKNOWN)
            for n in FactName
        ),
        error,
        binding,
        key,
    )


def validate_branch(
    expected: Expected, repository: object, branch: object
) -> Observation:
    """Validate REST payloads or fixtures; source authenticity is external."""
    try:
        key = _key(expected)
        return _result(binding=_validated(expected, repository, branch), key=key)
    except _Denied as error:
        return _result(error.args[0])
    except Exception:
        return _result(Error.SHAPE)


def _get(reader, path):
    try:
        response = reader.get(path)
    except Exception:
        raise _Denied(Error.API) from None
    _need(type(response.status) is int, Error.SHAPE)
    if response.status != 200:
        raise _Denied(
            {
                401: Error.FORBIDDEN,
                403: Error.FORBIDDEN,
                404: Error.NOT_FOUND,
                429: Error.RATE_LIMIT,
            }.get(response.status, Error.API)
        )
    _need(response.next_page is None, Error.PAGINATION)
    return response.data


def _read(reader, expected):
    repository = _get(reader, PREFIX)
    _repository(repository)  # wrong identity/permissions stop before branch GET
    branch = _get(reader, BRANCH_ROUTE)
    return _validated(expected, repository, branch)


def read_branch(reader: Reader, expected: Expected, previous=None) -> Observation:
    """Read repo/branch twice, and optionally recheck the same prior pins.

    These four GETs are not an atomic snapshot, a policy read or a post-approval
    recheck. A run's reported head_sha never substitutes for branch commit.sha.
    """
    try:
        key = _key(expected)
        if previous is not None:
            _need(
                type(previous) is Observation
                and previous.error is None
                and previous._expected == key
                and type(previous._binding) is str
                and re.fullmatch(r"[a-f0-9]{64}", previous._binding) is not None
                and previous.facts == _result().facts,
                Error.PREVIOUS,
            )
        binding = _read(reader, expected)
        _need(_read(reader, expected) == binding, Error.CHANGED)
        if previous is not None:
            _need(previous._binding == binding, Error.CHANGED)
        return _result(binding=binding, key=key)
    except _Denied as error:
        return _result(error.args[0])
    except Exception:
        return _result(Error.SHAPE)


if __name__ == "__main__":
    raise SystemExit(1)  # no CLI, backend or executable admission path
