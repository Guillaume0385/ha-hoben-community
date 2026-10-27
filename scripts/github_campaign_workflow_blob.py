"""Bounded Git blob byte identity; no YAML semantics or execution authority."""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum

if __name__ == "__main__":
    raise SystemExit(1)
else:
    from scripts import github_campaign_workflow_tree as tree

MAX_BLOB_BYTES = 16 * 1024
MAX_BASE64_CHARS = 24 * 1024  # includes GitHub's base64 line wrapping


class FactName(Enum):
    """Byte identity never implies YAML semantics or loaded Actions provenance."""

    TREE_LINK = "pinned_campaign_commit_tree_link"
    BLOB = "git_blob_bytes_identity"
    SIZE = "bounded_coherent_blob_size"
    YAML = "workflow_yaml_semantics"
    REGISTERED = "actions_workflow_registered_or_loaded"
    WORKFLOW_REF = "executed_workflow_ref"
    CURRENT_HEAD = "current_experimental_head_and_ancestry"
    PROTECTION = "effective_branch_protection"
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


class State(Enum):
    """Closed partial facts; unknown is never a permissive default."""

    ATTESTED = "attested"
    UNKNOWN = "unknown"


class Error(Enum):
    """Only categorical failures leave the byte-processing boundary."""

    EXPECTED = "invalid_expected_workflow_blob"
    TREE = "workflow_tree_identity_unverified"
    SHAPE = "malformed_blob_response"
    SIZE = "blob_size_unverified_or_excessive"
    ENCODING = "blob_base64_invalid"
    IDENTITY = "blob_git_identity_mismatch"
    FORBIDDEN = "api_forbidden"
    NOT_FOUND = "api_not_found"
    RATE_LIMIT = "api_rate_limited"
    API = "api_unavailable"
    PAGINATION = "pagination_unverified"
    CHANGED = "workflow_blob_facts_changed"
    PREVIOUS = "previous_workflow_blob_observation_unverified"


@dataclass(frozen=True, repr=False)
class Expected:
    """Independent config pins, checked against a distinct validated tree result."""

    campaign: tree.Campaign
    commit_sha: str
    blob_sha: str
    repository: str = tree.REPOSITORY
    ref: str = tree.REF


@dataclass(frozen=True)
class Fact:
    """Only a closed name and state; no content, URL or response field."""

    name: FactName
    state: State


@dataclass(frozen=True)
class Observation:
    """No bytes/text retained, and no execution permission even on success."""

    facts: tuple[Fact, ...]
    error: Error | None
    _binding: str | None = field(default=None, repr=False)
    _expected: str | None = field(default=None, repr=False)
    can_start: bool = field(default=False, init=False)
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)

    def __bool__(self):
        return False


_PROVEN = frozenset({FactName.TREE_LINK, FactName.BLOB, FactName.SIZE})


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
        type(expected.campaign) is tree.Campaign
        and _sha(expected.commit_sha)
        and _sha(expected.blob_sha)
        and type(expected.repository) is str
        and expected.repository == tree.REPOSITORY
        and type(expected.ref) is str
        and expected.ref == tree.REF,
        Error.EXPECTED,
    )
    return _digest(
        (
            expected.repository,
            expected.ref,
            expected.campaign.value,
            expected.commit_sha,
            expected.blob_sha,
        )
    )


def _tree(expected, observation):
    identity = tree.blob_identity(
        observation,
        tree.Expected(
            expected.campaign, expected.commit_sha, expected.repository, expected.ref
        ),
    )
    _need(identity is not None and identity.sha == expected.blob_sha, Error.TREE)
    return identity.binding


def _validated(expected, tree_binding, payload):
    """Check strict REST envelope, canonical base64 and Git object identity only."""
    _need(type(payload) is dict, Error.SHAPE)
    _need(
        {"sha", "size", "encoding", "content"} <= payload.keys()
        and payload.keys() <= {"sha", "size", "encoding", "content", "url", "node_id"},
        Error.SHAPE,
    )
    for key, limit in (("url", 2048), ("node_id", 256)):
        if key in payload:
            _need(type(payload[key]) is str and len(payload[key]) <= limit, Error.SHAPE)
    _need(
        type(payload["sha"]) is str and payload["sha"] == expected.blob_sha,
        Error.IDENTITY,
    )
    size, content = payload["size"], payload["content"]
    _need(type(size) is int and 0 <= size <= MAX_BLOB_BYTES, Error.SIZE)
    _need(
        type(payload["encoding"]) is str and payload["encoding"] == "base64",
        Error.ENCODING,
    )
    _need(type(content) is str and len(content) <= MAX_BASE64_CHARS, Error.SIZE)
    # Only base64 and LF/CRLF wrapping; no spaces, tabs, lone CR or blank lines.
    normalized = content.replace("\r\n", "\n")
    lines = normalized.removesuffix("\n").split("\n")
    _need(content == "" or all(lines), Error.ENCODING)
    encoded = "".join(lines)
    _need(len(encoded) == 4 * ((size + 2) // 3), Error.SIZE)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception:
        raise _Denied(Error.ENCODING) from None
    _need(base64.b64encode(decoded).decode("ascii") == encoded, Error.ENCODING)
    _need(len(decoded) == size, Error.SIZE)
    # Git SHA-1 is an object identifier, not an authorization/signature scheme.
    header = b"blob " + str(size).encode("ascii") + b"\0"
    sha = hashlib.sha1(header + decoded, usedforsecurity=False).hexdigest()
    _need(sha == expected.blob_sha, Error.IDENTITY)
    return _digest((_key(expected), tree_binding, hashlib.sha256(decoded).hexdigest()))


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


def validate_workflow_blob(
    expected: Expected, tree_observation: tree.Observation, payload: object
) -> Observation:
    """Pure validation, consuming separate tree proof; no source authentication."""
    try:
        key = _key(expected)
        binding = _validated(expected, _tree(expected, tree_observation), payload)
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


def read_workflow_blob(
    reader: tree.Reader,
    expected: Expected,
    tree_observation: tree.Observation,
    previous=None,
) -> Observation:
    """Read only the separately pinned/proven blob, twice; no tree or YAML fetch CLI."""
    try:
        key = _key(expected)
        tree_binding = _tree(expected, tree_observation)  # before every blob GET
        if previous is not None:
            _need(
                type(previous) is Observation
                and previous.error is None
                and previous._expected == key
                and previous.facts == _result().facts
                and type(previous._binding) is str
                and re.fullmatch(r"[a-f0-9]{64}", previous._binding) is not None,
                Error.PREVIOUS,
            )
        path = tree.PREFIX + "/git/blobs/" + expected.blob_sha
        binding = _validated(expected, tree_binding, _get(reader, path))
        _need(
            _validated(expected, tree_binding, _get(reader, path)) == binding,
            Error.CHANGED,
        )
        if previous is not None:
            _need(previous._binding == binding, Error.CHANGED)
        return _result(binding=binding, key=key)
    except _Denied as error:
        return _result(error.args[0])
    except Exception:
        return _result(Error.SHAPE)
