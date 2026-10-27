"""Synthetic blobs and distinct tree evidence; no DNS, socket or live API."""

import ast
import base64
import copy
import hashlib
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest
from test_github_campaign_transport import FakeHTTP, Stream
from test_github_campaign_workflow_tree import fixture as tree_fixture

import scripts.github_campaign_workflow_blob as blob
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


def git_sha(data):
    return hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False
    ).hexdigest()


def fixture(campaign=tree.Campaign.PROTOCOL, content=CONTENT):
    sha = git_sha(content)
    expected = blob.Expected(campaign, COMMIT, sha)
    metadata = tree_fixture(campaign)
    metadata[4]["tree"][0]["sha"] = sha
    proof = tree.validate_workflow_tree(tree.Expected(campaign, COMMIT), *metadata)
    assert proof.error is None
    payload = {
        "sha": sha,
        "size": len(content),
        "encoding": "base64",
        "content": base64.encodebytes(content).decode(),
        "url": "https://private.invalid/SYNTHETIC_PRIVATE_INPUT",
        "node_id": "SYNTHETIC_PRIVATE_INPUT",
    }
    return expected, proof, payload


class FakeReader:
    def __init__(self, responses=None):
        self.responses = (
            [Reply(200, fixture()[2], None)] * 2 if responses is None else responses
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
        raise AssertionError("Network forbidden in blob evidence tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def never_starts(result):
    assert type(result) is blob.Observation and not result and result.can_start is False
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert len(result.facts) == len(blob.FactName)
    assert all(
        type(f.name) is blob.FactName and type(f.state) is blob.State
        for f in result.facts
    )
    assert "SYNTHETIC_PRIVATE_INPUT" not in repr(result) and TOKEN not in repr(result)
    assert CONTENT.decode() not in repr(result)


def refused(result, error=None):
    never_starts(result)
    assert type(result.error) is blob.Error
    if error is not None:
        assert result.error is error
    assert all(f.state is blob.State.UNKNOWN for f in result.facts)
    assert result._binding is result._expected is None


@pytest.mark.parametrize("campaign", list(tree.Campaign))
def test_both_campaigns_require_tree_link_and_attest_only_byte_identity(campaign):
    expected, proof, payload = fixture(campaign)
    pure = blob.validate_workflow_blob(expected, proof, payload)
    reader = FakeReader([Reply(200, payload, None)] * 2)
    result = blob.read_workflow_blob(reader, expected, proof)
    assert result.error is pure.error is None and result == pure
    never_starts(result)
    assert {f.name for f in result.facts if f.state is blob.State.ATTESTED} == {
        blob.FactName.TREE_LINK,
        blob.FactName.BLOB,
        blob.FactName.SIZE,
    }
    assert reader.calls == [tree.PREFIX + "/git/blobs/" + expected.blob_sha] * 2
    recheck = FakeReader([Reply(200, payload, None)] * 2)
    assert blob.read_workflow_blob(recheck, expected, proof, result) == result
    assert recheck.calls == reader.calls


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        {},
        replace(fixture()[0], campaign="protocol"),
        replace(fixture()[0], repository="spoof/repo"),
        replace(fixture()[0], repository=True),
        replace(fixture()[0], ref="refs/heads/main"),
        replace(fixture()[0], ref="experimental"),
        replace(fixture()[0], ref=True),
        replace(fixture()[0], commit_sha="0" * 40),
        replace(fixture()[0], commit_sha=True),
        replace(fixture()[0], blob_sha="0" * 40),
        replace(fixture()[0], blob_sha="A" * 40),
        replace(fixture()[0], blob_sha="a" * 39),
        replace(fixture()[0], blob_sha=True),
        replace(fixture()[0], blob_sha="SYNTHETIC_PRIVATE_INPUT"),
    ],
)
def test_closed_configuration_and_main_refuse_before_any_blob_get(bad):
    _, proof, payload = fixture()
    reader = FakeReader()
    refused(blob.validate_workflow_blob(bad, proof, payload), blob.Error.EXPECTED)
    refused(blob.read_workflow_blob(reader, bad, proof), blob.Error.EXPECTED)
    assert reader.calls == []
    if type(bad) is blob.Expected:
        assert "SYNTHETIC_PRIVATE_INPUT" not in repr(bad)


@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "bool",
        "dict",
        "failed",
        "empty_projection",
        "campaign",
        "commit",
        "blob",
        "binding",
        "changed_identity",
        "tree_shas",
        "unverified_facts",
    ],
)
def test_distinct_real_tree_proof_required_before_blob_get(case):
    expected, proof, payload = fixture()
    if case == "absent":
        proof = None
    elif case == "bool":
        proof = True
    elif case == "dict":
        proof = {"attested": True, "sha": expected.blob_sha}
    elif case == "failed":
        proof = tree.validate_workflow_tree(
            tree.Expected(tree.Campaign.PROTOCOL, COMMIT), *[{}] * 5
        )
    elif case == "empty_projection":
        proof = replace(proof, _blob=None)
    elif case == "campaign":
        expected = replace(expected, campaign=tree.Campaign.HA)
    elif case == "commit":
        expected = replace(expected, commit_sha="f" * 40)
    elif case == "blob":
        expected = replace(expected, blob_sha="f" * 40)
    elif case == "binding":
        proof = replace(proof, _binding="f" * 64)
    elif case == "changed_identity":
        proof = replace(proof, _blob=replace(proof._blob, sha="f" * 40))
        expected = replace(expected, blob_sha="f" * 40)
    elif case == "tree_shas":
        proof = replace(proof, _blob=replace(proof._blob, tree_shas=("f" * 40,) * 3))
    else:
        proof = replace(proof, facts=())
    reader = FakeReader()
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.TREE)
    refused(blob.read_workflow_blob(reader, expected, proof), blob.Error.TREE)
    assert reader.calls == []


@pytest.mark.parametrize(
    "content", [b"", b"\x00\xff\x80\n", b"not: [valid YAML", b"X" * blob.MAX_BLOB_BYTES]
)
def test_identity_only_including_empty_binary_invalid_yaml_and_exact_size_limit(
    content,
):
    expected, proof, payload = fixture(content=content)
    result = blob.validate_workflow_blob(expected, proof, payload)
    assert result.error is None
    never_starts(result)
    assert (
        next(f.state for f in result.facts if f.name is blob.FactName.YAML)
        is blob.State.UNKNOWN
    )


@pytest.mark.parametrize("wrapped", [False, "LF", "CRLF"])
def test_valid_canonical_base64_with_github_line_wrapping(wrapped):
    expected, proof, payload = fixture(content=b"X" * 200)
    encoded = base64.b64encode(b"X" * 200).decode()
    if wrapped:
        newline = "\n" if wrapped == "LF" else "\r\n"
        encoded = (
            newline.join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
            + newline
        )
    payload["content"] = encoded
    assert blob.validate_workflow_blob(expected, proof, payload).error is None


@pytest.mark.parametrize(
    "field,bad",
    [
        ("sha", "f" * 40),
        ("sha", True),
        ("sha", None),
        ("encoding", "utf-8"),
        ("encoding", "BASE64"),
        ("encoding", True),
        ("size", True),
        ("size", -1),
        ("size", 1.0),
        ("size", None),
        ("size", len(CONTENT) - 1),
        ("size", len(CONTENT) + 1),
        ("size", blob.MAX_BLOB_BYTES + 1),
        ("size", 10**20),
        ("content", None),
        ("content", True),
        ("content", b"AAAA"),
        ("content", "A" * (blob.MAX_BASE64_CHARS + 1)),
        ("url", []),
        ("url", "X" * 2049),
        ("node_id", None),
    ],
)
def test_envelope_identity_types_sizes_and_limits_fail_closed(field, bad):
    expected, proof, payload = fixture()
    payload[field] = bad
    refused(blob.validate_workflow_blob(expected, proof, payload))


@pytest.mark.parametrize("field", ["sha", "size", "encoding", "content"])
def test_missing_required_field_refuses(field):
    expected, proof, payload = fixture()
    del payload[field]
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.SHAPE)


@pytest.mark.parametrize("bad", [None, True, [], "SYNTHETIC_PRIVATE_INPUT", b"PRIVATE"])
def test_root_shape_refuses(bad):
    expected, proof, _ = fixture()
    refused(blob.validate_workflow_blob(expected, proof, bad), blob.Error.SHAPE)


@pytest.mark.parametrize(
    "encoded",
    [
        "@@==",
        "Zg=",
        "Zg===",
        "Zh==",
        "Zg--",
        "Zg__",
        "Zg==\n\n",
        " Zg==",
        "Zg==\t",
        "Zg==\r",
        "Zg==\x00",
        "éé==",
    ],
)
def test_invalid_truncated_noncanonical_padding_or_whitespace_refuses(encoded):
    expected, proof, payload = fixture(content=b"f")
    payload["content"] = encoded
    refused(blob.validate_workflow_blob(expected, proof, payload))


def test_decoded_byte_hash_uses_git_header_not_raw_sha_or_payload_claim():
    expected, proof, payload = fixture()
    tampered = b"Y" * len(CONTENT)
    payload["content"] = base64.b64encode(tampered).decode()
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.IDENTITY)
    payload["sha"] = git_sha(tampered)
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.IDENTITY)
    expected, proof, payload = fixture()
    metadata = tree_fixture()
    raw_sha = hashlib.sha1(CONTENT, usedforsecurity=False).hexdigest()
    metadata[4]["tree"][0]["sha"] = raw_sha
    proof = tree.validate_workflow_tree(
        tree.Expected(tree.Campaign.PROTOCOL, COMMIT), *metadata
    )
    expected = replace(expected, blob_sha=raw_sha)
    payload["sha"] = raw_sha
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.IDENTITY)


def test_size_limit_plus_one_and_base64_decoding_length_mismatch_refuse():
    expected, proof, payload = fixture(content=b"X" * (blob.MAX_BLOB_BYTES + 1))
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.SIZE)
    expected, proof, payload = fixture(content=b"f")
    payload["size"] = 2  # same four base64 characters, but different decoded size
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.SIZE)


@pytest.mark.parametrize(
    "extra", ["truncated", "content_utf8", "download_url", "can_start", "encoding_alt"]
)
def test_ambiguous_extra_envelope_fields_refuse(extra):
    expected, proof, payload = fixture()
    payload[extra] = "SYNTHETIC_PRIVATE_INPUT"
    refused(blob.validate_workflow_blob(expected, proof, payload), blob.Error.SHAPE)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 502, 503])
def test_http_failure_at_either_read_discards_partial_facts_no_retry(index, status):
    expected, proof, payload = fixture()
    responses = [Reply(200, payload, None)] * 2
    responses[index] = Reply(status, {"message": "SYNTHETIC_PRIVATE_INPUT"}, None)
    reader = FakeReader(responses)
    refused(blob.read_workflow_blob(reader, expected, proof))
    assert len(reader.calls) == index + 1


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "bad",
    [
        Reply(200, None, None),
        Reply(True, {}, None),
        Reply(200, {}, 2),
        RuntimeError("SYNTHETIC_PRIVATE_INPUT"),
    ],
)
def test_private_malformed_paginated_or_exceptional_read_refuses(index, bad, capsys):
    expected, proof, payload = fixture()
    responses = [Reply(200, payload, None)] * 2
    responses[index] = bad
    refused(blob.read_workflow_blob(FakeReader(responses), expected, proof))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_recheck_changed_bytes_pins_tree_binding_or_unverified_previous_refuse():
    expected, proof, payload = fixture()
    previous = blob.read_workflow_blob(FakeReader(), expected, proof)
    assert previous.error is None
    p = copy.deepcopy(payload)
    p["content"] = base64.b64encode(b"Y" * len(CONTENT)).decode()
    refused(
        blob.read_workflow_blob(
            FakeReader([Reply(200, payload, None), Reply(200, p, None)]),
            expected,
            proof,
        ),
        blob.Error.IDENTITY,
    )
    for pin, obs in [
        (replace(expected, campaign=tree.Campaign.HA), fixture(tree.Campaign.HA)[1]),
        (replace(expected, commit_sha="f" * 40), proof),
    ]:
        reader = FakeReader()
        refused(blob.read_workflow_blob(reader, pin, obs, previous))
        assert reader.calls == []
    metadata = tree_fixture()
    metadata[4]["tree"][0]["sha"] = expected.blob_sha
    metadata[1]["tree"]["sha"] = "f" * 40
    metadata[2]["sha"] = "f" * 40
    moved = tree.validate_workflow_tree(
        tree.Expected(tree.Campaign.PROTOCOL, COMMIT), *metadata
    )
    assert moved.error is None
    refused(
        blob.read_workflow_blob(FakeReader(), expected, moved, previous),
        blob.Error.CHANGED,
    )
    for bad in (True, {}, blob.validate_workflow_blob(expected, proof, None)):
        reader = FakeReader()
        refused(
            blob.read_workflow_blob(reader, expected, proof, bad), blob.Error.PREVIOUS
        )
        assert reader.calls == []


def test_observations_and_tree_identity_keep_only_frozen_pins_facts_and_hashes():
    expected, proof, payload = fixture()
    identity = tree.blob_identity(proof, tree.Expected(tree.Campaign.PROTOCOL, COMMIT))
    assert type(identity) is tree.BlobIdentity and identity.sha == expected.blob_sha
    result = blob.validate_workflow_blob(expected, proof, payload)
    before = repr(result)
    payload["content"] = "SYNTHETIC_PRIVATE_INPUT"
    assert result.error is None and repr(result) == before
    assert len(result._binding) == len(result._expected) == 64
    for obj, attr in (
        (result, "can_start"),
        (result.facts[0], "state"),
        (identity, "sha"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, attr, True)
    with pytest.raises(TypeError):
        blob.Observation(result.facts, None, can_start=True)
    assert {f.name for f in fields(result)} == {
        "facts",
        "error",
        "_binding",
        "_expected",
        "can_start",
        "execution",
        "actions_result",
    }


@pytest.mark.parametrize("campaign", list(tree.Campaign))
def test_transport_authenticates_tree_then_fetches_only_selected_blob(campaign):
    expected, _, payload = fixture(campaign)
    metadata = tree_fixture(campaign)
    metadata[4]["tree"][0]["sha"] = expected.blob_sha
    paths = ["", "/git/commits/" + COMMIT, *["/git/trees/" + c * 40 for c in "bcd"]]
    payloads = dict(zip(paths, metadata, strict=True))
    blob_path = "/git/blobs/" + expected.blob_sha
    payloads[blob_path] = payload
    http = FakeHTTP(payloads=payloads)
    reader = GitHubGETTransport(TOKEN, client=http)
    proof = tree.read_workflow_tree(reader, tree.Expected(campaign, COMMIT))
    assert proof.error is None
    result = blob.read_workflow_blob(reader, expected, proof)
    assert result.error is None
    assert [c[0] for c in http.calls] == [
        "https://api.github.com" + tree.PREFIX + p for p in paths * 2 + [blob_path] * 2
    ]
    assert all(s.closed for s in http.streams)
    never_starts(result)


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
    "body", [b'{"sha":', b'{"size":1,"size":2}', b'{"content":"SYNTHETIC_TOKEN_011"}']
)
def test_new_route_keeps_transport_json_truncation_duplicates_and_secret_refusals(body):
    http = FakeHTTP(Stream(body))
    with pytest.raises(TransportFailure) as caught:
        GitHubGETTransport(TOKEN, client=http).get(
            tree.PREFIX + "/git/blobs/" + "a" * 40
        )
    assert "SYNTHETIC_PRIVATE_INPUT" not in repr(caught.value) and TOKEN not in repr(
        caught.value
    )
    assert http.stream.closed


def test_module_has_no_yaml_interpreter_backend_io_or_runtime_consumer():
    path = ROOT / "scripts/github_campaign_workflow_blob.py"
    parsed = ast.parse(path.read_text())
    imports = {
        n.module if isinstance(n, ast.ImportFrom) else alias.name
        for n in ast.walk(parsed)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for alias in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert imports == {
        "base64",
        "hashlib",
        "json",
        "re",
        "dataclasses",
        "enum",
        "scripts",
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
            "github_campaign_workflow_blob" in p.read_text()
            for p in (ROOT / folder).rglob("*")
            if p != path and p.is_file() and p.suffix in {".py", ".cjs", ".yml"}
        )
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
