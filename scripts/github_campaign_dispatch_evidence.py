"""Partial REST dispatch facts: pure validation and an injected GET reader only.

No HTTP backend, credentials, execution permit or inferred workflow_ref. A
trusted Reader supplies authenticated responses; fixtures do not prove live use.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Protocol

REPOSITORY = "Guillaume0385/ha-hoben-community"
REPOSITORY_ID, OWNER_ID = 1401398724, 18246624
PREFIX = "/repos/" + REPOSITORY


class Campaign(Enum):
    """Exactly the two inert campaign definitions, never the legacy live path."""

    PROTOCOL = "protocol"
    HA = "ha"


class State(Enum):
    """A missing fact never becomes a permissive false value."""

    ATTESTED = "attested"
    UNKNOWN = "unknown"


class FactName(Enum):
    """Closed projection of reported facts and explicitly unproved context."""

    REPOSITORY = "repository"
    RUN_ID = "run_id"
    EVENT = "event"
    ATTEMPT = "attempt"
    WORKFLOW = "workflow_id_and_path"
    RUN_SHA = "reported_run_sha"
    BRANCH_NAME = "reported_branch_name"
    ACTOR = "actor"
    TRIGGERING_ACTOR = "triggering_actor"
    WORKFLOW_REF = "workflow_ref"
    WORKFLOW_SHA = "workflow_sha"
    WORKFLOW_CONTENT = "workflow_content"
    WORKFLOW_REGISTRY = "workflow_registration"
    SCENARIO = "scenario_input"
    SENDER = "dispatch_sender"
    RUNNER = "runner_context"
    BRANCH_HEAD = "current_branch_head"
    PROTECTION = "branch_protection"
    ENVIRONMENT = "environment_policy_and_approvals"
    MANAGER_REVIEW = "manager_review"
    PR_CI = "pr_and_ci"
    CLAIM = "atomic_claim"
    MUTEX = "mutex"
    REPLAY = "anti_replay"
    POST_APPROVAL = "recheck_after_approval"
    UI_MAIN = "ui_and_main_selection"
    RUN_RESULT = "scenario_result"
    AUTHORIZATION = "execution_authorization"
    FRESHNESS = "global_freshness"


class Error(Enum):
    """Fixed categories, never an API body, URL, token or exception string."""

    EXPECTED = "invalid_expected_context"
    SHAPE = "malformed_dispatch_response"
    REPOSITORY = "repository_unverified"
    RUN = "run_unverified"
    WORKFLOW = "workflow_unverified"
    SHA = "sha_or_branch_unverified"
    ACTOR = "actor_unverified"
    FORBIDDEN = "api_forbidden"
    NOT_FOUND = "api_not_found"
    RATE_LIMIT = "api_rate_limited"
    API = "api_unavailable"
    PAGINATION = "pagination_unverified"
    CHANGED = "dispatch_facts_changed"
    PREVIOUS = "previous_observation_unverified"


@dataclass(frozen=True, repr=False)
class Expected:
    """Caller pins to compare with REST, not attestations or discovered IDs."""

    campaign: Campaign
    run_id: int
    workflow_id: int
    sha: str
    target_ref: str = "refs/heads/experimental"


@dataclass(frozen=True)
class Fact:
    name: FactName
    state: State


@dataclass(frozen=True)
class Observation:
    """Immutable, bounded projection; every result refuses execution."""

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
    """The existing GET transport's Reply shape, without importing a backend."""

    status: int
    data: object
    next_page: int | None


class Reader(Protocol):
    def get(self, path: str) -> Response: ...


_PATHS = MappingProxyType(
    {
        Campaign.PROTOCOL: ".github/workflows/hoben-protocol-manual.yml",
        Campaign.HA: ".github/workflows/hoben-ha-manual.yml",
    }
)
_PROVEN = frozenset(
    {
        FactName.REPOSITORY,
        FactName.RUN_ID,
        FactName.EVENT,
        FactName.ATTEMPT,
        FactName.WORKFLOW,
        FactName.RUN_SHA,
        FactName.BRANCH_NAME,
        FactName.ACTOR,
        FactName.TRIGGERING_ACTOR,
    }
)


class _Denied(Exception):
    pass


def _need(condition, error):
    if not condition:
        raise _Denied(error)


def _positive(value):
    return type(value) is int and 0 < value <= 2**53 - 1


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
        type(expected.campaign) is Campaign
        and _positive(expected.run_id)
        and _positive(expected.workflow_id)
        and type(expected.sha) is str
        and re.fullmatch(r"[a-f0-9]{40}", expected.sha) is not None
        and expected.sha != "0" * 40
        and type(expected.target_ref) is str
        and expected.target_ref == "refs/heads/experimental",
        Error.EXPECTED,
    )
    return _digest(
        (expected.campaign.value, expected.run_id, expected.workflow_id, expected.sha)
    )


def _owner(value, error):
    _match(value, {"id": OWNER_ID, "login": "Guillaume0385", "type": "User"}, error)


def _repository(value):
    _match(value, {"id": REPOSITORY_ID, "full_name": REPOSITORY}, Error.REPOSITORY)
    _owner(value["owner"], Error.REPOSITORY)


def _validated(expected, payload):
    """Pure checks of documented REST fields, discarding all other payload."""
    _match(
        payload,
        {"id": expected.run_id, "event": "workflow_dispatch", "run_attempt": 1},
        Error.RUN,
    )
    _repository(payload["repository"])
    _repository(payload["head_repository"])
    _match(payload, {"workflow_id": expected.workflow_id}, Error.WORKFLOW)
    path = payload["path"]
    target = _PATHS[expected.campaign]
    _need(
        type(path) is str and path in (target, target + "@refs/heads/experimental"),
        Error.WORKFLOW,
    )
    _match(
        payload, {"head_sha": expected.sha, "head_branch": "experimental"}, Error.SHA
    )
    _match(payload["head_commit"], {"id": expected.sha}, Error.SHA)
    _owner(payload["actor"], Error.ACTOR)
    # Never copy actor into triggering_actor when the latter proof is absent.
    _owner(payload["triggering_actor"], Error.ACTOR)
    return _digest((_key(expected), path))


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


def validate_dispatch(expected: Expected, payload: object) -> Observation:
    """Validate an authenticated REST payload or offline fixture, with no IO.

    This function does not establish transport authenticity. ATTESTED is relative
    to that source boundary and never authenticates a caller's booleans.
    """
    try:
        key = _key(expected)
        return _result(binding=_validated(expected, payload), key=key)
    except _Denied as error:
        return _result(error.args[0])
    except Exception:
        return _result(Error.SHAPE)


def _read(reader, expected):
    try:
        response = reader.get(PREFIX + f"/actions/runs/{expected.run_id}")
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
    return _validated(expected, response.data)


def read_dispatch(reader: Reader, expected: Expected, previous=None) -> Observation:
    """Two distinct GETs of the same run; optional provenance-only recheck.

    Changes to unrelated status/conclusion/updated_at are not dispatch facts.
    No approval, anti-replay or atomic/fresh snapshot is attested here.
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
            _need(binding == previous._binding, Error.CHANGED)
        return _result(binding=binding, key=key)
    except _Denied as error:
        return _result(error.args[0])
    except Exception:
        return _result(Error.SHAPE)


if __name__ == "__main__":
    raise SystemExit(1)  # no CLI, HTTP backend, environment or default reader
