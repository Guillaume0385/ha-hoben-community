"""Synthetic Git metadata and HTTP only; DNS and sockets are forbidden."""

import ast
import copy
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest
from test_github_campaign_transport import FakeHTTP, Stream

import scripts.github_campaign_workflow_tree as tree
from scripts.github_campaign_evidence import Reply
from scripts.github_campaign_transport import (
    Failure,
    GitHubGETTransport,
    TransportFailure,
)

ROOT = Path(__file__).resolve().parents[1]
SHA, ROOT_SHA, GITHUB_SHA, WORKFLOWS_SHA, BLOB_SHA = (c * 40 for c in "abcde")
EXPECTED = tree.Expected(tree.Campaign.PROTOCOL, SHA)
TOKEN = "SYNTHETIC_TOKEN_010"
ROUTES = [
    tree.PREFIX,
    tree.PREFIX + "/git/commits/" + SHA,
    *[tree.PREFIX + "/git/trees/" + s for s in (ROOT_SHA, GITHUB_SHA, WORKFLOWS_SHA)],
]


def fixture(campaign=tree.Campaign.PROTOCOL):
    def entry(path, sha, mode="040000", kind="tree"):
        return {"path": path, "sha": sha, "mode": mode, "type": kind}

    def git_tree(sha, entry):
        return {"sha": sha, "truncated": False, "tree": [entry], "url": "PRIVATE_INPUT"}

    return [
        {
            "id": 1401398724,
            "full_name": "Guillaume0385/ha-hoben-community",
            "owner": {"id": 18246624, "login": "Guillaume0385", "type": "User"},
            "permissions": {"admin": True},
        },
        {"sha": SHA, "tree": {"sha": ROOT_SHA}, "message": "PRIVATE_INPUT"},
        git_tree(ROOT_SHA, entry(".github", GITHUB_SHA)),
        git_tree(GITHUB_SHA, entry("workflows", WORKFLOWS_SHA)),
        git_tree(
            WORKFLOWS_SHA,
            entry(
                "hoben-" + campaign.value + "-manual.yml", BLOB_SHA, "100644", "blob"
            ),
        ),
    ]


class FakeReader:
    def __init__(self, payloads=None, responses=None):
        self.responses = (
            [Reply(200, p, None) for p in (fixture() if payloads is None else payloads)]
            * 2
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
        raise AssertionError("Network forbidden in workflow tree tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def never_starts(result):
    assert type(result) is tree.Observation and result.can_start is False and not result
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert len(result.facts) == len(tree.FactName)
    assert all(
        type(f.name) is tree.FactName and type(f.state) is tree.State
        for f in result.facts
    )
    assert "PRIVATE_INPUT" not in repr(result) and TOKEN not in repr(result)


def refused(result, error=None):
    never_starts(result)
    assert type(result.error) is tree.Error
    if error is not None:
        assert result.error is error
    assert all(f.state is tree.State.UNKNOWN for f in result.facts)
    assert result._binding is result._expected is None
    assert result._blob is None


@pytest.mark.parametrize("campaign", list(tree.Campaign))
def test_both_paths_pure_double_get_and_recheck_attest_only_partial_facts(campaign):
    expected, payloads = tree.Expected(campaign, SHA), fixture(campaign)
    pure = tree.validate_workflow_tree(expected, *payloads)
    reader = FakeReader(payloads)
    result = tree.read_workflow_tree(reader, expected)
    assert result.error is pure.error is None and result._binding == pure._binding
    never_starts(result)
    assert {f.name for f in result.facts if f.state is tree.State.ATTESTED} == {
        tree.FactName.REPOSITORY,
        tree.FactName.COMMIT,
        tree.FactName.WORKFLOW_PATH,
        tree.FactName.BLOB,
    }
    assert reader.calls == ROUTES * 2
    reader = FakeReader(payloads)
    rechecked = tree.read_workflow_tree(reader, expected, result)
    assert rechecked == result and reader.calls == ROUTES * 2


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        {},
        replace(EXPECTED, campaign="protocol"),
        replace(EXPECTED, campaign=True),
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
def test_closed_independent_inputs_refuse_before_get(bad):
    reader = FakeReader()
    refused(tree.validate_workflow_tree(bad, *fixture()), tree.Error.EXPECTED)
    refused(tree.read_workflow_tree(reader, bad), tree.Error.EXPECTED)
    assert reader.calls == []
    if type(bad) is tree.Expected:
        assert "PRIVATE_INPUT" not in repr(bad)


@pytest.mark.parametrize(
    "index,path,value",
    [
        (0, ("id",), 1),
        (0, ("id",), True),
        (0, ("full_name",), "spoof/repo"),
        (0, ("owner", "id"), 1),
        (0, ("owner", "login"), "spoof"),
        (0, ("owner", "type"), "Bot"),
        (1, ("sha",), "f" * 40),
        (1, ("sha",), True),
        (1, ("tree",), None),
        (1, ("tree", "sha"), "0" * 40),
        (1, ("tree", "sha"), "PRIVATE_INPUT"),
        (2, ("sha",), "f" * 40),
        (3, ("sha",), ROOT_SHA),
        (4, ("sha",), GITHUB_SHA),
        (2, ("tree", 0, "sha"), "f" * 40),
        (3, ("tree", 0, "sha"), "f" * 40),
        (4, ("tree", 0, "sha"), "0" * 40),
        (4, ("tree", 0, "sha"), "E" * 40),
        (4, ("tree", 0, "sha"), None),
    ],
)
def test_identity_pin_and_chain_divergence_refuse_before_following_bad_data(
    index, path, value
):
    payloads = fixture()
    target = payloads[index]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    refused(tree.validate_workflow_tree(EXPECTED, *payloads))
    reader = FakeReader(payloads)
    refused(tree.read_workflow_tree(reader, EXPECTED))
    # Even a syntactically valid replacement SHA cannot silently change the chain.
    assert len(reader.calls) <= 5


@pytest.mark.parametrize("index", [2, 3, 4])
@pytest.mark.parametrize("bad", [True, None, 0, "false", "missing"])
def test_truncated_missing_or_approximate_completeness_refuses(index, bad):
    payloads = fixture()
    if bad == "missing":
        del payloads[index]["truncated"]
    else:
        payloads[index]["truncated"] = bad
    refused(tree.validate_workflow_tree(EXPECTED, *payloads), tree.Error.TRUNCATED)
    reader = FakeReader(payloads)
    refused(tree.read_workflow_tree(reader, EXPECTED), tree.Error.TRUNCATED)
    assert len(reader.calls) == index + 1


@pytest.mark.parametrize("index", [2, 3, 4])
@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "missing",
        "null",
        "not_list",
        "bad_entry",
        "symlink",
        "submodule",
        "mode_type",
        "exec_yaml_or_dir",
        "bad_sha",
        "encoded_name",
        "slash",
        "dotdot",
    ],
)
def test_tree_shape_names_types_modes_and_unique_components(index, case):
    payloads = fixture()
    p, e = payloads[index], payloads[index]["tree"][0]
    if case == "duplicate":
        p["tree"].append(copy.deepcopy(e))
    elif case == "missing":
        p["tree"] = []
    elif case == "null":
        p["tree"] = None
    elif case == "not_list":
        p["tree"] = {"PRIVATE_INPUT": e}
    elif case == "bad_entry":
        p["tree"].append(True)
    elif case == "symlink":
        e.update(mode="120000", type="blob")
    elif case == "submodule":
        e.update(mode="160000", type="commit")
    elif case == "mode_type":
        e["type"] = "blob" if index != 4 else "tree"
    elif case == "exec_yaml_or_dir":
        e.update(mode="100755", type="blob")
    elif case == "bad_sha":
        e["sha"] = True
    elif case == "encoded_name":
        e["path"] = "%2e" + e["path"]
    elif case == "slash":
        e["path"] = ".github/workflows"
    else:
        e["path"] = ".."
    refused(tree.validate_workflow_tree(EXPECTED, *payloads))
    reader = FakeReader(payloads)
    refused(tree.read_workflow_tree(reader, EXPECTED))
    assert len(reader.calls) == index + 1


def test_unrelated_entries_are_validated_too_and_regular_executable_sibling_is_safe():
    payloads = fixture()
    sibling = {"path": "helper", "mode": "100755", "type": "blob", "sha": "f" * 40}
    payloads[2]["tree"].append(sibling)
    assert tree.validate_workflow_tree(EXPECTED, *payloads).error is None
    for key, bad in (("mode", "120000"), ("sha", "0" * 40), ("path", "helper\x00")):
        p = copy.deepcopy(payloads)
        p[2]["tree"][1][key] = bad
        refused(tree.validate_workflow_tree(EXPECTED, *p))
    p = copy.deepcopy(payloads)
    p[2]["tree"].append(copy.deepcopy(sibling))
    refused(tree.validate_workflow_tree(EXPECTED, *p), tree.Error.ENTRY)


@pytest.mark.parametrize("field", ["path", "sha", "mode", "type"])
@pytest.mark.parametrize("bad", [None, True, 100644, [], {}])
def test_entry_required_fields_have_strict_json_types(field, bad):
    p = fixture()
    p[4]["tree"][0][field] = bad
    refused(tree.validate_workflow_tree(EXPECTED, *p), tree.Error.ENTRY)
    del p[4]["tree"][0][field]
    refused(tree.validate_workflow_tree(EXPECTED, *p), tree.Error.ENTRY)


def test_tree_metadata_count_bound_and_wrong_campaign_path():
    p = fixture()
    p[2]["tree"] = [p[2]["tree"][0]] * (tree.MAX_TREE_ENTRIES + 1)
    refused(tree.validate_workflow_tree(EXPECTED, *p), tree.Error.TREE)
    refused(
        tree.validate_workflow_tree(EXPECTED, *fixture(tree.Campaign.HA)),
        tree.Error.MISSING,
    )


@pytest.mark.parametrize("index", range(10))
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 502, 503])
def test_every_read_failure_discards_partial_facts_without_retry(index, status):
    responses = [Reply(200, p, None) for p in fixture()] * 2
    responses[index] = Reply(status, {"message": "PRIVATE_INPUT"}, None)
    reader = FakeReader(responses=responses)
    refused(tree.read_workflow_tree(reader, EXPECTED))
    assert reader.calls == (ROUTES * 2)[: index + 1]


@pytest.mark.parametrize(
    "response",
    [
        Reply(200, None, None),
        Reply(200, True, None),
        Reply(200, b"PRIVATE_INPUT", None),
        Reply(True, {}, None),
        Reply(200, {}, 2),
        RuntimeError("PRIVATE_INPUT"),
    ],
)
def test_malformed_private_or_paginated_response_has_only_closed_error(
    response, capsys
):
    reader = FakeReader(responses=[response])
    refused(tree.read_workflow_tree(reader, EXPECTED))
    assert len(reader.calls) == 1
    assert capsys.readouterr().out == capsys.readouterr().err == ""


@pytest.mark.parametrize("index", range(10))
def test_private_or_incomplete_read_discards_partial_facts(index):
    for bad in (RuntimeError("PRIVATE_INPUT"), Reply(200, {}, 2)):
        responses = [Reply(200, p, None) for p in fixture()] * 2
        responses[index] = bad
        reader = FakeReader(responses=responses)
        refused(tree.read_workflow_tree(reader, EXPECTED))
        assert reader.calls == (ROUTES * 2)[: index + 1]


def test_changed_blob_between_reads_or_since_previous_and_retarget_refused():
    prior = tree.read_workflow_tree(FakeReader(), EXPECTED)
    changed = fixture()
    changed[4]["tree"][0]["sha"] = "f" * 40
    responses = [Reply(200, p, None) for p in fixture() + changed]
    refused(
        tree.read_workflow_tree(FakeReader(responses=responses), EXPECTED),
        tree.Error.CHANGED,
    )
    refused(
        tree.read_workflow_tree(FakeReader(changed), EXPECTED, prior),
        tree.Error.CHANGED,
    )
    for pin in (
        replace(EXPECTED, sha="f" * 40),
        replace(EXPECTED, campaign=tree.Campaign.HA),
    ):
        reader = FakeReader()
        refused(tree.read_workflow_tree(reader, pin, prior), tree.Error.PREVIOUS)
        assert reader.calls == []
    for bad in (
        True,
        {"attested": True},
        tree.validate_workflow_tree(EXPECTED, *[{}] * 5),
    ):
        reader = FakeReader()
        refused(tree.read_workflow_tree(reader, EXPECTED, bad), tree.Error.PREVIOUS)
        assert reader.calls == []


def test_no_loaded_yaml_policy_or_dispatch_fact_is_inferred_from_added_fields():
    p = fixture()
    for payload in p:
        payload.update(
            protected=True,
            workflow_ref="PRIVATE_INPUT",
            registered=True,
            yaml="PRIVATE_INPUT",
            approved=True,
            can_start=True,
        )
    result = tree.validate_workflow_tree(EXPECTED, *p)
    assert result.error is None
    never_starts(result)
    assert all(
        f.state is tree.State.UNKNOWN
        for f in result.facts
        if f.name
        not in {
            tree.FactName.REPOSITORY,
            tree.FactName.COMMIT,
            tree.FactName.WORKFLOW_PATH,
            tree.FactName.BLOB,
        }
    )


def test_projection_is_immutable_and_retains_no_inputs_or_free_text():
    p = fixture()
    result = tree.validate_workflow_tree(EXPECTED, *p)
    before = repr(result)
    p[4]["tree"][0]["sha"] = "f" * 40
    p[0]["owner"]["login"] = "PRIVATE_INPUT"
    assert result.error is None and repr(result) == before
    assert len(result._binding) == len(result._expected) == 64
    with pytest.raises(FrozenInstanceError):
        result.can_start = True
    with pytest.raises(FrozenInstanceError):
        result.facts[0].state = tree.State.UNKNOWN
    with pytest.raises(TypeError):
        tree.Observation(result.facts, None, can_start=True)
    assert {f.name for f in fields(result)} == {
        "facts",
        "error",
        "_binding",
        "_expected",
        "_blob",
        "can_start",
        "execution",
        "actions_result",
    }


@pytest.mark.parametrize("campaign", list(tree.Campaign))
def test_existing_transport_traverses_metadata_only_and_closes_all_streams(campaign):
    payloads = {
        path[len(tree.PREFIX) :]: p
        for path, p in zip(ROUTES, fixture(campaign), strict=True)
    }
    http = FakeHTTP(payloads=payloads)
    result = tree.read_workflow_tree(
        GitHubGETTransport(TOKEN, client=http), tree.Expected(campaign, SHA)
    )
    assert result.error is None
    never_starts(result)
    assert [c[0] for c in http.calls] == [
        "https://api.github.com" + p for p in ROUTES * 2
    ]
    assert all(s.closed for s in http.streams)


@pytest.mark.parametrize(
    "suffix",
    [
        "/git/trees",
        "/git/trees/main",
        "/git/trees/experimental",
        "/git/trees/" + "0" * 40,
        "/git/trees/" + "A" * 40,
        "/git/trees/" + "a" * 39,
        "/git/trees/%61" + "a" * 39,
        "/git/trees/../" + ROOT_SHA,
        "/git/trees/" + ROOT_SHA + "?recursive=1",
        "/git/trees/" + ROOT_SHA + "?ref=main",
        "/git/trees/" + ROOT_SHA + "#fragment",
        "/git/trees/" + ROOT_SHA + "/",
        "/git/blobs/main",
        "/contents/.github/workflows/hoben-ha-manual.yml",
        "/branches/main",
        "/branches/feature",
        "/branches/experimental/protection",
        "/actions/workflows",
        "/actions/secrets",
        "/git/trees/" + ROOT_SHA + "%2fblob",
    ],
)
def test_free_encoded_query_neighbor_and_forbidden_routes_refuse_before_http(suffix):
    http = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(tree.PREFIX + suffix)
    assert caught.value.code is Failure.REQUEST and http.calls == []


@pytest.mark.parametrize(
    "params", [{"page": 1}, {"per_page": 100}, {"page": 1, "per_page": 100}]
)
def test_tree_route_rejects_pagination_parameters(params):
    http = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(ROUTES[2], **params)
    assert caught.value.code is Failure.REQUEST and http.calls == []


@pytest.mark.parametrize(
    "stream",
    [
        Stream(b'{"truncated":'),
        Stream(b'{"message":"SYNTHETIC_TOKEN_010"}'),
        Stream(
            status=302, headers=[("Location", "https://private.invalid/PRIVATE_INPUT")]
        ),
        Stream(
            b"{}",
            headers=[
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("Link", '<https://api.github.com/PRIVATE_INPUT>; rel="next"'),
            ],
        ),
    ],
)
def test_new_route_keeps_transport_truncation_secret_redirect_and_link_refusals(stream):
    http = FakeHTTP(stream)
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(ROUTES[2])
    assert TOKEN not in repr(caught.value) and "PRIVATE_INPUT" not in repr(caught.value)
    assert stream.closed and len(http.calls) == 1


def test_module_stdlib_only_no_runtime_caller_backend_io_env_or_cli():
    path = ROOT / "scripts/github_campaign_workflow_tree.py"
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
            "github_campaign_workflow_tree" in p.read_text()
            for p in (ROOT / folder).rglob("*")
            if p not in {path, ROOT / "scripts/github_campaign_workflow_blob.py"}
            and p.is_file()
            and p.suffix in {".py", ".cjs", ".yml"}
        )
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
