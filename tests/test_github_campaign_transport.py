"""Synthetic credentials and streams only: no DNS, socket or remote request."""

import ast
import copy
import io
import json
import socket
import ssl
import subprocess
import sys
import traceback
from email.message import Message
from http.client import HTTPResponse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest
from test_github_campaign_evidence import REQUEST
from test_github_campaign_evidence import fixture as evidence_fixture

import scripts.github_campaign_transport as transport
from scripts.github_campaign_evidence import Error, State, read_evidence

TOKEN = "SYNTHETIC_OFFLINE_TOKEN_007"
PREFIX = "/repos/Guillaume0385/ha-hoben-community"
ORIGIN = "https://api.github.com"
REVIEWS = PREFIX + "/pulls/27/reviews"
JOBS = PREFIX + "/actions/runs/12345/attempts/1/jobs"
SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[1]


class Stream:
    def __init__(self, body=b"{}", *, status=200, headers=None, url=None):
        self.status, self.url = status, url
        self.headers = Message()
        pairs = (
            headers
            if headers is not None
            else [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ]
        )
        for name, value in pairs:
            self.headers[name] = value
        self.body, self.offset, self.closed, self.reads = body, 0, False, []

    def read1(self, size):
        self.reads.append(size)
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def geturl(self):
        return self.url

    def close(self):
        self.closed = True


class FakeHTTP:
    def __init__(self, stream=None, *, payloads=None, fault=None):
        self.stream = Stream() if stream is None else stream
        self.payloads, self.fault, self.calls, self.streams = payloads, fault, [], []

    def open(self, url, *, headers, timeout, context):
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.keylog_filename is None
        self.calls.append((url, headers, timeout, context))
        if self.fault is not None:
            raise self.fault
        stream = self.stream
        if self.payloads is not None:
            suffix = urlsplit(url).path[len(PREFIX) :]
            stream = Stream(json.dumps(self.payloads[suffix]).encode())
        if stream.url is None:
            stream.url = url
        self.streams.append(stream)
        return stream


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def fail(client, category=None, path=PREFIX, **params):
    reader = transport.GitHubGETTransport(TOKEN, client=client)
    with pytest.raises(transport.TransportFailure) as caught:
        reader.get(path, **params)
    error = caught.value
    assert type(error.code) is transport.Failure
    if category is not None:
        assert error.code is category
    assert error.__context__ is None and error.__cause__ is None
    assert TOKEN not in repr(reader) + repr(error) + str(error)
    assert "PRIVATE_INPUT" not in "".join(traceback.format_exception(error))
    assert all(s.closed for s in client.streams)
    return error


def header_stream(body=b"{}", **values):
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    headers.update(values)
    return Stream(body, headers=list(headers.items()))


def link(page=2, path=REVIEWS, relation="next"):
    return f'<{ORIGIN}{path}?per_page=100&page={page}>; rel="{relation}"'


def test_successful_reply_auth_headers_tls_timeout_and_closed_stream(capsys):
    fake = FakeHTTP()
    reader = transport.GitHubGETTransport(TOKEN, client=fake)
    reply = reader.get(PREFIX)
    assert reply.status == 200 and reply.data == {} and reply.next_page is None
    url, headers, timeout, context = fake.calls[0]
    assert url == ORIGIN + PREFIX and timeout == 10
    assert headers["Authorization"] == "Bearer " + TOKEN
    assert headers["Accept-Encoding"] == "identity"
    assert headers["Cache-Control"] == headers["Pragma"] == "no-cache"
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert fake.stream.closed and fake.stream.reads == [65536, 65536]
    assert TOKEN not in repr(reader) + str(reader) + repr(reply) + str(reply)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "token",
    [
        None,
        True,
        b"SYNTHETIC_TOKEN",
        "",
        "short",
        " " * 20,
        "line\r\nInjected: value",
        "x" * 1025,
        "é" * 20,
    ],
)
def test_missing_or_unsafe_auth_never_falls_back_to_environment(token, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    fake = FakeHTTP()
    with pytest.raises(transport.TransportFailure) as caught:
        transport.GitHubGETTransport(token, client=fake)
    assert caught.value.code is transport.Failure.AUTH and fake.calls == []
    assert TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    "path,params",
    [
        (PREFIX, {}),
        (PREFIX + "/git/commits/" + SHA, {}),
        (PREFIX + "/pulls/27", {}),
        (PREFIX + "/actions/runs/12345", {}),
        (REVIEWS, {"page": 1, "per_page": 100}),
        (JOBS, {"page": 1, "per_page": 100}),
    ],
)
def test_exact_six_routes_only(path, params):
    body = (
        b"[]"
        if path == REVIEWS
        else b'{"total_count":0,"jobs":[]}'
        if path == JOBS
        else b"{}"
    )
    fake = FakeHTTP(Stream(body))
    reply = transport.GitHubGETTransport(TOKEN, client=fake).get(path, **params)
    assert reply.status == 200 and reply.next_page is None
    assert len(fake.calls) == 1 and fake.stream.closed


@pytest.mark.parametrize(
    "path",
    [
        None,
        True,
        "",
        "https://api.github.com" + PREFIX,
        "https://private.invalid/PRIVATE_INPUT",
        "//private.invalid/PRIVATE_INPUT",
        PREFIX + "/",
        PREFIX + "-spoof",
        PREFIX.lower(),
        PREFIX + "/../other",
        PREFIX + "/%2e%2e/other",
        PREFIX + "/pulls%2f27",
        PREFIX + "/pulls/27?token=PRIVATE_INPUT",
        PREFIX + "/pulls/27#fragment",
        PREFIX + "/pulls/0",
        PREFIX + "/pulls/027",
        PREFIX + "/pulls/-27",
        PREFIX + "/pulls/9007199254740992",
        PREFIX + "/git/commits/" + "0" * 40,
        PREFIX + "/git/commits/" + "A" * 40,
        PREFIX + "/actions/runs/12345/attempts/2/jobs",
        PREFIX + "/actions/runs/12345/jobs",
        PREFIX + "/actions/workflows",
        PREFIX + "/environments/hoben-live",
        PREFIX + "/secrets",
        PREFIX + "/git/refs",
        PREFIX + "/issues/126/comments",
        PREFIX + "/pulls/27\r\nHost: private.invalid",
    ],
)
def test_other_origins_routes_queries_or_encodings_refused_before_http(path):
    fake = FakeHTTP()
    fail(fake, transport.Failure.REQUEST, path)
    assert fake.calls == []


@pytest.mark.parametrize(
    "path,params",
    [
        (PREFIX, {"page": 1, "per_page": 100}),
        (REVIEWS, {}),
        (REVIEWS, {"page": True, "per_page": 100}),
        (REVIEWS, {"page": 0, "per_page": 100}),
        (REVIEWS, {"page": 11, "per_page": 100}),
        (REVIEWS, {"page": 1, "per_page": 99}),
        (REVIEWS, {"page": 1, "per_page": True}),
        (REVIEWS, {"page": "1", "per_page": 100}),
    ],
)
def test_closed_pagination_parameters(path, params):
    fake = FakeHTTP()
    fail(fake, transport.Failure.REQUEST, path, **params)
    assert fake.calls == []


@pytest.mark.parametrize(
    "status,category",
    [
        (301, transport.Failure.REDIRECT),
        (302, transport.Failure.REDIRECT),
        (303, transport.Failure.REDIRECT),
        (307, transport.Failure.REDIRECT),
        (308, transport.Failure.REDIRECT),
        (401, transport.Failure.FORBIDDEN),
        (403, transport.Failure.FORBIDDEN),
        (404, transport.Failure.NOT_FOUND),
        (429, transport.Failure.RATE_LIMIT),
        (500, transport.Failure.HTTP),
        (502, transport.Failure.HTTP),
        (503, transport.Failure.HTTP),
        (201, transport.Failure.HTTP),
        (204, transport.Failure.HTTP),
        (True, transport.Failure.HTTP),
    ],
)
def test_http_failure_no_body_read_no_retry_or_redirect(status, category):
    stream = Stream(
        (TOKEN + " PRIVATE_INPUT").encode(),
        status=status,
        headers=[("Location", "https://private.invalid/PRIVATE_INPUT")],
    )
    fake = FakeHTTP(stream)
    fail(fake, category)
    assert len(fake.calls) == 1 and stream.reads == []


@pytest.mark.parametrize(
    "url",
    [
        ORIGIN + PREFIX + "/",
        "http://api.github.com" + PREFIX,
        "https://private.invalid/PRIVATE_INPUT",
        "https://api.github.com@private.invalid" + PREFIX,
        "https://api.github.com:443" + PREFIX,
    ],
)
def test_effective_response_url_must_match_exact_request(url):
    fake = FakeHTTP(Stream(url=url))
    fail(fake, transport.Failure.REDIRECT)
    assert fake.stream.reads == [] and len(fake.calls) == 1


@pytest.mark.parametrize(
    "fault,category",
    [
        (TimeoutError("PRIVATE_INPUT " + TOKEN), transport.Failure.TIMEOUT),
        (ssl.SSLCertVerificationError("PRIVATE_INPUT " + TOKEN), transport.Failure.TLS),
        (URLError(ssl.SSLError("PRIVATE_INPUT")), transport.Failure.TLS),
        (URLError(TimeoutError("PRIVATE_INPUT")), transport.Failure.TIMEOUT),
        (RuntimeError("PRIVATE_INPUT " + TOKEN), transport.Failure.NETWORK),
    ],
)
def test_private_network_errors_sanitized_without_context(fault, category, capsys):
    fake = FakeHTTP(fault=fault)
    fail(fake, category)
    assert len(fake.calls) == 1 and capsys.readouterr() == ("", "")


def test_no_tls_disable_or_keylogging_and_weak_context_refused(monkeypatch, tmp_path):
    forbidden = tmp_path / "keylog-must-not-exist"
    monkeypatch.setenv("SSLKEYLOGFILE", str(forbidden))
    context = transport._tls_context()
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert context.keylog_filename is None and not forbidden.exists()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    monkeypatch.setattr(transport, "_tls_context", lambda: context)
    fake = FakeHTTP()
    fail(fake, transport.Failure.TLS)
    assert fake.calls == []


def test_context_tampering_by_client_refused_and_stream_closed():
    class Tampering(FakeHTTP):
        def open(self, url, **kwargs):
            stream = super().open(url, **kwargs)
            kwargs["context"].check_hostname = False
            return stream

    fake = Tampering()
    fail(fake, transport.Failure.TLS)
    assert fake.stream.reads == [] and fake.stream.closed


@pytest.mark.parametrize(
    "headers,category",
    [
        ([("Content-Length", "2")], transport.Failure.HEADERS),
        (
            [("Content-Type", "text/html"), ("Content-Length", "2")],
            transport.Failure.HEADERS,
        ),
        (
            [
                ("Content-Type", "application/json; charset=latin1"),
                ("Content-Length", "2"),
            ],
            transport.Failure.HEADERS,
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("content-length", "2"),
            ],
            transport.Failure.HEADERS,
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("Content-Encoding", "gzip"),
            ],
            transport.Failure.HEADERS,
        ),
        ([("Content-Type", "application/json")], transport.Failure.BODY),
        (
            [
                ("Content-Type", "application/json"),
                ("Transfer-Encoding", "gzip, chunked"),
            ],
            transport.Failure.BODY,
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Transfer-Encoding", "chunked"),
                ("Content-Length", "2"),
            ],
            transport.Failure.BODY,
        ),
        (
            [("Content-Type", "application/json"), ("Content-Length", "-1")],
            transport.Failure.BODY,
        ),
        (
            [("Content-Type", "application/json"), ("Content-Length", "02")],
            transport.Failure.BODY,
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(transport.MAX_RESPONSE_BYTES + 1)),
            ],
            transport.Failure.SIZE,
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("X-Extra", "PRIVATE_INPUT\r\nLocation: other"),
            ],
            transport.Failure.HEADERS,
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("X-Extra", "x" * (transport.MAX_HEADER_BYTES + 1)),
            ],
            transport.Failure.HEADERS,
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                *((f"X-{i}", "value") for i in range(99)),
            ],
            transport.Failure.HEADERS,
        ),
    ],
)
def test_header_types_duplicates_compression_framing_and_bounds(headers, category):
    fake = FakeHTTP(Stream(headers=headers))
    fail(fake, category)
    assert fake.stream.reads == []


def test_header_parser_defects_cannot_hide_pagination_metadata():
    fake = FakeHTTP(Stream())
    fake.stream.headers.defects.append(ValueError("PRIVATE_INPUT"))
    fail(fake, transport.Failure.HEADERS)
    assert fake.stream.reads == []


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"{} trailing",
        b"\xff",
        b'{"a":1,"a":2}',
        b'{"a":{"b":1,"b":2}}',
        b'{"n":NaN}',
        b'{"n":Infinity}',
        b'{"n":1e999}',
        b'{"s":"\\ud800"}',
        b"[" * 66 + b"0" + b"]" * 66,
        b"[]",
        b"null",
        b"true",
    ],
)
def test_invalid_json_encoding_duplicate_keys_nesting_and_unexpected_root(body):
    fail(FakeHTTP(Stream(body)))


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"echo": TOKEN}).encode(),
        ('{"echo":"' + "".join("\\u%04x" % ord(c) for c in TOKEN) + '"}').encode(),
        json.dumps({TOKEN: "ignored"}).encode(),
    ],
)
def test_literal_or_json_escaped_token_never_returned(body):
    fail(FakeHTTP(Stream(body)), transport.Failure.SECRET)


def test_response_length_mismatch_and_oversize_stream_and_exact_boundary():
    fail(FakeHTTP(header_stream(**{"Content-Length": "3"})), transport.Failure.BODY)
    fail(FakeHTTP(header_stream(**{"Content-Length": "1"})), transport.Failure.BODY)
    body = b'{"padding":"' + b"x" * (transport.MAX_RESPONSE_BYTES - 14) + b'"}'
    assert len(body) == transport.MAX_RESPONSE_BYTES
    fake = FakeHTTP(Stream(body))
    assert transport.GitHubGETTransport(TOKEN, client=fake).get(PREFIX).status == 200
    oversized = FakeHTTP(
        Stream(
            body + b"x",
            headers=[
                ("Content-Type", "application/json"),
                ("Transfer-Encoding", "chunked"),
            ],
        )
    )
    fail(oversized, transport.Failure.SIZE)
    assert oversized.stream.offset == transport.MAX_RESPONSE_BYTES + 1


def test_monotonic_deadline_checked_after_open_and_read(monkeypatch):
    now = [0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])

    class SlowOpen(FakeHTTP):
        def open(self, *args, **kwargs):
            stream = super().open(*args, **kwargs)
            now[0] = 10
            return stream

    fake = SlowOpen()
    fail(fake, transport.Failure.TIMEOUT)
    assert fake.stream.reads == []
    now[0] = 0

    class SlowRead(Stream):
        def read1(self, size):
            result = super().read1(size)
            now[0] += 6
            return result

    fail(FakeHTTP(SlowRead()), transport.Failure.TIMEOUT)


def test_deadline_covers_validation_and_stream_faults_remain_private(monkeypatch):
    now = [0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    decode = transport._json

    def late_decode(*args):
        result = decode(*args)
        now[0] = 10
        return result

    monkeypatch.setattr(transport, "_json", late_decode)
    fail(FakeHTTP(), transport.Failure.TIMEOUT)
    now[0] = 0

    class BrokenStream(Stream):
        def read1(self, size):
            raise RuntimeError("PRIVATE_INPUT " + TOKEN)

    fail(FakeHTTP(BrokenStream()), transport.Failure.NETWORK)


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        'application/json; charset="UTF-8"',
        "application/vnd.github+json; charset=utf-8",
    ],
)
def test_supported_json_content_types(content_type):
    fake = FakeHTTP(header_stream(**{"Content-Type": content_type}))
    assert transport.GitHubGETTransport(TOKEN, client=fake).get(PREFIX).data == {}


@pytest.mark.parametrize(
    "next_link",
    [
        link(),
        link() + ", " + link(2, relation="last"),
    ],
)
def test_valid_next_link_bound_to_current_origin_route_query_and_successor(next_link):
    fake = FakeHTTP(header_stream(b"[{}]", Link=next_link))
    reader = transport.GitHubGETTransport(TOKEN, client=fake)
    reply = reader.get(REVIEWS, page=1, per_page=100)
    assert reply.next_page == 2 and reply.data == [{}]
    assert len(fake.calls) == 1  # URL in Link is validated, never followed here


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "PRIVATE_INPUT",
        link() + ", " + link(),
        link().replace("https://", "http://"),
        link().replace("api.github.com", "private.invalid/PRIVATE_INPUT"),
        link().replace("api.github.com", "api.github.com@private.invalid"),
        link().replace("api.github.com", "api.github.com:443"),
        link().replace(REVIEWS, JOBS),
        link().replace(PREFIX, "/repositories/1401398724"),
        link().replace("page=2", "page=1"),
        link().replace("page=2", "page=3"),
        link().replace("page=2", "page=11"),
        link().replace("page=2", "page=02"),
        link().replace("per_page=100", "per_page=20"),
        link().replace("page=2", "page=2&page=2"),
        link().replace("page=2", "page=2&token=PRIVATE_INPUT"),
        link().replace("page=2", "page=2#fragment"),
        link().replace('rel="next"', 'rel="next last"'),
        link().replace('rel="next"', 'rel="unknown"'),
        link().replace('rel="next"', "rel=next"),
        link(2, relation="last"),
        link(2, relation="first"),
        link(1, relation="prev"),
        link() + ", " + link(1, relation="last"),
    ],
)
def test_malformed_ambiguous_or_malicious_link_refuses_without_second_request(bad):
    fake = FakeHTTP(header_stream(b"[{}]", Link=bad))
    fail(fake, transport.Failure.PAGINATION, REVIEWS, page=1, per_page=100)
    assert len(fake.calls) == 1


def test_terminal_proof_full_reviews_page_missing_next_and_jobs_total():
    fail(
        FakeHTTP(header_stream(b"[]", Link=link())),
        transport.Failure.PAGINATION,
        REVIEWS,
        page=1,
        per_page=100,
    )
    fail(
        FakeHTTP(Stream(json.dumps([{}] * 100).encode())),
        transport.Failure.PAGINATION,
        REVIEWS,
        page=1,
        per_page=100,
    )
    fake = FakeHTTP(
        header_stream(
            b"[]", Link=link(1, relation="prev") + ", " + link(1, relation="first")
        )
    )
    assert (
        transport.GitHubGETTransport(TOKEN, client=fake)
        .get(REVIEWS, page=2, per_page=100)
        .next_page
        is None
    )
    for body in (
        {"total_count": 101, "jobs": [{}] * 100},
        {"total_count": 4, "jobs": [{}] * 3},
        {"total_count": True, "jobs": []},
        {"jobs": []},
    ):
        fail(
            FakeHTTP(Stream(json.dumps(body).encode())),
            transport.Failure.PAGINATION,
            JOBS,
            page=1,
            per_page=100,
        )
    fake = FakeHTTP(
        header_stream(
            json.dumps({"total_count": 101, "jobs": [{}] * 100}).encode(),
            Link=link(2, JOBS),
        )
    )
    assert (
        transport.GitHubGETTransport(TOKEN, client=fake)
        .get(JOBS, page=1, per_page=100)
        .next_page
        == 2
    )


def test_single_resource_link_cannot_create_a_pagination_proof():
    fail(FakeHTTP(header_stream(Link=link())), transport.Failure.PAGINATION)


def test_real_httpresponse_chunk_framing_complete_and_truncated_without_socket():
    class MemorySocket:
        def __init__(self, wire):
            self.wire = wire

        def makefile(self, mode):
            return io.BytesIO(self.wire)

    for wire, success in (
        (b"2\r\n{}\r\n0\r\n\r\n", True),
        (b"2\r\n{}\r\n", False),
        (b"4\r\n{}", False),
    ):
        response = HTTPResponse(
            MemorySocket(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n" + wire
            )
        )
        response.begin()
        response.url = ORIGIN + PREFIX
        fake = FakeHTTP(response)
        if success:
            assert (
                transport.GitHubGETTransport(TOKEN, client=fake).get(PREFIX).data == {}
            )
        else:
            fail(fake, transport.Failure.BODY)
        assert response.closed


def test_stdlib_backend_builds_verified_get_and_blocks_every_redirect(monkeypatch):
    calls, handlers = [], []

    class Opener:
        def open(self, request, *, timeout):
            calls.append(request)
            assert (
                timeout == 10 and request.get_method() == "GET" and request.data is None
            )
            assert request.get_header("Authorization") == "Bearer " + TOKEN
            return Stream(url=request.full_url)

    def build(*items):
        handlers.extend(items)
        return Opener()

    monkeypatch.setattr(transport, "build_opener", build)
    assert transport.GitHubGETTransport(TOKEN).get(PREFIX).status == 200
    secure = next(h for h in handlers if isinstance(h, transport.HTTPSHandler))
    assert (
        secure._context.check_hostname
        and secure._context.verify_mode == ssl.CERT_REQUIRED
    )
    redirect = next(h for h in handlers if isinstance(h, transport._NoRedirect))
    for url in (ORIGIN + PREFIX, "https://private.invalid/PRIVATE_INPUT"):
        assert redirect.redirect_request(calls[0], None, 302, "", {}, url) is None
    assert len(calls) == 1


def test_stdlib_http_error_is_closed_without_reading_private_error_body(monkeypatch):
    body = io.BytesIO((TOKEN + " PRIVATE_INPUT").encode())

    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError(ORIGIN + PREFIX, 403, "PRIVATE_INPUT", Message(), body)

    monkeypatch.setattr(transport, "build_opener", lambda *args: Opener())
    with pytest.raises(transport.TransportFailure) as caught:
        transport.GitHubGETTransport(TOKEN).get(PREFIX)
    assert caught.value.code is transport.Failure.FORBIDDEN
    assert body.closed and caught.value.__context__ is None


def test_existing_validator_compatible_double_read_recheck_and_no_execution():
    fake = FakeHTTP(payloads=evidence_fixture())
    reader = transport.GitHubGETTransport(TOKEN, client=fake)
    first = read_evidence(reader, REQUEST)
    assert first.error is None and first.can_start is False and not first
    assert first.execution == "NOT RUN" and first.actions_result == "FAILURE"
    assert len(fake.calls) == 12 and all(s.closed for s in fake.streams)
    second = read_evidence(reader, REQUEST, first)
    assert second.error is None and not second and not second.can_start
    missing_review = copy.deepcopy(evidence_fixture())
    missing_review["/pulls/27/reviews"] = []
    refused = read_evidence(
        transport.GitHubGETTransport(TOKEN, client=FakeHTTP(payloads=missing_review)),
        REQUEST,
    )
    assert refused.error is Error.REVIEW and all(
        f.state is State.UNKNOWN for f in refused.facts
    )
    refused = read_evidence(
        transport.GitHubGETTransport(TOKEN, client=FakeHTTP(Stream(status=403))),
        REQUEST,
    )
    assert refused.error is Error.API_UNAVAILABLE and not refused.can_start
    assert TOKEN not in repr(first) + repr(second) + repr(refused)


def test_no_env_token_discovery_live_callers_or_cli(capsys):
    path = ROOT / "scripts/github_campaign_transport.py"
    tree = ast.parse(path.read_text())
    assert not any(
        isinstance(n, ast.Name)
        and n.id in {"print", "input", "getenv", "environ", "eval", "exec"}
        for n in ast.walk(tree)
    )
    shared_types = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        and n.module == "scripts.github_campaign_evidence"
    ]
    assert len(shared_types) == 1
    assert {n.name for n in shared_types[0].names} == {"PREFIX", "Reply"}
    for folder in (".github", "scripts", "custom_components"):
        assert not any(
            "github_campaign_transport" in p.read_text()
            for p in (ROOT / folder).rglob("*")
            if p != path and p.is_file() and p.suffix in {".yml", ".cjs", ".py"}
        )
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
    assert capsys.readouterr() == ("", "")
