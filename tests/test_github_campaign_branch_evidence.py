"""Only synthetic branch/repository responses, with DNS and sockets forbidden."""

import ast
import copy
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_github_campaign_transport import FakeHTTP, Stream

import scripts.github_campaign_branch_evidence as branch
from scripts.github_campaign_dispatch_evidence import (
    Campaign,
    validate_dispatch,
)
from scripts.github_campaign_dispatch_evidence import (
    Expected as DispatchExpected,
)
from scripts.github_campaign_evidence import Reply
from scripts.github_campaign_transport import (
    Failure,
    GitHubGETTransport,
    TransportFailure,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
EXPECTED = branch.Expected(SHA)
TOKEN = "SYNTHETIC_TOKEN_009"


def repository():
    return {
        "id": 1401398724,
        "full_name": "Guillaume0385/ha-hoben-community",
        "owner": {"id": 18246624, "login": "Guillaume0385", "type": "User"},
        "permissions": {"admin": True},
        "description": "PRIVATE_INPUT",
    }


def payload():
    return {
        "name": "experimental",
        "commit": {"sha": SHA, "url": "PRIVATE_INPUT"},
        "protected": True,
        "protection_url": "https://private.invalid/PRIVATE_INPUT",
    }


class FakeReader:
    def __init__(self, responses=None):
        self.responses = (
            [Reply(200, repository(), None), Reply(200, payload(), None)] * 2
            if responses is None
            else responses
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
        raise AssertionError("Network forbidden in branch evidence tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def never_starts(result):
    assert (
        type(result) is branch.Observation and result.can_start is False and not result
    )
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert all(
        type(f.name) is branch.FactName and type(f.state) is branch.State
        for f in result.facts
    )
    assert "PRIVATE_INPUT" not in repr(result) and TOKEN not in repr(result)


def refused(result, error=None):
    never_starts(result)
    assert result.error is not None
    if error is not None:
        assert result.error is error
    assert all(f.state is branch.State.UNKNOWN for f in result.facts)


def mutate(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


def test_positive_pure_and_reader_attest_only_repo_branch_and_head():
    pure = branch.validate_branch(EXPECTED, repository(), payload())
    reader = FakeReader()
    result = branch.read_branch(reader, EXPECTED)
    assert result.error is pure.error is None and result._binding == pure._binding
    never_starts(result)
    assert {f.name for f in result.facts if f.state is branch.State.ATTESTED} == {
        branch.FactName.REPOSITORY,
        branch.FactName.BRANCH_NAME,
        branch.FactName.HEAD,
    }
    assert len(result.facts) == len(branch.FactName)
    assert reader.calls == [branch.PREFIX, branch.BRANCH_ROUTE] * 2


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        {},
        DispatchExpected(Campaign.HA, 1, 2, SHA),
        replace(EXPECTED, repository="PRIVATE_INPUT"),
        replace(EXPECTED, repository=True),
        replace(EXPECTED, ref="refs/heads/main"),
        replace(EXPECTED, ref="experimental"),
        replace(EXPECTED, ref=True),
        replace(EXPECTED, sha="0" * 40),
        replace(EXPECTED, sha="A" * 40),
        replace(EXPECTED, sha="a" * 39),
        replace(EXPECTED, sha=True),
        replace(EXPECTED, sha="PRIVATE_INPUT"),
    ],
)
def test_expected_inputs_strict_main_and_wrong_repo_refused_before_get(bad):
    reader = FakeReader()
    refused(branch.validate_branch(bad, repository(), payload()), branch.Error.EXPECTED)
    refused(branch.read_branch(reader, bad), branch.Error.EXPECTED)
    assert reader.calls == []
    if type(bad) is branch.Expected:
        assert "PRIVATE_INPUT" not in repr(bad)


@pytest.mark.parametrize(
    "path,value",
    [
        (("id",), 1),
        (("id",), True),
        (("full_name",), "spoof/repo"),
        (("owner", "id"), 1),
        (("owner", "login"), "spoof"),
        (("owner", "type"), "Bot"),
    ],
)
def test_repository_identity_verified_via_existing_get_not_branch_url(path, value):
    repo = repository()
    mutate(repo, path, value)
    reader = FakeReader([Reply(200, repo, None)])
    refused(branch.read_branch(reader, EXPECTED))
    assert reader.calls == [branch.PREFIX]
    refused(branch.validate_branch(EXPECTED, repo, payload()))


@pytest.mark.parametrize(
    "path,value",
    [
        (("name",), "main"),
        (("name",), "refs/heads/experimental"),
        (("name",), True),
        (("commit", "sha"), "b" * 40),
        (("commit", "sha"), True),
        (("commit",), None),
    ],
)
def test_branch_name_and_exact_pinned_sha_required(path, value):
    p = payload()
    mutate(p, path, value)
    reader = FakeReader([Reply(200, repository(), None), Reply(200, p, None)])
    refused(branch.read_branch(reader, EXPECTED))
    assert reader.calls == [branch.PREFIX, branch.BRANCH_ROUTE]
    refused(branch.validate_branch(EXPECTED, repository(), p))


def test_missing_null_or_boolean_required_fields_never_have_safe_defaults():
    original = {"repo": repository(), "branch": payload()}
    for path, keys in (
        (("repo",), ("id", "full_name", "owner")),
        (("repo", "owner"), ("id", "login", "type")),
        (("branch",), ("name", "commit")),
        (("branch", "commit"), ("sha",)),
    ):
        for key in keys:
            for action in ("missing", "null", "bool"):
                current = copy.deepcopy(original)
                target = current
                for part in path:
                    target = target[part]
                if action == "missing":
                    del target[key]
                else:
                    target[key] = None if action == "null" else True
                refused(
                    branch.validate_branch(EXPECTED, current["repo"], current["branch"])
                )


@pytest.mark.parametrize("protected", [True, False, None, "PRIVATE_INPUT"])
def test_protected_and_other_claims_never_attest_effective_policy(protected):
    p = payload()
    p.update(
        protected=protected,
        protection={"required_checks": "PRIVATE_INPUT"},
        manager_reviewed=True,
        environment_approved=True,
        workflow_ref="PRIVATE_INPUT",
        workflow_sha=SHA,
        claim=True,
        mutex=True,
        anti_replay=True,
        atomic=True,
    )
    result = branch.validate_branch(EXPECTED, repository(), p)
    assert result.error is None
    never_starts(result)
    assert {f.name for f in result.facts if f.state is branch.State.ATTESTED} == {
        branch.FactName.REPOSITORY,
        branch.FactName.BRANCH_NAME,
        branch.FactName.HEAD,
    }


def test_run_reported_sha_and_protected_do_not_substitute_for_commit_sha():
    wrong = {
        "name": "experimental",
        "head_sha": SHA,
        "head_commit": {"id": SHA},
        "protected": True,
    }
    refused(branch.validate_branch(EXPECTED, repository(), wrong))
    dispatch_observation = validate_dispatch(
        DispatchExpected(Campaign.HA, 1, 2, SHA), {}
    )
    reader = FakeReader()
    refused(
        branch.read_branch(reader, EXPECTED, dispatch_observation),
        branch.Error.PREVIOUS,
    )
    assert reader.calls == []


@pytest.mark.parametrize(
    "status,error",
    [
        (401, branch.Error.FORBIDDEN),
        (403, branch.Error.FORBIDDEN),
        (404, branch.Error.NOT_FOUND),
        (429, branch.Error.RATE_LIMIT),
        (500, branch.Error.API),
        (502, branch.Error.API),
        (503, branch.Error.API),
    ],
)
@pytest.mark.parametrize("position", range(4))
def test_failure_at_each_of_four_gets_discards_all_facts_no_retry(
    status, error, position
):
    reader = FakeReader()
    reader.responses = list(reader.responses)
    reader.responses[position] = Reply(
        status, {"message": "PRIVATE_INPUT " + TOKEN}, None
    )
    refused(branch.read_branch(reader, EXPECTED), error)
    assert len(reader.calls) == position + 1


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        {},
        SimpleNamespace(status=True, data={}, next_page=None),
        Reply(200, None, None),
        Reply(200, [], None),
        Reply(200, True, None),
        Reply(200, b'{"truncated":', None),
        Reply(200, {"attested": True}, None),
        RuntimeError("PRIVATE_INPUT " + TOKEN),
    ],
)
def test_malformed_responses_or_private_exception_refuse(bad, capsys):
    refused(branch.read_branch(FakeReader([bad]), EXPECTED))
    refused(
        branch.read_branch(FakeReader([Reply(200, repository(), None), bad]), EXPECTED)
    )
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("next_page", [2, False, "PRIVATE_INPUT"])
def test_single_object_pagination_metadata_must_be_none(next_page):
    reader = FakeReader(
        [Reply(200, repository(), None), Reply(200, payload(), next_page)]
    )
    refused(branch.read_branch(reader, EXPECTED), branch.Error.PAGINATION)


def test_head_moved_between_reads_or_since_previous_is_refused():
    moved = payload()
    moved["commit"]["sha"] = "b" * 40
    reader = FakeReader()
    reader.responses = list(reader.responses)
    reader.responses[3] = Reply(200, moved, None)
    refused(branch.read_branch(reader, EXPECTED), branch.Error.HEAD)
    assert len(reader.calls) == 4
    previous = branch.read_branch(FakeReader(), EXPECTED)
    reader = FakeReader([Reply(200, repository(), None), Reply(200, moved, None)])
    refused(branch.read_branch(reader, EXPECTED, previous), branch.Error.HEAD)
    assert len(reader.calls) == 2
    reader = FakeReader()
    refused(
        branch.read_branch(reader, replace(EXPECTED, sha="b" * 40), previous),
        branch.Error.PREVIOUS,
    )
    assert reader.calls == []


def test_recheck_rereads_identity_and_head_without_attesting_policy_or_atomicity():
    previous = branch.read_branch(FakeReader(), EXPECTED)
    changed_policy = payload()
    changed_policy["protected"] = False
    reader = FakeReader(
        [Reply(200, repository(), None), Reply(200, changed_policy, None)] * 2
    )
    result = branch.read_branch(reader, EXPECTED, previous)
    assert result.error is None and result._binding == previous._binding
    assert len(reader.calls) == 4
    never_starts(result)
    for name in (
        branch.FactName.PROTECTION,
        branch.FactName.ATOMICITY,
        branch.FactName.FRESHNESS,
        branch.FactName.POST_APPROVAL,
    ):
        assert (
            next(f.state for f in result.facts if f.name is name)
            is branch.State.UNKNOWN
        )
    for bad in (True, {"attested": True}, branch.validate_branch(EXPECTED, {}, {})):
        reader = FakeReader()
        refused(branch.read_branch(reader, EXPECTED, bad), branch.Error.PREVIOUS)
        assert reader.calls == []


def test_recheck_refuses_a_different_binding_despite_matching_expected_pin():
    previous = branch.read_branch(FakeReader(), EXPECTED)
    changed = replace(previous, _binding="c" * 64)
    reader = FakeReader()
    refused(branch.read_branch(reader, EXPECTED, changed), branch.Error.CHANGED)
    assert len(reader.calls) == 4


def test_immutable_projection_retains_no_payload_or_free_url():
    repo, p = repository(), payload()
    result = branch.validate_branch(EXPECTED, repo, p)
    before = repr(result)
    repo["owner"]["login"] = "PRIVATE_INPUT"
    p["commit"]["sha"] = "b" * 40
    assert result.error is None and repr(result) == before
    assert len(result._expected) == len(result._binding) == 64
    with pytest.raises(FrozenInstanceError):
        result.can_start = True
    with pytest.raises(FrozenInstanceError):
        result.facts[0].state = branch.State.UNKNOWN
    with pytest.raises(TypeError):
        branch.Observation(result.facts, None, can_start=True)
    assert {f.name for f in fields(result)} == {
        "facts",
        "error",
        "_binding",
        "_expected",
        "can_start",
        "execution",
        "actions_result",
    }


def test_exact_new_route_works_with_existing_transport_no_pagination_or_redirect():
    fake = FakeHTTP(payloads={"": repository(), "/branches/experimental": payload()})
    reader = GitHubGETTransport(TOKEN, client=fake)
    result = branch.read_branch(reader, EXPECTED)
    assert result.error is None and len(fake.calls) == 4
    assert [c[0] for c in fake.calls] == [
        "https://api.github.com" + p for p in [branch.PREFIX, branch.BRANCH_ROUTE] * 2
    ]
    assert all(s.closed for s in fake.streams)
    never_starts(result)
    fake = FakeHTTP(Stream(b'{"truncated":'))
    with pytest.raises(TransportFailure):
        GitHubGETTransport(TOKEN, client=fake).get(branch.BRANCH_ROUTE)
    assert fake.stream.closed
    fake = FakeHTTP(
        Stream(
            status=302, headers=[("Location", "https://private.invalid/PRIVATE_INPUT")]
        )
    )
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=fake).get(branch.BRANCH_ROUTE)
    assert (
        caught.value.code is Failure.REDIRECT
        and len(fake.calls) == 1
        and fake.stream.closed
    )


@pytest.mark.parametrize(
    "suffix",
    [
        "/branches",
        "/branches/main",
        "/branches/feature",
        "/branches/Experimental",
        "/branches/experimental/",
        "/branches/experimental/protection",
        "/branches/experimental/protection/required_status_checks",
        "/branches/experimental?ref=main",
        "/branches/experimental#fragment",
        "/branches/%65xperimental",
        "/branches/../experimental",
        "/branches/experimental%2fprotection",
    ],
)
def test_arbitrary_main_protection_encoded_or_free_query_routes_refused(suffix):
    fake = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=fake).get(branch.PREFIX + suffix)
    assert caught.value.code is Failure.REQUEST and fake.calls == []


@pytest.mark.parametrize(
    "params", [{"page": 1}, {"per_page": 100}, {"page": 1, "per_page": 100}]
)
def test_branch_route_rejects_pagination_parameters(params):
    fake = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=fake).get(branch.BRANCH_ROUTE, **params)
    assert caught.value.code is Failure.REQUEST and fake.calls == []


def test_module_has_no_backend_env_clock_io_cli_or_runtime_caller():
    path = ROOT / "scripts/github_campaign_branch_evidence.py"
    tree = ast.parse(path.read_text())
    imports = {
        n.module if isinstance(n, ast.ImportFrom) else alias.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for alias in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert imports == {"hashlib", "json", "re", "dataclasses", "enum", "typing"}
    assert not any(
        isinstance(n, ast.Name)
        and n.id
        in {"open", "print", "input", "eval", "exec", "__import__", "environ", "getenv"}
        for n in ast.walk(tree)
    )
    for folder in (".github", "scripts", "custom_components"):
        assert not any(
            "github_campaign_branch_evidence" in p.read_text()
            for p in (ROOT / folder).rglob("*")
            if p != path and p.is_file() and p.suffix in {".py", ".cjs", ".yml"}
        )
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
