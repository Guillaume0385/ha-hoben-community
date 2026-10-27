"""Partial Git tree evidence for two inert campaigns; never an execution permit.

Only metadata is traversed through an injected authenticated GET reader. Blob
contents, Actions registration and the workflow actually loaded remain unknown.
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
REF = "refs/heads/experimental"
PREFIX = "/repos/" + REPOSITORY
MAX_TREE_ENTRIES = 10000  # GitHub metadata only; no Hoben RX budget is introduced


class Campaign(Enum):
    """No free-form path or workflow selector is accepted."""

    PROTOCOL = "protocol"
    HA = "ha"


_FILES = MappingProxyType(
    {
        Campaign.PROTOCOL: "hoben-protocol-manual.yml",
        Campaign.HA: "hoben-ha-manual.yml",
    }
)


class State(Enum):
    """Only independently checked metadata facts may become attested."""

    ATTESTED = "attested"
    UNKNOWN = "unknown"


class FactName(Enum):
    """Presence of a Git blob does not establish workflow provenance or policy."""

    REPOSITORY = "repository"
    COMMIT = "pinned_git_commit"
    WORKFLOW_PATH = "workflow_path_in_pinned_tree"
    BLOB = "regular_blob_identity"
    CURRENT_HEAD = "current_experimental_head_and_ancestry"
    PROTECTION = "effective_branch_protection"
    WORKFLOW_REF = "loaded_workflow_ref"
    YAML = "workflow_yaml_content"
    REGISTERED = "actions_workflow_registered_or_loaded"
    DISPATCH = "dispatch_provenance"
    MANAGER_REVIEW = "manager_review"
    PR_CI = "pr_and_ci"
    ENVIRONMENT = "environment_policy_and_approvals"
    CLAIM = "atomic_claim"
    MUTEX = "mutex"
    REPLAY = "anti_replay"
    FRESHNESS = "global_freshness"
    ATOMICITY = "atomic_snapshot"
    POST_APPROVAL = "recheck_after_approval"
    UI_MAIN = "ui_and_main_selection"
    AUTHORIZATION = "execution_authorization"


class Error(Enum):
    """Closed categories only; no path, body, token or exception leaves here."""

    EXPECTED = "invalid_expected_workflow_tree"
    SHAPE = "malformed_workflow_tree_response"
    REPOSITORY = "repository_unverified"
    COMMIT = "pinned_commit_unverified"
    TREE = "tree_identity_or_shape_unverified"
    ENTRY = "tree_entry_unverified"
    MISSING = "required_tree_entry_missing"
    TRUNCATED = "tree_completeness_unverified"
    FORBIDDEN = "api_forbidden"
    NOT_FOUND = "api_not_found"
    RATE_LIMIT = "api_rate_limited"
    API = "api_unavailable"
    PAGINATION = "pagination_unverified"
    CHANGED = "workflow_tree_facts_changed"
    PREVIOUS = "previous_workflow_tree_observation_unverified"


@dataclass(frozen=True, repr=False)
class Expected:
    """Pins come from independent configuration, never from a received commit."""

    campaign: Campaign
    sha: str
    repository: str = REPOSITORY
    ref: str = REF


@dataclass(frozen=True)
class Fact:
    """A fixed fact name and state, with no free-form metadata."""

    name: FactName
    state: State


@dataclass(frozen=True)
class Observation:
    """Immutable partial facts and non-secret bindings; always NOT RUN/FAILURE."""

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
    """The existing bounded transport can supply this reply shape."""

    status: int
    data: object
    next_page: int | None


class Reader(Protocol):
    """Trusted authenticated GET boundary; no HTTP backend or token discovery."""

    def get(self, path: str) -> Response: ...


_PROVEN = frozenset(
    {FactName.REPOSITORY, FactName.COMMIT, FactName.WORKFLOW_PATH, FactName.BLOB}
)


class _Denied(Exception):
    pass


def _need(condition, error):
    if not condition:
        raise _Denied(error)


def _sha(value):
    return (
        type(value) is str
        and re.fullmatch(r"[a-f0-9]{40}", value) is not None
        and value != "0" * 40
    )


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _key(expected):
    _need(type(expected) is Expected, Error.EXPECTED)
    _need(
        type(expected.campaign) is Campaign
        and type(expected.repository) is str
        and expected.repository == REPOSITORY
        and type(expected.ref) is str
        and expected.ref == REF
        and _sha(expected.sha),
        Error.EXPECTED,
    )
    return _digest(
        (expected.repository, expected.ref, expected.sha, expected.campaign.value)
    )


def _match(value, expected, error):
    _need(type(value) is dict, error)
    _need(
        all(
            type(value.get(k)) is type(v) and value[k] == v for k, v in expected.items()
        ),
        error,
    )


def _repository(payload):
    _match(payload, {"id": REPOSITORY_ID, "full_name": REPOSITORY}, Error.REPOSITORY)
    _match(
        payload.get("owner"),
        {"id": OWNER_ID, "login": "Guillaume0385", "type": "User"},
        Error.REPOSITORY,
    )


def _commit(payload, expected):
    _match(payload, {"sha": expected.sha}, Error.COMMIT)
    tree = payload.get("tree")
    _need(type(tree) is dict and _sha(tree.get("sha")), Error.COMMIT)
    return tree["sha"]


def _entry(payload, tree_sha, name, mode, kind):
    """Validate a complete non-recursive tree before selecting one component.

    Every entry must have a unique simple name and a valid Git identity. Even
    unrelated symlinks/submodules are conservatively refused, never traversed.
    Executable regular siblings are permitted; the selected YAML must be 100644.
    """
    _match(payload, {"sha": tree_sha}, Error.TREE)
    _need(payload.get("truncated") is False, Error.TRUNCATED)
    entries = payload.get("tree")
    _need(type(entries) is list and len(entries) <= MAX_TREE_ENTRIES, Error.TREE)
    names, selected = set(), None
    for entry in entries:
        _need(type(entry) is dict, Error.ENTRY)
        path = entry.get("path")
        _need(
            type(path) is str
            and 0 < len(path) <= 255
            and path not in (".", "..")
            and not any(
                c in "/\\" or ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF
                for c in path
            )
            and path not in names,
            Error.ENTRY,
        )
        names.add(path)
        _need(
            type(entry.get("mode")) is str
            and type(entry.get("type")) is str
            and (entry.get("mode"), entry.get("type"))
            in (("040000", "tree"), ("100644", "blob"), ("100755", "blob"))
            and _sha(entry.get("sha")),
            Error.ENTRY,
        )
        if path == name:
            _match(entry, {"mode": mode, "type": kind}, Error.ENTRY)
            selected = entry["sha"]
    _need(selected is not None, Error.MISSING)
    return selected


def _validated(expected, repository, commit, root, github, workflows):
    _repository(repository)
    root_sha = _commit(commit, expected)
    github_sha = _entry(root, root_sha, ".github", "040000", "tree")
    workflows_sha = _entry(github, github_sha, "workflows", "040000", "tree")
    blob_sha = _entry(
        workflows, workflows_sha, _FILES[expected.campaign], "100644", "blob"
    )
    return _digest((_key(expected), root_sha, github_sha, workflows_sha, blob_sha))


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


def validate_workflow_tree(
    expected: Expected,
    repository: object,
    commit: object,
    root: object,
    github: object,
    workflows: object,
) -> Observation:
    """Pure shape/relationship validation; a dict does not authenticate its source."""
    try:
        key = _key(expected)
        binding = _validated(expected, repository, commit, root, github, workflows)
        return _result(binding=binding, key=key)
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
    _repository(repository)
    commit = _get(reader, PREFIX + "/git/commits/" + expected.sha)
    root_sha = _commit(commit, expected)
    root = _get(reader, PREFIX + "/git/trees/" + root_sha)
    github_sha = _entry(root, root_sha, ".github", "040000", "tree")
    github = _get(reader, PREFIX + "/git/trees/" + github_sha)
    workflows_sha = _entry(github, github_sha, "workflows", "040000", "tree")
    workflows = _get(reader, PREFIX + "/git/trees/" + workflows_sha)
    return _validated(expected, repository, commit, root, github, workflows)


def read_workflow_tree(
    reader: Reader, expected: Expected, previous=None
) -> Observation:
    """Traverse the pinned tree twice, optionally comparing a prior binding.

    These sequential reads neither attest current branch HEAD/ancestry nor an
    atomic snapshot, Actions registration, YAML contents or a loaded workflow.
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
    raise SystemExit(1)
