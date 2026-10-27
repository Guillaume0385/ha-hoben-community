"""Bounded GitHub GET transport; no workflow, admission, token discovery or CLI."""

import json
import math
import re
import ssl
import time
from enum import Enum
from http.client import IncompleteRead
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

if __name__ == "__main__":
    raise SystemExit(1)
else:
    from scripts.github_campaign_evidence import PREFIX, Reply

ORIGIN = "https://api.github.com"
TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_PAGES = 10
_ID = r"([1-9][0-9]{0,15})"


class Failure(Enum):
    """Only fixed categories may leave the HTTP boundary."""

    AUTH = "transport_auth_missing_or_invalid"
    REQUEST = "transport_request_refused"
    TLS = "transport_tls_unverified"
    REDIRECT = "transport_redirect_refused"
    FORBIDDEN = "transport_http_forbidden"
    NOT_FOUND = "transport_http_not_found"
    RATE_LIMIT = "transport_http_rate_limited"
    HTTP = "transport_http_failure"
    NETWORK = "transport_network_failure"
    TIMEOUT = "transport_timeout"
    HEADERS = "transport_headers_invalid"
    SIZE = "transport_response_too_large"
    BODY = "transport_body_invalid_or_incomplete"
    JSON = "transport_json_invalid"
    PAGINATION = "transport_pagination_unverified"
    SECRET = "transport_secret_echo_refused"


class TransportFailure(Exception):
    """No raw exception, response, URL or token in the message or args."""

    def __init__(self, code):
        self.code = code if type(code) is Failure else Failure.NETWORK
        super().__init__(self.code.value)


class HTTPClient(Protocol):
    """Trusted streaming HTTP boundary, injectable for deterministic tests.

    Implement GET only, respect the verified SSLContext and timeout, never
    redirect/log/cache. The stream supplies status, headers.raw_items()/defects,
    geturl(), read1(n) and close(). read1 detects incomplete chunked framing.
    """

    def open(self, url, *, headers, timeout, context): ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # even same-origin redirects must fail, never resend auth


class _UrllibClient:
    def open(self, url, *, headers, timeout, context):
        # Preserve standard proxy/CA configuration; never install global openers.
        opener = build_opener(HTTPSHandler(context=context), _NoRedirect())
        request = Request(url, headers=headers, method="GET")
        try:
            return opener.open(request, timeout=timeout)
        except HTTPError as response:
            return response  # status inspected without reading an error body


def _need(condition, category):
    if not condition:
        raise TransportFailure(category)


def _tls_context():
    # Unlike create_default_context(), this never enables SSLKEYLOGFILE.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()
    return context


def _verified(context):
    _need(
        isinstance(context, ssl.SSLContext)
        and context.check_hostname is True
        and context.verify_mode == ssl.CERT_REQUIRED
        and context.keylog_filename is None,
        Failure.TLS,
    )


def _route(path, page, per_page):
    _need(type(path) is str and len(path) <= 200, Failure.REQUEST)
    _need(path.startswith(PREFIX), Failure.REQUEST)
    suffix, collection, match = path[len(PREFIX) :], None, None
    if suffix in (
        "",
        "/branches/experimental",
        "/actions/workflows/hoben-protocol-manual.yml",
        "/actions/workflows/hoben-ha-manual.yml",
    ):
        pass
    elif re.fullmatch(r"/git/(?:commits|trees|blobs)/[a-f0-9]{40}", suffix):
        _need(not suffix.endswith("0" * 40), Failure.REQUEST)
    else:
        for pattern, kind in (
            (r"/pulls/" + _ID, None),
            (r"/actions/runs/" + _ID, None),
            (r"/pulls/" + _ID + r"/reviews", "reviews"),
            (r"/actions/runs/" + _ID + r"/attempts/1/jobs", "jobs"),
        ):
            match = re.fullmatch(pattern, suffix)
            if match:
                collection = kind
                break
        _need(match is not None and int(match[1]) <= 2**53 - 1, Failure.REQUEST)
    if collection is None:
        _need(page is None and per_page is None, Failure.REQUEST)
        return ORIGIN + path, collection
    _need(
        type(page) is int
        and 1 <= page <= MAX_PAGES
        and type(per_page) is int
        and per_page == 100,
        Failure.REQUEST,
    )
    return ORIGIN + path + f"?page={page}&per_page=100", collection


def _headers(message):
    # email/http parsers may otherwise silently drop a malformed header line.
    _need(type(message.defects) is list and not message.defects, Failure.HEADERS)
    result, size = {}, 0
    for index, (name, value) in enumerate(message.raw_items()):
        _need(index < 100 and type(name) is str and type(value) is str, Failure.HEADERS)
        size += len(name) + len(value)
        _need(size <= MAX_HEADER_BYTES, Failure.HEADERS)
        _need(re.fullmatch(r"[A-Za-z0-9-]+", name) is not None, Failure.HEADERS)
        _need(all(32 <= ord(c) <= 126 or c == "\t" for c in value), Failure.HEADERS)
        name = name.lower()
        _need(name not in result, Failure.HEADERS)
        result[name] = value.strip()
    content_type = result.get("content-type", "")
    _need(
        re.fullmatch(
            r'application/(?:json|vnd\.github\+json)(?:;\s*charset=(?:utf-8|"utf-8"))?',
            content_type,
            re.IGNORECASE,
        )
        is not None,
        Failure.HEADERS,
    )
    _need(
        result.get("content-encoding", "identity").lower() == "identity",
        Failure.HEADERS,
    )
    length, transfer = result.get("content-length"), result.get("transfer-encoding")
    _need((length is None) != (transfer is None), Failure.BODY)
    if transfer is not None:
        _need(transfer.lower() == "chunked", Failure.BODY)
        return result, None
    _need(re.fullmatch(r"0|[1-9][0-9]{0,7}", length) is not None, Failure.BODY)
    _need(int(length) <= MAX_RESPONSE_BYTES, Failure.SIZE)
    return result, int(length)


def _body(stream, length, deadline):
    data = bytearray()
    while True:
        _need(time.monotonic() < deadline, Failure.TIMEOUT)
        size = min(65536, MAX_RESPONSE_BYTES + 1 - len(data))
        chunk = stream.read1(size)
        _need(type(chunk) is bytes and len(chunk) <= size, Failure.BODY)
        if not chunk:
            break
        data.extend(chunk)
        _need(len(data) <= MAX_RESPONSE_BYTES, Failure.SIZE)
    _need(time.monotonic() < deadline, Failure.TIMEOUT)
    _need(length is None or len(data) == length, Failure.BODY)
    return bytes(data)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, Failure.JSON)
        result[key] = value
    return result


def _nonfinite(value):
    raise TransportFailure(Failure.JSON)


def _float(value):
    number = float(value)
    _need(math.isfinite(number), Failure.JSON)
    return number


def _json(body, token):
    _need(token.encode("ascii") not in body, Failure.SECRET)
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_nonfinite,
            parse_float=_float,
        )
    except TransportFailure:
        raise
    except Exception:
        raise TransportFailure(Failure.JSON) from None
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        _need(depth <= 64, Failure.JSON)
        if type(item) is str:
            _need(token not in item, Failure.SECRET)
            _need(not any(0xD800 <= ord(c) <= 0xDFFF for c in item), Failure.JSON)
        elif type(item) is dict:
            stack.extend((v, depth + 1) for v in (*item.keys(), *item.values()))
        elif type(item) is list:
            stack.extend((v, depth + 1) for v in item)
    return value


def _next_page(link, path, page, collection, data):
    if collection is None:
        _need(type(data) is dict and link is None, Failure.PAGINATION)
        return None
    relations = {}
    if link is not None:
        _need(type(link) is str and 0 < len(link) <= 8192, Failure.PAGINATION)
        for part in link.split(","):
            match = re.fullmatch(
                r'\s*<([^<>\s]+)>;\s*rel="(next|prev|first|last)"\s*', part
            )
            _need(match is not None, Failure.PAGINATION)
            url, relation = match.groups()
            _need(relation not in relations, Failure.PAGINATION)
            parsed = urlsplit(url)
            _need(
                parsed.scheme == "https"
                and parsed.netloc == "api.github.com"
                and parsed.path == path
                and not parsed.fragment,
                Failure.PAGINATION,
            )
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            _need(
                len(pairs) == 2 and {k for k, v in pairs} == {"page", "per_page"},
                Failure.PAGINATION,
            )
            query = dict(pairs)
            _need(
                query["per_page"] == "100"
                and re.fullmatch(r"[1-9][0-9]?", query["page"]),
                Failure.PAGINATION,
            )
            target = int(query["page"])
            _need(target <= MAX_PAGES, Failure.PAGINATION)
            if relation == "next":
                _need(target == page + 1, Failure.PAGINATION)
            elif relation == "prev":
                _need(page > 1 and target == page - 1, Failure.PAGINATION)
            elif relation == "first":
                _need(target == 1, Failure.PAGINATION)
            else:
                _need(target >= page, Failure.PAGINATION)
            relations[relation] = target
        if relations.get("last", page) > page:
            _need("next" in relations, Failure.PAGINATION)
        if "last" in relations and "next" in relations:
            _need(relations["next"] <= relations["last"], Failure.PAGINATION)
    next_page = relations.get("next")
    if collection == "reviews":
        _need(type(data) is list and len(data) <= 100, Failure.PAGINATION)
        _need(
            len(data) > 0 if next_page is not None else len(data) < 100,
            Failure.PAGINATION,
        )
    else:
        _need(type(data) is dict, Failure.PAGINATION)
        total, jobs = data.get("total_count"), data.get("jobs")
        _need(
            type(total) is int and 0 <= total <= 1000 and type(jobs) is list,
            Failure.PAGINATION,
        )
        _need(
            len(jobs) == min(100, max(0, total - (page - 1) * 100)), Failure.PAGINATION
        )
        _need((next_page is not None) == (total > page * 100), Failure.PAGINATION)
    return next_page


class GitHubGETTransport:
    """Token-injected REST reader; default backend GETs with verified TLS only.

    An injected client is trusted HTTP infrastructure, not caller evidence.
    Credentials and raw HTTP failures never appear in repr or returned errors.
    """

    __slots__ = ("_token", "_client")

    def __init__(self, token, *, client: HTTPClient | None = None):
        _need(
            type(token) is str
            and 8 <= len(token) <= 1024
            and re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token) is not None,
            Failure.AUTH,
        )
        self._token = token
        self._client = _UrllibClient() if client is None else client

    def __repr__(self):
        return "<GitHubGETTransport>"

    def get(self, path, *, page=None, per_page=None):
        """Return a successful Reply or raise only a sanitized fixed category."""
        try:
            return self._get(path, page, per_page)
        except TransportFailure as error:
            category = error.code
        except (TimeoutError, ssl.SSLError) as error:
            category = (
                Failure.TLS if isinstance(error, ssl.SSLError) else Failure.TIMEOUT
            )
        except URLError as error:
            category = (
                Failure.TLS
                if isinstance(error.reason, ssl.SSLError)
                else Failure.TIMEOUT
                if isinstance(error.reason, TimeoutError)
                else Failure.NETWORK
            )
        except IncompleteRead:
            category = Failure.BODY
        except Exception:
            category = Failure.NETWORK
        # Outside every except block: do not retain a private exception context.
        raise TransportFailure(category)

    def _get(self, path, page, per_page):
        url, collection = _route(path, page, per_page)
        context = _tls_context()
        _verified(context)
        deadline = time.monotonic() + TIMEOUT_SECONDS
        stream = self._client.open(
            url,
            timeout=TIMEOUT_SECONDS,
            context=context,
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ha-hoben-community-proof-reader",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        try:
            _verified(context)
            status = stream.status
            _need(type(status) is int, Failure.HTTP)
            if 300 <= status < 400:
                raise TransportFailure(Failure.REDIRECT)
            _need(
                status == 200,
                {
                    401: Failure.FORBIDDEN,
                    403: Failure.FORBIDDEN,
                    404: Failure.NOT_FOUND,
                    429: Failure.RATE_LIMIT,
                }.get(status, Failure.HTTP),
            )
            _need(stream.geturl() == url, Failure.REDIRECT)
            headers, length = _headers(stream.headers)
            data = _json(_body(stream, length, deadline), self._token)
            _verified(context)
            next_page = _next_page(headers.get("link"), path, page, collection, data)
            _need(time.monotonic() < deadline, Failure.TIMEOUT)
            return Reply(200, data, next_page)
        finally:
            stream.close()
