"""Partial Actions registry metadata, independent of Git content and admission.

An injected authenticated GET reader is the source boundary. No default backend,
token discovery, YAML interpreter, registration/activation operation or CLI.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Protocol

PREFIX = "/repos/Guillaume0385/ha-hoben-community"
MAX_METADATA_BYTES = 16 * 1024  # GitHub metadata only, never a Hoben RX budget


class Campaign(Enum):
    """These selectors never accept a workflow ID, path, ref or URL."""

    PROTOCOL = "protocol"
    HA = "ha"


_FILES = MappingProxyType(
    {Campaign.PROTOCOL: "hoben-protocol-manual.yml", Campaign.HA: "hoben-ha-manual.yml"}
)


class WorkflowState(Enum):
    """Known REST states, reported verbatim without granting execution rights."""

    ACTIVE = "active"
    DELETED = "deleted"
    DISABLED_FORK = "disabled_fork"
    DISABLED_INACTIVITY = "disabled_inactivity"
    DISABLED_MANUALLY = "disabled_manually"


class State(Enum):
    """Attested metadata is separate from unknown execution prerequisites."""

    ATTESTED = "attested"
    UNKNOWN = "unknown"


class FactName(Enum):
    """An existing REST entry can be disabled/deleted; it is not a loaded YAML."""

    ENTRY = "reported_campaign_registry_entry"
    ID = "reported_workflow_id"
    PATH = "reported_campaign_workflow_path"
    STATE = "reported_workflow_state"
    WORKFLOW_REF = "executed_workflow_ref"
    YAML = "loaded_workflow_sha_content_and_semantics"
    ACTIVE_ON_REF = "workflow_active_on_pinned_ref"
    DISPATCH = "dispatch_provenance"
    CURRENT_HEAD = "current_experimental_head_and_ancestry"
    PROTECTION = "effective_branch_protection"
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
    """No free-text response, URL, credential or exception in an error."""

    CAMPAIGN = "invalid_registry_campaign"
    SHAPE = "malformed_registry_metadata"
    SIZE = "registry_metadata_too_large"
    ID = "workflow_id_unverified"
    PATH = "campaign_workflow_path_unverified"
    STATE = "workflow_state_unverified"
    FORBIDDEN = "api_forbidden"
    NOT_FOUND = "workflow_metadata_not_found"
    RATE_LIMIT = "api_rate_limited"
    API = "api_unavailable"
    PAGINATION = "pagination_unverified"
    CHANGED = "registry_metadata_changed"
    PREVIOUS = "previous_registry_observation_unverified"


@dataclass(frozen=True)
class Fact:
    """Only closed metadata facts and states may leave validation."""

    name: FactName
    state: State


@dataclass(frozen=True)
class Observation:
    """No payload retained; NOT RUN/FAILURE even when state reports active."""

    facts: tuple[Fact, ...]
    error: Error | None
    reported_state: WorkflowState | None = None
    _binding: str | None = field(default=None, repr=False)
    _campaign: Campaign | None = field(default=None, repr=False)
    can_start: bool = field(default=False, init=False)
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)

    def __bool__(self):
        return False


class Response(Protocol):
    """The existing GET transport can provide this bounded reply shape."""

    status: int
    data: object
    next_page: int | None


class Reader(Protocol):
    """Trusted authenticated REST infrastructure; no backend imported here."""

    def get(self, path: str) -> Response: ...


_PROVEN = frozenset({FactName.ENTRY, FactName.ID, FactName.PATH, FactName.STATE})
_TEXT_LIMITS = MappingProxyType(
    {
        "node_id": 256,
        "name": 256,
        "created_at": 64,
        "updated_at": 64,
        "deleted_at": 64,
        "url": 2048,
        "html_url": 2048,
        "badge_url": 2048,
    }
)


class _Denied(Exception):
    pass


def _need(condition, category):
    if not condition:
        raise _Denied(category)


def _file(campaign):
    _need(type(campaign) is Campaign, Error.CAMPAIGN)
    return _FILES[campaign]


def _validated(campaign, payload):
    filename = _file(campaign)
    _need(type(payload) is dict, Error.SHAPE)
    _need(
        {"id", "path", "state"} <= payload.keys()
        and payload.keys() <= {"id", "path", "state", *_TEXT_LIMITS},
        Error.SHAPE,
    )
    _need(type(payload["id"]) is int and 0 < payload["id"] <= 2**53 - 1, Error.ID)
    _need(
        type(payload["path"]) is str
        and payload["path"] == ".github/workflows/" + filename,
        Error.PATH,
    )
    _need(
        type(payload["state"]) is str
        and payload["state"] in {s.value for s in WorkflowState},
        Error.STATE,
    )
    for key, limit in _TEXT_LIMITS.items():
        if key in payload:
            if key == "deleted_at" and payload[key] is None:
                continue
            _need(
                type(payload[key]) is str
                and len(payload[key]) <= limit
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in payload[key]),
                Error.SHAPE,
            )
    # Bind every accepted field, including optional metadata. JSON key order is
    # immaterial, but any value/field change between reads or recheck refuses.
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    _need(len(encoded) <= MAX_METADATA_BYTES, Error.SIZE)
    binding = hashlib.sha256(
        PREFIX.encode() + b"\0" + campaign.value.encode() + b"\0" + encoded
    ).hexdigest()
    return WorkflowState(payload["state"]), binding


def _result(error=None, state=None, binding=None, campaign=None):
    return Observation(
        tuple(
            Fact(n, State.ATTESTED if error is None and n in _PROVEN else State.UNKNOWN)
            for n in FactName
        ),
        error,
        state,
        binding,
        campaign,
    )


def validate_registry(campaign: Campaign, payload: object) -> Observation:
    """Pure shape/relationship checks, not authentication of a supplied dict."""
    try:
        state, binding = _validated(campaign, payload)
        return _result(state=state, binding=binding, campaign=campaign)
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


def read_registry(reader: Reader, campaign: Campaign, previous=None) -> Observation:
    """Read only one fixed workflow route twice, optionally rechecking prior facts.

    No main/ref selection, workflow list, Git/YAML inference or registration
    fallback. Unavailable metadata leaves every fact unknown, never runnable.
    """
    try:
        filename = _file(campaign)
        if previous is not None:
            _need(
                type(previous) is Observation
                and previous.error is None
                and previous._campaign is campaign
                and type(previous.reported_state) is WorkflowState
                and previous.facts == _result().facts
                and type(previous._binding) is str
                and re.fullmatch(r"[a-f0-9]{64}", previous._binding) is not None,
                Error.PREVIOUS,
            )
        path = PREFIX + "/actions/workflows/" + filename
        state, binding = _validated(campaign, _get(reader, path))
        _need(
            _validated(campaign, _get(reader, path)) == (state, binding), Error.CHANGED
        )
        if previous is not None:
            _need(
                previous._binding == binding and previous.reported_state is state,
                Error.CHANGED,
            )
        return _result(state=state, binding=binding, campaign=campaign)
    except _Denied as error:
        return _result(error.args[0])
    except Exception:
        return _result(Error.SHAPE)


if __name__ == "__main__":
    raise SystemExit(1)
