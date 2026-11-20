"""Shared registry-route transport guards after removal of the unused reader."""

import ast
import socket
from pathlib import Path

import pytest
from test_github_campaign_transport import FakeHTTP, Stream

from scripts.github_campaign_evidence import PREFIX, Reply
from scripts.github_campaign_transport import (
    Failure,
    GitHubGETTransport,
    TransportFailure,
)

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "SYNTHETIC_TOKEN_012"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in registry evidence tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def test_removed_registry_reader_has_no_operational_entry_point():
    """The shared GET transport stays guarded without a registry proof reader."""
    assert not (ROOT / "scripts/github_campaign_actions_registry.py").exists()
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
                assert not any("github_campaign_actions_registry" in n for n in names)
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        assert "github_campaign_actions_registry" not in path.read_text()
    assert (
        "github_campaign_actions_registry" not in (ROOT / "pyproject.toml").read_text()
    )


@pytest.mark.parametrize("campaign", ["protocol", "ha"])
def test_exact_new_routes_work_only_via_injected_existing_transport(campaign):
    route = "/actions/workflows/hoben-" + campaign + "-manual.yml"
    payload = {
        "id": 10011,
        "path": ".github/workflows/hoben-" + campaign + "-manual.yml",
        "state": "active",
    }
    http = FakeHTTP(payloads={route: payload})
    result = GitHubGETTransport(TOKEN, client=http).get(PREFIX + route)
    assert result == Reply(200, payload, None)
    assert [call[0] for call in http.calls] == [
        "https://api.github.com" + PREFIX + route
    ]
    assert all(stream.closed for stream in http.streams)


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
        GitHubGETTransport(TOKEN, client=http).get(PREFIX + suffix)
    assert caught.value.code is Failure.REQUEST and http.calls == []


@pytest.mark.parametrize("campaign", ("protocol", "ha"))
@pytest.mark.parametrize(
    "params", [{"page": 1}, {"per_page": 100}, {"page": 1, "per_page": 100}]
)
def test_workflow_routes_have_no_pagination_or_query(campaign, params):
    http = FakeHTTP()
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(
            PREFIX + "/actions/workflows/hoben-" + campaign + "-manual.yml",
            **params,
        )
    assert caught.value.code is Failure.REQUEST and http.calls == []


@pytest.mark.parametrize(
    "body,category",
    [
        (b'{"id":', Failure.JSON),
        (b'{"id":10011,"id":10012}', Failure.JSON),
        (b'{"name":"SYNTHETIC_TOKEN_012"}', Failure.SECRET),
    ],
)
def test_new_routes_keep_transport_truncation_duplicates_and_secret_echo_refusals(
    body, category
):
    http = FakeHTTP(Stream(body))
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(
            PREFIX + "/actions/workflows/hoben-protocol-manual.yml"
        )
    assert caught.value.code is category
    assert TOKEN not in repr(caught.value) + str(caught.value)
    assert len(http.calls) == 1 and http.stream.closed


def test_new_route_refuses_redirect_and_does_not_follow_body_url():
    http = FakeHTTP(
        Stream(status=302, headers=[("Location", "https://private.invalid/PRIVATE")])
    )
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(
            PREFIX + "/actions/workflows/hoben-ha-manual.yml"
        )
    assert caught.value.code is Failure.REDIRECT
    assert len(http.calls) == 1 and http.stream.closed and http.stream.reads == []
