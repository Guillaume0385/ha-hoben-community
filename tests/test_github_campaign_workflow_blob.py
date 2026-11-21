"""Shared Git Blob transport/tree guards after removal of the unused reader."""

import ast
import base64
import hashlib
import socket
from pathlib import Path

import pytest
from test_github_campaign_transport import FakeHTTP, Stream
from test_github_campaign_workflow_tree import fixture as tree_fixture

import scripts.github_campaign_workflow_tree as tree
from scripts.github_campaign_evidence import Reply
from scripts.github_campaign_transport import (
    Failure,
    GitHubGETTransport,
    TransportFailure,
)

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
CONTENT = b"name: SYNTHETIC_PRIVATE_INPUT\non: workflow_dispatch\n"
TOKEN = "SYNTHETIC_TOKEN_011"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in blob evidence tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def test_removed_blob_reader_has_no_operational_entry_point():
    """Keep transport/tree guards without reinstating an unused byte reader."""
    assert not (ROOT / "scripts/github_campaign_workflow_blob.py").exists()
    for folder in ("scripts", "custom_components"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [node.module or "", *(part.name for part in node.names)]
                    if isinstance(node, ast.ImportFrom)
                    else [part.name for part in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                assert not any(
                    "github_campaign_workflow_blob" in name for name in names
                )
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        assert "github_campaign_workflow_blob" not in path.read_text()
    assert "github_campaign_workflow_blob" not in (ROOT / "pyproject.toml").read_text()


def git_sha(data):
    return hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False
    ).hexdigest()


@pytest.mark.parametrize("campaign", list(tree.Campaign))
def test_transport_authenticates_tree_then_fetches_only_selected_blob(campaign):
    sha = git_sha(CONTENT)
    metadata = tree_fixture(campaign)
    metadata[4]["tree"][0]["sha"] = sha
    paths = ["", "/git/commits/" + COMMIT, *["/git/trees/" + c * 40 for c in "bcd"]]
    payloads = dict(zip(paths, metadata, strict=True))
    payload = {
        "sha": sha,
        "size": len(CONTENT),
        "encoding": "base64",
        "content": base64.encodebytes(CONTENT).decode(),
    }
    blob_path = "/git/blobs/" + sha
    payloads[blob_path] = payload
    http = FakeHTTP(payloads=payloads)
    reader = GitHubGETTransport(TOKEN, client=http)
    expected = tree.Expected(campaign, COMMIT)
    proof = tree.read_workflow_tree(reader, expected)
    assert proof.error is None
    selected = tree.blob_identity(proof, expected)
    assert selected is not None and selected.sha == sha
    result = reader.get(tree.PREFIX + "/git/blobs/" + selected.sha)
    assert result == Reply(200, payload, None)
    assert [call[0] for call in http.calls] == [
        "https://api.github.com" + tree.PREFIX + path
        for path in paths * 2 + [blob_path]
    ]
    assert all(stream.closed for stream in http.streams)
    assert not proof and proof.can_start is False and proof.execution == "NOT RUN"


@pytest.mark.parametrize(
    "suffix",
    [
        "/git/blobs",
        "/git/blobs/main",
        "/git/blobs/experimental",
        "/git/blobs/" + "0" * 40,
        "/git/blobs/" + "A" * 40,
        "/git/blobs/" + "a" * 39,
        "/git/blobs/%61" + "a" * 39,
        "/git/blobs/../" + "a" * 40,
        "/git/blobs/" + "a" * 40 + "?raw=1",
        "/git/blobs/" + "a" * 40 + "?ref=main",
        "/git/blobs/" + "a" * 40 + "#fragment",
        "/git/blobs/" + "a" * 40 + "/",
        "/contents/.github/workflows/hoben-ha-manual.yml",
        "/branches/main",
        "/branches/experimental/protection",
        "/actions/workflows",
        "/actions/secrets",
    ],
)
def test_only_exact_blob_sha_route_is_added(suffix):
    http = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(tree.PREFIX + suffix)
    assert caught.value.code is Failure.REQUEST and http.calls == []


@pytest.mark.parametrize(
    "params", [{"page": 1}, {"per_page": 100}, {"page": 1, "per_page": 100}]
)
def test_blob_route_refuses_query_parameters(params):
    http = FakeHTTP()
    with pytest.raises(TransportFailure):
        GitHubGETTransport(TOKEN, client=http).get(
            tree.PREFIX + "/git/blobs/" + "a" * 40, **params
        )
    assert http.calls == []


@pytest.mark.parametrize(
    "body,category",
    [
        (b'{"sha":', Failure.JSON),
        (b'{"size":1,"size":2}', Failure.JSON),
        (b'{"content":"SYNTHETIC_TOKEN_011"}', Failure.SECRET),
    ],
)
def test_new_route_keeps_transport_json_truncation_duplicates_and_secret_refusals(
    body, category
):
    http = FakeHTTP(Stream(body))
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(
            tree.PREFIX + "/git/blobs/" + "a" * 40
        )
    assert caught.value.code is category
    assert "SYNTHETIC_PRIVATE_INPUT" not in repr(caught.value) and TOKEN not in repr(
        caught.value
    )
    assert len(http.calls) == 1 and http.stream.closed
