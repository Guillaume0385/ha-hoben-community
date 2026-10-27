"""Synthetic registry metadata only, with DNS and sockets forbidden."""

import ast
import copy
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest
from test_github_campaign_transport import FakeHTTP, Stream

import scripts.github_campaign_actions_registry as registry
from scripts.github_campaign_evidence import Reply
from scripts.github_campaign_transport import (
    Failure,
    GitHubGETTransport,
    TransportFailure,
)

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "SYNTHETIC_TOKEN_012"


def fixture(campaign=registry.Campaign.PROTOCOL, state="active"):
    return {
        "id": 10011 if campaign is registry.Campaign.PROTOCOL else 10012,
        "path": ".github/workflows/hoben-" + campaign.value + "-manual.yml",
        "state": state,
        "name": "SYNTHETIC_PRIVATE_INPUT",
        "node_id": "SYNTHETIC_PRIVATE_INPUT",
        "url": "https://private.invalid/SYNTHETIC_PRIVATE_INPUT",
        "html_url": "https://private.invalid/SYNTHETIC_PRIVATE_INPUT",
        "badge_url": "https://private.invalid/SYNTHETIC_PRIVATE_INPUT",
        "created_at": "2026-10-27T00:00:00Z",
        "updated_at": "2026-10-27T00:00:00Z",
        "deleted_at": None,
    }


class FakeReader:
    def __init__(self, responses=None):
        self.responses = (
            [Reply(200, fixture(), None)] * 2 if responses is None else responses
        )
        self.calls = []

    def get(self, path):
        index = len(self.calls)
        self.calls.append(path)
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in registry evidence tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def never_starts(result):
    assert (
        type(result) is registry.Observation
        and not result
        and result.can_start is False
    )
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert len(result.facts) == len(registry.FactName)
    assert all(
        type(f.name) is registry.FactName and type(f.state) is registry.State
        for f in result.facts
    )
    assert "SYNTHETIC_PRIVATE_INPUT" not in repr(result) and TOKEN not in repr(result)


def refused(result, error=None):
    never_starts(result)
    assert type(result.error) is registry.Error
    if error is not None:
        assert result.error is error
    assert all(f.state is registry.State.UNKNOWN for f in result.facts)
    assert result.reported_state is result._binding is result._campaign is None


@pytest.mark.parametrize("campaign", list(registry.Campaign))
@pytest.mark.parametrize("state", list(registry.WorkflowState))
def test_both_campaigns_all_known_states_are_only_reported_metadata(campaign, state):
    payload = fixture(campaign, state.value)
    pure = registry.validate_registry(campaign, payload)
    reader = FakeReader([Reply(200, payload, None)] * 2)
    result = registry.read_registry(reader, campaign)
    assert result.error is None and result == pure and result.reported_state is state
    never_starts(result)
    assert {f.name for f in result.facts if f.state is registry.State.ATTESTED} == {
        registry.FactName.ENTRY,
        registry.FactName.ID,
        registry.FactName.PATH,
        registry.FactName.STATE,
    }
    assert (
        reader.calls
        == [
            registry.PREFIX
            + "/actions/workflows/hoben-"
            + campaign.value
            + "-manual.yml"
        ]
        * 2
    )
    recheck = FakeReader([Reply(200, payload, None)] * 2)
    assert registry.read_registry(recheck, campaign, result) == result
    assert recheck.calls == reader.calls


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        10011,
        "protocol",
        "ha",
        "main",
        "refs/heads/experimental",
        ".github/workflows/hoben-protocol-manual.yml",
        "https://private.invalid/SYNTHETIC_PRIVATE_INPUT",
        {},
        [],
    ],
)
def test_no_free_id_name_ref_path_branch_url_or_selector_before_get(bad):
    reader = FakeReader()
    refused(registry.validate_registry(bad, fixture()), registry.Error.CAMPAIGN)
    refused(registry.read_registry(reader, bad), registry.Error.CAMPAIGN)
    assert reader.calls == []


@pytest.mark.parametrize(
    "field,bad,error",
    [
        ("id", True, registry.Error.ID),
        ("id", 0, registry.Error.ID),
        ("id", -1, registry.Error.ID),
        ("id", 2**53, registry.Error.ID),
        ("id", 1.0, registry.Error.ID),
        ("id", "10011", registry.Error.ID),
        ("id", None, registry.Error.ID),
        ("path", ".github/workflows/hoben-ha-manual.yml", registry.Error.PATH),
        ("path", "hoben-protocol-manual.yml", registry.Error.PATH),
        (
            "path",
            ".github/workflows/hoben-protocol-manual.yml@refs/heads/experimental",
            registry.Error.PATH,
        ),
        ("path", ".github/workflows/../hoben-protocol-manual.yml", registry.Error.PATH),
        ("path", True, registry.Error.PATH),
        ("path", None, registry.Error.PATH),
        ("state", "enabled", registry.Error.STATE),
        ("state", "ACTIVE", registry.Error.STATE),
        ("state", "unknown", registry.Error.STATE),
        ("state", True, registry.Error.STATE),
        ("state", None, registry.Error.STATE),
    ],
)
def test_ids_paths_and_states_must_be_explicit_and_strict(field, bad, error):
    payload = fixture()
    payload[field] = bad
    refused(registry.validate_registry(registry.Campaign.PROTOCOL, payload), error)


@pytest.mark.parametrize("field", ["id", "path", "state"])
def test_missing_required_field_never_inferred_from_name_or_git_presence(field):
    payload = fixture()
    payload["name"] = "hoben-protocol-manual.yml"
    del payload[field]
    refused(
        registry.validate_registry(registry.Campaign.PROTOCOL, payload),
        registry.Error.SHAPE,
    )


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        [],
        [fixture()],
        [fixture(), fixture()],
        "SYNTHETIC_PRIVATE_INPUT",
        b"PRIVATE",
    ],
)
def test_malformed_or_duplicate_collection_is_not_a_registry_entry(bad):
    refused(
        registry.validate_registry(registry.Campaign.PROTOCOL, bad),
        registry.Error.SHAPE,
    )


@pytest.mark.parametrize(
    "extra",
    [
        "workflows",
        "total_count",
        "truncated",
        "registered",
        "workflow_ref",
        "workflow_sha",
        "content",
        "can_start",
        "manager_reviewed",
    ],
)
def test_unknown_or_ambiguous_envelope_fields_are_refused(extra):
    payload = fixture()
    payload[extra] = "SYNTHETIC_PRIVATE_INPUT"
    refused(
        registry.validate_registry(registry.Campaign.PROTOCOL, payload),
        registry.Error.SHAPE,
    )


@pytest.mark.parametrize(
    "field", ["name", "node_id", "url", "created_at", "deleted_at"]
)
@pytest.mark.parametrize("bad", [True, 1, [], {}])
def test_optional_metadata_is_typed_and_bounded(field, bad):
    payload = fixture()
    payload[field] = bad
    refused(
        registry.validate_registry(registry.Campaign.PROTOCOL, payload),
        registry.Error.SHAPE,
    )


def test_total_metadata_limit_and_optional_string_bounds():
    payload = fixture()
    payload["url"] = "X" * 2049
    refused(
        registry.validate_registry(registry.Campaign.PROTOCOL, payload),
        registry.Error.SHAPE,
    )
    payload = fixture()
    payload.update(url="é" * 2048, html_url="é" * 2048, badge_url="é" * 2048)
    refused(
        registry.validate_registry(registry.Campaign.PROTOCOL, payload),
        registry.Error.SIZE,
    )
    minimal = {k: v for k, v in fixture().items() if k in {"id", "path", "state"}}
    assert registry.validate_registry(registry.Campaign.PROTOCOL, minimal).error is None

    payload = fixture()
    payload["name"] = "\ud800"
    refused(
        registry.validate_registry(registry.Campaign.PROTOCOL, payload),
        registry.Error.SHAPE,
    )


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "status,error",
    [
        (401, registry.Error.FORBIDDEN),
        (403, registry.Error.FORBIDDEN),
        (404, registry.Error.NOT_FOUND),
        (429, registry.Error.RATE_LIMIT),
        (500, registry.Error.API),
        (502, registry.Error.API),
        (503, registry.Error.API),
    ],
)
def test_missing_registration_or_http_errors_leave_all_facts_unknown(
    index, status, error
):
    responses = [Reply(200, fixture(), None)] * 2
    responses[index] = Reply(status, {"message": "SYNTHETIC_PRIVATE_INPUT"}, None)
    reader = FakeReader(responses)
    refused(registry.read_registry(reader, registry.Campaign.PROTOCOL), error)
    assert len(reader.calls) == index + 1


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "bad",
    [
        Reply(True, {}, None),
        Reply(200, None, None),
        Reply(200, fixture(), 2),
        RuntimeError("SYNTHETIC_PRIVATE_INPUT"),
    ],
)
def test_private_malformed_or_paginated_reply_discards_partial_proof(
    index, bad, capsys
):
    responses = [Reply(200, fixture(), None)] * 2
    responses[index] = bad
    refused(registry.read_registry(FakeReader(responses), registry.Campaign.PROTOCOL))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 20011),
        ("state", "disabled_manually"),
        ("name", "OTHER_SYNTHETIC_NAME"),
        ("url", "https://private.invalid/OTHER"),
        ("updated_at", "2026-10-27T00:01:00Z"),
        ("deleted_at", "2026-10-27T00:01:00Z"),
    ],
)
def test_any_accepted_metadata_change_between_reads_or_recheck_refuses(field, value):
    original, changed = fixture(), fixture()
    changed[field] = value
    previous = registry.read_registry(FakeReader(), registry.Campaign.PROTOCOL)
    reader = FakeReader([Reply(200, original, None), Reply(200, changed, None)])
    refused(
        registry.read_registry(reader, registry.Campaign.PROTOCOL),
        registry.Error.CHANGED,
    )
    reader = FakeReader([Reply(200, changed, None)] * 2)
    refused(
        registry.read_registry(reader, registry.Campaign.PROTOCOL, previous),
        registry.Error.CHANGED,
    )
    assert len(reader.calls) == 2


def test_recheck_different_campaign_or_invalid_previous_refuses_before_get():
    previous = registry.read_registry(FakeReader(), registry.Campaign.PROTOCOL)
    for bad in (
        True,
        {},
        registry.validate_registry(registry.Campaign.PROTOCOL, {}),
        replace(previous, facts=()),
        replace(previous, _binding=None),
    ):
        reader = FakeReader()
        refused(
            registry.read_registry(reader, registry.Campaign.PROTOCOL, bad),
            registry.Error.PREVIOUS,
        )
        assert reader.calls == []
    reader = FakeReader()
    refused(
        registry.read_registry(reader, registry.Campaign.HA, previous),
        registry.Error.PREVIOUS,
    )
    assert reader.calls == []


def test_json_object_order_does_not_change_metadata_binding():
    payload = fixture()
    reader = FakeReader(
        [Reply(200, payload, None), Reply(200, dict(reversed(payload.items())), None)]
    )
    assert registry.read_registry(reader, registry.Campaign.PROTOCOL).error is None


def test_optional_field_disappearance_is_not_silently_ignored():
    payload, changed = fixture(), fixture()
    del changed["name"]
    reader = FakeReader([Reply(200, payload, None), Reply(200, changed, None)])
    refused(
        registry.read_registry(reader, registry.Campaign.PROTOCOL),
        registry.Error.CHANGED,
    )


def test_projection_is_immutable_without_payload_url_name_or_raw_id():
    payload = fixture()
    result = registry.validate_registry(registry.Campaign.PROTOCOL, payload)
    never_starts(result)
    before = repr(result)
    payload["state"] = "deleted"
    payload["id"] = 20011
    assert (
        repr(result) == before
        and result.reported_state is registry.WorkflowState.ACTIVE
    )
    assert len(result._binding) == 64 and "10011" not in before
    with pytest.raises(FrozenInstanceError):
        result.can_start = True
    with pytest.raises(FrozenInstanceError):
        result.facts[0].state = registry.State.UNKNOWN
    with pytest.raises(TypeError):
        registry.Observation(result.facts, None, can_start=True)
    assert {f.name for f in fields(result)} == {
        "facts",
        "error",
        "reported_state",
        "_binding",
        "_campaign",
        "can_start",
        "execution",
        "actions_result",
    }


@pytest.mark.parametrize("campaign", list(registry.Campaign))
def test_exact_new_routes_work_only_via_injected_existing_transport(campaign):
    filename = "hoben-" + campaign.value + "-manual.yml"
    route = "/actions/workflows/" + filename
    http = FakeHTTP(payloads={route: fixture(campaign)})
    result = registry.read_registry(GitHubGETTransport(TOKEN, client=http), campaign)
    assert result.error is None
    never_starts(result)
    assert [c[0] for c in http.calls] == [
        "https://api.github.com" + registry.PREFIX + route
    ] * 2
    assert all(s.closed for s in http.streams)


@pytest.mark.parametrize(
    "suffix",
    [
        "/actions/workflows",
        "/actions/workflows/10011",
        "/actions/workflows/validate.yml",
        "/actions/workflows/hoben-manual.yml",
        "/actions/workflows/main",
        "/actions/workflows/hoben-protocol-manual.yaml",
        "/actions/workflows/hoben-protocol-manual.yml/enable",
        "/actions/workflows/hoben-ha-manual.yml/dispatches",
        "/actions/workflows/hoben-ha-manual.yml/runs",
        "/actions/workflows/../hoben-ha-manual.yml",
        "/actions/workflows/%68oben-ha-manual.yml",
        "/actions/workflows/hoben-ha-manual.yml?ref=main",
        "/actions/workflows/hoben-ha-manual.yml#fragment",
        "/actions/workflows/hoben-ha-manual.yml/",
        "/actions/workflows/.github%2fworkflows%2fhoben-ha-manual.yml",
        "/actions/secrets",
        "/branches/main",
        "/branches/experimental/protection",
    ],
)
def test_ids_free_names_paths_refs_urls_queries_and_activation_routes_refuse(suffix):
    http = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(registry.PREFIX + suffix)
    assert caught.value.code is Failure.REQUEST and http.calls == []


@pytest.mark.parametrize("campaign", list(registry.Campaign))
@pytest.mark.parametrize(
    "params", [{"page": 1}, {"per_page": 100}, {"page": 1, "per_page": 100}]
)
def test_workflow_routes_have_no_pagination_or_query(campaign, params):
    http = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(
            registry.PREFIX
            + "/actions/workflows/hoben-"
            + campaign.value
            + "-manual.yml",
            **params,
        )
    assert caught.value.code is Failure.REQUEST and http.calls == []


@pytest.mark.parametrize(
    "body", [b'{"id":', b'{"id":10011,"id":10012}', b'{"name":"SYNTHETIC_TOKEN_012"}']
)
def test_new_routes_keep_transport_truncation_duplicates_and_secret_echo_refusals(body):
    http = FakeHTTP(Stream(body))
    refused(
        registry.read_registry(
            GitHubGETTransport(TOKEN, client=http), registry.Campaign.PROTOCOL
        ),
        registry.Error.API,
    )
    assert len(http.calls) == 1 and http.stream.closed


def test_new_route_refuses_redirect_and_does_not_follow_body_url():
    http = FakeHTTP(
        Stream(status=302, headers=[("Location", "https://private.invalid/PRIVATE")])
    )
    refused(
        registry.read_registry(
            GitHubGETTransport(TOKEN, client=http), registry.Campaign.HA
        ),
        registry.Error.API,
    )
    assert len(http.calls) == 1 and http.stream.closed


def test_module_has_only_stdlib_and_no_runtime_consumer_io_backend_or_cli():
    path = ROOT / "scripts/github_campaign_actions_registry.py"
    parsed = ast.parse(path.read_text())
    imports = {
        n.module if isinstance(n, ast.ImportFrom) else alias.name
        for n in ast.walk(parsed)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for alias in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert imports == {
        "hashlib",
        "json",
        "re",
        "dataclasses",
        "enum",
        "types",
        "typing",
    }
    assert not any(
        isinstance(n, ast.Name)
        and n.id
        in {
            "open",
            "print",
            "input",
            "eval",
            "exec",
            "__import__",
            "environ",
            "getenv",
        }
        for n in ast.walk(parsed)
    )
    for folder in (".github", "scripts", "custom_components"):
        assert not any(
            "github_campaign_actions_registry" in p.read_text()
            for p in (ROOT / folder).rglob("*")
            if p != path and p.is_file() and p.suffix in {".py", ".cjs", ".yml"}
        )
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
