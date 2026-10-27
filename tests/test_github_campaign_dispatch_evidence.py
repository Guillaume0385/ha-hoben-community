"""Dispatch REST fixtures only: no dispatch, production credential or socket."""

import ast
import copy
import json
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from test_github_campaign_transport import FakeHTTP, Stream

import scripts.github_campaign_dispatch_evidence as dispatch
from scripts.github_campaign_evidence import Reply
from scripts.github_campaign_transport import GitHubGETTransport

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
# Synthetic workflow IDs are caller pins, never claimed to be installed IDs.
EXPECTED = dispatch.Expected(dispatch.Campaign.PROTOCOL, 810, 910, SHA)
PATHS = {
    dispatch.Campaign.PROTOCOL: ".github/workflows/hoben-protocol-manual.yml",
    dispatch.Campaign.HA: ".github/workflows/hoben-ha-manual.yml",
}


def owner():
    return {"id": 18246624, "login": "Guillaume0385", "type": "User"}


def repo():
    return {
        "id": 1401398724,
        "full_name": "Guillaume0385/ha-hoben-community",
        "owner": owner(),
    }


def payload(expected=EXPECTED):
    return {
        "id": expected.run_id,
        "event": "workflow_dispatch",
        "run_attempt": 1,
        "repository": repo(),
        "head_repository": repo(),
        "workflow_id": expected.workflow_id,
        "path": PATHS[expected.campaign],
        "head_sha": expected.sha,
        "head_branch": "experimental",
        "head_commit": {"id": expected.sha},
        "actor": owner(),
        "triggering_actor": owner(),
        "name": "PRIVATE_INPUT",
        "html_url": "https://private.invalid/PRIVATE_INPUT",
        "status": "queued",
        "conclusion": None,
    }


_DEFAULT = object()


class FakeReader:
    def __init__(self, first=_DEFAULT, second=_DEFAULT):
        self.first = Reply(200, payload(), None) if first is _DEFAULT else first
        self.second = self.first if second is _DEFAULT else second
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        response = self.first if len(self.calls) == 1 else self.second
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in dispatch facts tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def never_starts(result):
    assert type(result) is dispatch.Observation
    assert result.can_start is False and not result
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert "PRIVATE_INPUT" not in repr(result)
    assert "SYNTHETIC_TOKEN" not in repr(result)
    assert all(
        type(f.name) is dispatch.FactName and type(f.state) is dispatch.State
        for f in result.facts
    )


def refused(result, error=None):
    never_starts(result)
    assert result.error is not None
    if error is not None:
        assert result.error is error
    assert all(f.state is dispatch.State.UNKNOWN for f in result.facts)


def mutate(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


@pytest.mark.parametrize("campaign", tuple(dispatch.Campaign))
@pytest.mark.parametrize("suffix", ["", "@refs/heads/experimental"])
def test_pure_and_reader_positive_are_partial_and_never_authorize(campaign, suffix):
    expected = replace(EXPECTED, campaign=campaign)
    p = payload(expected)
    p["path"] += suffix
    pure = dispatch.validate_dispatch(expected, p)
    reader = FakeReader(Reply(200, p, None))
    observed = dispatch.read_dispatch(reader, expected)
    assert pure.error is observed.error is None
    assert pure.facts == observed.facts and pure._binding == observed._binding
    never_starts(pure)
    never_starts(observed)
    assert reader.calls == [dispatch.PREFIX + "/actions/runs/810"] * 2
    proven = {f.name for f in observed.facts if f.state is dispatch.State.ATTESTED}
    assert proven == {
        dispatch.FactName.REPOSITORY,
        dispatch.FactName.RUN_ID,
        dispatch.FactName.EVENT,
        dispatch.FactName.ATTEMPT,
        dispatch.FactName.WORKFLOW,
        dispatch.FactName.RUN_SHA,
        dispatch.FactName.BRANCH_NAME,
        dispatch.FactName.ACTOR,
        dispatch.FactName.TRIGGERING_ACTOR,
    }
    assert len(observed.facts) == len(dispatch.FactName)


def test_closed_campaigns_correspond_to_inert_yaml_and_cannot_be_mutated():
    assert {c.value for c in dispatch.Campaign} == {"protocol", "ha"}
    for campaign, path in PATHS.items():
        data = yaml.load((ROOT / path).read_text(), Loader=yaml.BaseLoader)
        assert set(data["on"]) == {"workflow_dispatch"}
        assert "not-activated" in data["jobs"]
        assert dispatch._PATHS[campaign] == path
    with pytest.raises(TypeError):
        dispatch._PATHS[dispatch.Campaign.HA] = ".github/workflows/hoben-manual.yml"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        {},
        replace(EXPECTED, campaign="protocol"),
        replace(EXPECTED, run_id=True),
        replace(EXPECTED, run_id=0),
        replace(EXPECTED, run_id=2**53),
        replace(EXPECTED, workflow_id=True),
        replace(EXPECTED, workflow_id=-1),
        replace(EXPECTED, sha="PRIVATE_INPUT"),
        replace(EXPECTED, sha="0" * 40),
        replace(EXPECTED, sha="A" * 40),
        replace(EXPECTED, target_ref="refs/heads/main"),
    ],
)
def test_invalid_expected_or_main_ref_refuses_before_reader(bad):
    reader = FakeReader()
    refused(dispatch.validate_dispatch(bad, payload()), dispatch.Error.EXPECTED)
    refused(dispatch.read_dispatch(reader, bad), dispatch.Error.EXPECTED)
    assert reader.calls == []
    if type(bad) is dispatch.Expected:
        assert "PRIVATE_INPUT" not in repr(bad)


@pytest.mark.parametrize(
    "path,value",
    [
        (("id",), 811),
        (("id",), True),
        (("event",), "pull_request"),
        (("event",), "push"),
        (("run_attempt",), 2),
        (("run_attempt",), True),
        (("repository", "id"), 1),
        (("repository", "full_name"), "spoof/repo"),
        (("repository", "owner", "id"), 1),
        (("repository", "owner", "login"), "spoof"),
        (("head_repository", "id"), 1),
        (("head_repository", "owner", "type"), "Bot"),
        (("workflow_id",), 911),
        (("workflow_id",), True),
        (("path",), ".github/workflows/hoben-manual.yml"),
        (("path",), PATHS[dispatch.Campaign.HA]),
        (("path",), PATHS[dispatch.Campaign.PROTOCOL] + "@refs/heads/main"),
        (("path",), "PRIVATE_INPUT"),
        (("head_sha",), "b" * 40),
        (("head_branch",), "main"),
        (("head_branch",), "refs/heads/experimental"),
        (("head_commit", "id"), "b" * 40),
        (("actor", "id"), 1),
        (("actor", "login"), "spoof"),
        (("actor", "type"), "Bot"),
        (("triggering_actor", "id"), 1),
        (("triggering_actor", "login"), "spoof"),
        (("triggering_actor", "type"), "Bot"),
    ],
)
def test_inconsistent_run_identity_sha_actor_workflow_or_ref_refuses(path, value):
    p = payload()
    mutate(p, path, value)
    refused(dispatch.validate_dispatch(EXPECTED, p))
    reader = FakeReader(Reply(200, p, None))
    refused(dispatch.read_dispatch(reader, EXPECTED))
    assert len(reader.calls) == 1


def test_every_required_field_absent_null_or_boolean_is_refused_not_inferred():
    original = payload()
    for path in (
        (),
        ("repository",),
        ("head_repository",),
        ("repository", "owner"),
        ("head_commit",),
        ("actor",),
        ("triggering_actor",),
    ):
        record = original
        for key in path:
            record = record[key]
        for key in record:
            if key in {"name", "html_url", "status", "conclusion"}:
                continue
            for bad in (None, True, "missing"):
                p = copy.deepcopy(original)
                target = p
                for part in path:
                    target = target[part]
                if bad == "missing":
                    del target[key]
                else:
                    target[key] = bad
                refused(dispatch.validate_dispatch(EXPECTED, p))
    p = payload()
    del p["triggering_actor"]
    p["triggering_actor_attested"] = True
    refused(dispatch.validate_dispatch(EXPECTED, p))


def test_unsupported_attestations_and_forged_rest_fields_remain_unknown():
    p = payload()
    p.update(
        attested=True,
        workflow_ref="PRIVATE_INPUT",
        workflow_sha=SHA,
        sender=owner(),
        inputs={"scenario": "all"},
        protected=True,
        environment_approved=True,
        manager_reviewed=True,
        claim=True,
        mutex=True,
        anti_replay=True,
        main_authorized=True,
    )
    result = dispatch.validate_dispatch(EXPECTED, p)
    assert result.error is None
    never_starts(result)
    for name in (
        "WORKFLOW_REF",
        "WORKFLOW_SHA",
        "WORKFLOW_CONTENT",
        "SENDER",
        "RUNNER",
        "SCENARIO",
        "BRANCH_HEAD",
        "PROTECTION",
        "ENVIRONMENT",
        "MANAGER_REVIEW",
        "CLAIM",
        "MUTEX",
        "REPLAY",
        "POST_APPROVAL",
        "UI_MAIN",
        "PR_CI",
        "AUTHORIZATION",
    ):
        assert (
            next(f.state for f in result.facts if f.name.name == name)
            is dispatch.State.UNKNOWN
        )


@pytest.mark.parametrize(
    "status,category",
    [
        (401, dispatch.Error.FORBIDDEN),
        (403, dispatch.Error.FORBIDDEN),
        (404, dispatch.Error.NOT_FOUND),
        (429, dispatch.Error.RATE_LIMIT),
        (500, dispatch.Error.API),
        (502, dispatch.Error.API),
        (503, dispatch.Error.API),
        (301, dispatch.Error.API),
    ],
)
@pytest.mark.parametrize("second", [False, True])
def test_http_error_first_or_second_read_never_keeps_partial_facts(
    status, category, second
):
    good = Reply(200, payload(), None)
    bad = Reply(status, {"body": "PRIVATE_INPUT SYNTHETIC_TOKEN"}, None)
    reader = FakeReader(good if second else bad, bad)
    refused(dispatch.read_dispatch(reader, EXPECTED), category)
    assert len(reader.calls) == (2 if second else 1)


@pytest.mark.parametrize(
    "response",
    [
        None,
        True,
        {},
        SimpleNamespace(status=True, next_page=None, data=payload()),
        Reply(200, b'{"truncated":', None),
        Reply(200, [], None),
        Reply(200, True, None),
        Reply(200, None, None),
        Reply(200, {"attested": True}, None),
        Reply(200, payload(), 2),
        Reply(200, payload(), False),
        Reply(200, payload(), "PRIVATE_INPUT"),
        RuntimeError("PRIVATE_INPUT SYNTHETIC_TOKEN"),
        json.JSONDecodeError("PRIVATE_INPUT", "SYNTHETIC_TOKEN", 0),
    ],
)
def test_malformed_truncated_paginated_or_private_exception_refuses(response, capsys):
    refused(dispatch.read_dispatch(FakeReader(response), EXPECTED))
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "path,value",
    [
        (("id",), 811),
        (("run_attempt",), 2),
        (("head_sha",), "b" * 40),
        (("actor", "id"), 1),
        (("triggering_actor", "login"), "spoof"),
        (("workflow_id",), 911),
        (("head_branch",), "main"),
        (("path",), PATHS[dispatch.Campaign.PROTOCOL] + "@refs/heads/experimental"),
    ],
)
def test_changed_facts_between_two_distinct_reads_refuse(path, value):
    first, second = payload(), payload()
    mutate(second, path, value)
    reader = FakeReader(Reply(200, first, None), Reply(200, second, None))
    result = dispatch.read_dispatch(reader, EXPECTED)
    refused(result)
    if path == ("path",):
        assert result.error is dispatch.Error.CHANGED
    assert len(reader.calls) == 2


def test_only_dispatch_facts_are_bound_status_progress_is_never_scenario_success():
    first, second = payload(), payload()
    second.update(status="completed", conclusion="success", updated_at="PRIVATE_INPUT")
    reader = FakeReader(Reply(200, first, None), Reply(200, second, None))
    result = dispatch.read_dispatch(reader, EXPECTED)
    assert result.error is None
    never_starts(result)
    assert (
        next(f.state for f in result.facts if f.name is dispatch.FactName.RUN_RESULT)
        is dispatch.State.UNKNOWN
    )


def test_observation_frozen_no_input_references_or_permission_constructor():
    p = payload()
    result = dispatch.validate_dispatch(EXPECTED, p)
    before = repr(result)
    p["actor"]["login"] = "PRIVATE_INPUT"
    assert result.error is None and repr(result) == before
    assert len(result._binding) == len(result._expected) == 64
    with pytest.raises(FrozenInstanceError):
        result.can_start = True
    with pytest.raises(FrozenInstanceError):
        result.facts[0].state = dispatch.State.UNKNOWN
    with pytest.raises(TypeError):
        dispatch.Observation(result.facts, None, can_start=True)
    assert {f.name for f in fields(result)} == {
        "facts",
        "error",
        "_binding",
        "_expected",
        "can_start",
        "execution",
        "actions_result",
    }


def test_recheck_rereads_and_pins_expected_ids_and_all_attested_facts():
    first = dispatch.read_dispatch(FakeReader(), EXPECTED)
    reader = FakeReader()
    second = dispatch.read_dispatch(reader, EXPECTED, first)
    assert (
        second.error is None
        and second._binding == first._binding
        and len(reader.calls) == 2
    )
    never_starts(second)
    changed = payload()
    changed["path"] += "@refs/heads/experimental"
    refused(
        dispatch.read_dispatch(FakeReader(Reply(200, changed, None)), EXPECTED, first),
        dispatch.Error.CHANGED,
    )
    for bad in (True, {"attested": True}, dispatch.validate_dispatch(EXPECTED, {})):
        reader = FakeReader()
        refused(dispatch.read_dispatch(reader, EXPECTED, bad), dispatch.Error.PREVIOUS)
        assert reader.calls == []
    reader = FakeReader()
    refused(
        dispatch.read_dispatch(reader, replace(EXPECTED, workflow_id=911), first),
        dispatch.Error.PREVIOUS,
    )
    assert reader.calls == []


def test_compatible_with_existing_http_transport_without_backend_import_or_new_route():
    fake = FakeHTTP(payloads={"/actions/runs/810": payload()})
    reader = GitHubGETTransport("SYNTHETIC_TOKEN_008", client=fake)
    result = dispatch.read_dispatch(reader, EXPECTED)
    assert result.error is None and len(fake.calls) == 2
    assert all(
        c[0] == "https://api.github.com" + dispatch.PREFIX + "/actions/runs/810"
        for c in fake.calls
    )
    assert all(s.closed for s in fake.streams)
    never_starts(result)
    fake = FakeHTTP(Stream(b'{"truncated":'))
    refused(
        dispatch.read_dispatch(
            GitHubGETTransport("SYNTHETIC_TOKEN_008", client=fake), EXPECTED
        ),
        dispatch.Error.API,
    )
    assert len(fake.calls) == 1 and fake.stream.closed


def test_pure_imports_no_network_environment_io_or_live_caller_and_silent_cli_refusal():
    path = ROOT / "scripts/github_campaign_dispatch_evidence.py"
    tree = ast.parse(path.read_text())
    imports = {
        n.module if isinstance(n, ast.ImportFrom) else alias.name
        for n in ast.walk(tree)
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
        in {"open", "print", "input", "eval", "exec", "__import__", "environ", "getenv"}
        for n in ast.walk(tree)
    )
    for folder in (".github", "scripts", "custom_components"):
        assert not any(
            "github_campaign_dispatch_evidence" in p.read_text()
            for p in (ROOT / folder).rglob("*")
            if p != path and p.is_file() and p.suffix in {".py", ".cjs", ".yml"}
        )
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
