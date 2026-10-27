"""Only synthetic REST responses; no GitHub/Hoben network or credentials."""

import ast
import copy
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from scripts.github_campaign_evidence import (
    CHECKS,
    PREFIX,
    Error,
    FactName,
    Observation,
    Reply,
    Request,
    State,
    read_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
SHA, TREE = "a" * 40, "b" * 40
PR, RUN = 27, 12345
BRANCH = "codex/offline-evidence"
REQUEST = Request(PR, SHA, BRANCH, RUN)
CREATED = "2026-10-27T10:00:00Z"
DONE = "2026-10-27T10:01:00Z"
REVIEWED = "2026-10-27T10:02:00Z"
MERGED = "2026-10-27T10:03:00Z"


def owner():
    return {"id": 18246624, "login": "Guillaume0385", "type": "User"}


def repo():
    return {
        "id": 1401398724,
        "full_name": "Guillaume0385/ha-hoben-community",
        "owner": owner(),
    }


def review(number=90, state="APPROVED", sha=SHA, user=None, date=REVIEWED):
    return {
        "id": number,
        "user": owner() if user is None else user,
        "state": state,
        "commit_id": sha,
        "submitted_at": date,
        "body": "PRIVATE_INPUT is never exported",
    }


def fixture():
    head = {"sha": SHA, "ref": BRANCH, "repo": repo()}
    base = {"ref": "experimental", "repo": repo()}
    return {
        "": repo(),
        "/git/commits/" + SHA: {"sha": SHA, "tree": {"sha": TREE}},
        f"/pulls/{PR}": {
            "number": PR,
            "draft": False,
            "head": head,
            "base": base,
            "state": "open",
            "merged": False,
            "merged_at": None,
            "updated_at": REVIEWED,
            "merge_commit_sha": "c" * 40,
            "body": "PRIVATE_INPUT",
        },
        f"/actions/runs/{RUN}": {
            "id": RUN,
            "head_sha": SHA,
            "head_commit": {"id": SHA},
            "head_branch": BRANCH,
            "event": "pull_request",
            "run_attempt": 1,
            "workflow_id": 373497148,
            "path": ".github/workflows/validate.yml",
            "status": "completed",
            "conclusion": "success",
            "repository": repo(),
            "head_repository": repo(),
            "created_at": CREATED,
            "updated_at": DONE,
            "pull_requests": [{"number": PR, "head": head, "base": base}],
            "html_url": "PRIVATE_INPUT",
        },
        f"/actions/runs/{RUN}/attempts/1/jobs": {
            "total_count": 4,
            "jobs": [
                {
                    "name": name,
                    "id": i + 100,
                    "run_id": RUN,
                    "run_attempt": 1,
                    "head_sha": SHA,
                    "head_branch": BRANCH,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": CREATED,
                    "completed_at": DONE,
                    "steps": [{"name": "PRIVATE_INPUT"}],
                }
                for i, name in enumerate(CHECKS)
            ],
        },
        f"/pulls/{PR}/reviews": [review()],
    }


class Fake:
    """A fresh fixture per pass; mirrors only the injected GET interface."""

    def __init__(self, first=None, second=None):
        self.first = fixture() if first is None else first
        self.second = self.first if second is None else second
        self.calls = []
        self.pass_number = -1
        self.replies = {}

    def get(self, path, *, page=None, per_page=None):
        assert path.startswith(PREFIX)
        if path == PREFIX:
            self.pass_number += 1
        self.calls.append((path, page, per_page))
        value = self.replies.get((path, page))
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return value
        source = self.first if self.pass_number == 0 else self.second
        return Reply(200, copy.deepcopy(source[path[len(PREFIX) :]]), None)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in offline evidence tests")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def never_starts(result):
    assert type(result) is Observation
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert result.can_start is False and not result
    assert "PRIVATE_INPUT" not in repr(result)
    assert all(
        type(f.name) is FactName and type(f.state) is State for f in result.facts
    )


def refused(fake, error=None, request=REQUEST, previous=None):
    result = read_evidence(fake, request, previous)
    never_starts(result)
    assert result.error is not None
    if error is not None:
        assert result.error is error
    assert all(f.state is State.UNKNOWN for f in result.facts)
    return result


def mutate(data, path, value):
    parent = data
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = value


def test_positive_projection_has_only_six_attested_facts_and_no_authority():
    fake = Fake()
    result = read_evidence(fake, REQUEST)
    assert result.error is None
    never_starts(result)
    known = {f.name for f in result.facts if f.state is State.ATTESTED}
    assert known == {
        FactName.REPOSITORY,
        FactName.COMMIT,
        FactName.PR,
        FactName.REVIEW,
        FactName.CI,
        FactName.CHECKS,
    }
    assert len(result.facts) == len(FactName) and len(fake.calls) == 12
    assert {f.name for f in fields(result)} == {
        "facts",
        "error",
        "_binding",
        "_request",
        "execution",
        "actions_result",
        "can_start",
    }
    with pytest.raises(FrozenInstanceError):
        result.can_start = True
    with pytest.raises(FrozenInstanceError):
        result.facts[0].state = State.ATTESTED
    fake.first[""]["full_name"] = "PRIVATE_INPUT"
    assert result.error is None and "PRIVATE_INPUT" not in repr(result)
    assert len(result._binding) == len(result._request) == 64


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        True,
        Request(True, SHA, BRANCH, RUN),
        Request(PR, "PRIVATE_INPUT", BRANCH, RUN),
        Request(PR, SHA, "PRIVATE_INPUT@other", RUN),
        Request(PR, SHA, "main", RUN),
        Request(PR, SHA, BRANCH, 0),
        Request(PR, SHA, BRANCH, RUN, "refs/heads/main"),
    ],
)
def test_untrusted_request_or_main_ref_refused_before_any_get(bad):
    fake = Fake()
    refused(fake, Error.INVALID_REQUEST, bad)
    assert fake.calls == []


@pytest.mark.parametrize(
    "status,category",
    [
        (401, Error.API_FORBIDDEN),
        (403, Error.API_FORBIDDEN),
        (404, Error.API_NOT_FOUND),
        (429, Error.API_RATE_LIMITED),
        (500, Error.API_UNAVAILABLE),
        (502, Error.API_UNAVAILABLE),
        (503, Error.API_UNAVAILABLE),
        (301, Error.API_HTTP),
        (201, Error.API_HTTP),
    ],
)
@pytest.mark.parametrize(
    "route,page",
    [
        ("", None),
        (f"/pulls/{PR}/reviews", 1),
        (f"/actions/runs/{RUN}/attempts/1/jobs", 1),
    ],
)
def test_api_failures_fixed_no_retry_no_empty_success(status, category, route, page):
    fake = Fake()
    fake.replies[(PREFIX + route, page)] = Reply(
        status, {"message": "PRIVATE_INPUT"}, None
    )
    refused(fake, category)
    assert sum(c[:2] == (PREFIX + route, page) for c in fake.calls) == 1


@pytest.mark.parametrize(
    "reply",
    [
        Reply(True, {}, None),
        Reply(200, [], None),
        Reply(200, {}, 2),
        None,
        True,
        {"attested": True},
    ],
)
def test_malformed_transport_or_shape_is_not_a_boolean_attestation(reply):
    class Malformed:
        def get(self, *args, **kwargs):
            return reply

    refused(Malformed())


def test_transport_exception_body_and_private_url_never_escape(capsys):
    fake = Fake()
    fake.replies[(PREFIX, None)] = RuntimeError("PRIVATE_INPUT: token/body/url")
    refused(fake, Error.API_UNAVAILABLE)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "path,value",
    [
        (("", "id"), 1),
        (("", "full_name"), "spoof/ha-hoben-community"),
        (("", "owner", "id"), 1),
        (("", "owner", "login"), "spoof"),
        (("/git/commits/" + SHA, "sha"), "d" * 40),
        (("/git/commits/" + SHA, "tree", "sha"), "PRIVATE_INPUT"),
        ((f"/pulls/{PR}", "number"), True),
        ((f"/pulls/{PR}", "draft"), True),
        ((f"/pulls/{PR}", "head", "sha"), "d" * 40),
        ((f"/pulls/{PR}", "head", "ref"), "other"),
        ((f"/pulls/{PR}", "base", "ref"), "main"),
        ((f"/pulls/{PR}", "head", "repo", "id"), 1),
        ((f"/pulls/{PR}", "base", "repo", "full_name"), "spoof/repo"),
        ((f"/actions/runs/{RUN}", "id"), RUN + 1),
        ((f"/actions/runs/{RUN}", "head_sha"), "d" * 40),
        ((f"/actions/runs/{RUN}", "head_commit", "id"), "d" * 40),
        ((f"/actions/runs/{RUN}", "head_branch"), "main"),
        ((f"/actions/runs/{RUN}", "event"), "push"),
        ((f"/actions/runs/{RUN}", "run_attempt"), 2),
        ((f"/actions/runs/{RUN}", "run_attempt"), True),
        ((f"/actions/runs/{RUN}", "workflow_id"), 1),
        ((f"/actions/runs/{RUN}", "path"), ".github/workflows/spoof.yml"),
        (
            (f"/actions/runs/{RUN}", "path"),
            ".github/workflows/validate.yml@refs/heads/main",
        ),
        ((f"/actions/runs/{RUN}", "status"), "in_progress"),
        ((f"/actions/runs/{RUN}", "conclusion"), "neutral"),
        ((f"/actions/runs/{RUN}", "repository", "id"), 1),
        ((f"/actions/runs/{RUN}", "head_repository", "full_name"), "spoof/repo"),
        ((f"/actions/runs/{RUN}", "pull_requests"), []),
        ((f"/actions/runs/{RUN}", "pull_requests", 0, "number"), PR + 1),
        ((f"/actions/runs/{RUN}", "pull_requests", 0, "head", "sha"), "d" * 40),
        ((f"/actions/runs/{RUN}", "pull_requests", 0, "base", "ref"), "main"),
        ((f"/actions/runs/{RUN}", "updated_at"), "2026-10-27T09:59:59Z"),
    ],
)
def test_spoofing_heads_workflows_prs_repositories_and_nonterminal_runs(path, value):
    data = fixture()
    mutate(data, path, value)
    refused(Fake(data))


@pytest.mark.parametrize(
    "key,value",
    [
        ("name", "other"),
        ("run_id", RUN + 1),
        ("run_attempt", 2),
        ("head_sha", "d" * 40),
        ("head_branch", "main"),
        ("status", "queued"),
        ("conclusion", "skipped"),
        ("conclusion", "failure"),
        ("completed_at", "2026-10-27T10:04:00Z"),
        ("id", True),
    ],
)
def test_jobs_must_come_from_this_actions_run_attempt_and_candidate(key, value):
    data = fixture()
    data[f"/actions/runs/{RUN}/attempts/1/jobs"]["jobs"][0][key] = value
    refused(Fake(data))


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate_name", "duplicate_id", "extra", "status_instead_of_job"],
)
def test_check_cardinality_and_commit_status_are_not_ci_proof(change):
    data = fixture()
    collection = data[f"/actions/runs/{RUN}/attempts/1/jobs"]
    jobs = collection["jobs"]
    if change == "missing":
        jobs.pop()
    elif change == "duplicate_name":
        jobs[0]["name"] = jobs[1]["name"]
    elif change == "duplicate_id":
        jobs[0]["id"] = jobs[1]["id"]
    elif change == "extra":
        jobs.append(copy.deepcopy(jobs[0]))
    else:
        jobs[0] = {"context": "tests", "state": "success", "sha": SHA}
    collection["total_count"] = len(jobs)
    refused(Fake(data))


@pytest.mark.parametrize(
    "reviews",
    [
        [],
        [review(state="COMMENTED")],
        [review(state="DISMISSED")],
        [review(state="CHANGES_REQUESTED")],
        [review(sha="d" * 40)],
        [review(user={"id": 1, "login": "spoof", "type": "User"})],
        [review(user={"id": 1, "login": "Guillaume0385", "type": "User"})],
        [review(user={"id": 18246624, "login": "spoof", "type": "User"})],
        [review(state="PENDING")],
        [review(), review()],
        [review(), review(91, "DISMISSED", date=MERGED)],
    ],
)
def test_missing_stale_spoofed_or_dismissed_manager_review_is_not_attested(reviews):
    data = fixture()
    data[f"/pulls/{PR}/reviews"] = reviews
    refused(Fake(data))


def test_latest_reviews_and_changes_requested_are_processed_independently_of_order():
    other = {"id": 2, "login": "independent", "type": "User"}
    data = fixture()
    reviews = data[f"/pulls/{PR}/reviews"]
    reviews.extend(
        [
            review(91, "CHANGES_REQUESTED", user=other),
            review(92, "COMMENTED", user=other, date=MERGED),
        ]
    )
    refused(Fake(data), Error.REVIEW)
    reviews.append(review(93, "DISMISSED", user=other, date=MERGED))
    reviews.reverse()
    result = read_evidence(Fake(data), REQUEST)
    assert result.error is None
    never_starts(result)


def test_merged_pr_still_requires_explicit_current_head_review_and_ci_association():
    data = fixture()
    pr = data[f"/pulls/{PR}"]
    pr.update(state="closed", merged=True, merged_at=MERGED, merged_by=owner())
    assert read_evidence(Fake(data), REQUEST).error is None
    data[f"/pulls/{PR}/reviews"] = []
    refused(Fake(data), Error.REVIEW)  # merged_by alone is never a review
    data[f"/pulls/{PR}/reviews"] = [review()]
    data[f"/actions/runs/{RUN}"]["pull_requests"] = []
    refused(Fake(data), Error.CI)  # no fallback when GitHub clears associations


@pytest.mark.parametrize(
    "route,key",
    [(f"/pulls/{PR}/reviews", None), (f"/actions/runs/{RUN}/attempts/1/jobs", "jobs")],
)
def test_all_pages_read_and_pinned_without_following_arbitrary_links(route, key):
    fake = Fake()
    items = copy.deepcopy(fake.first[route] if key is None else fake.first[route][key])
    if key is None:
        items.append(review(91, "COMMENTED"))

    def wrap(values):
        return values if key is None else {"total_count": len(items), key: values}

    fake.replies[(PREFIX + route, 1)] = Reply(200, wrap(items[:1]), 2)
    fake.replies[(PREFIX + route, 2)] = Reply(200, wrap(items[1:]), None)
    result = read_evidence(fake, REQUEST)
    assert result.error is None
    assert sum(c[0] == PREFIX + route for c in fake.calls) == 4
    never_starts(result)


@pytest.mark.parametrize(
    "next_page", [0, 1, 3, True, "PRIVATE_INPUT", "https://private.invalid"]
)
def test_pagination_loops_skips_urls_or_boolean_metadata_refuse(next_page):
    fake = Fake()
    fake.replies[(PREFIX + f"/pulls/{PR}/reviews", 1)] = Reply(
        200, [review()], next_page
    )
    refused(fake, Error.PAGINATION)


def test_missing_page_totals_full_terminal_review_page_and_page_limit_refuse():
    route = PREFIX + f"/actions/runs/{RUN}/attempts/1/jobs"
    fake = Fake()
    fake.replies[(route, 1)] = Reply(
        200,
        {
            "total_count": 5,
            "jobs": fixture()[f"/actions/runs/{RUN}/attempts/1/jobs"]["jobs"],
        },
        None,
    )
    refused(fake, Error.PAGINATION)
    fake = Fake()
    route = PREFIX + f"/pulls/{PR}/reviews"
    fake.replies[(route, 1)] = Reply(200, [review(i + 100) for i in range(100)], None)
    refused(fake, Error.PAGINATION)
    fake = Fake()
    for page in range(1, 11):
        fake.replies[(route, page)] = Reply(200, [review(page + 100)], page + 1)
    refused(fake, Error.PAGINATION)
    assert len(fake.calls) < 20


def test_changing_total_empty_nonterminal_and_duplicate_across_pages_refuse():
    jobs = fixture()[f"/actions/runs/{RUN}/attempts/1/jobs"]["jobs"]
    route = PREFIX + f"/actions/runs/{RUN}/attempts/1/jobs"
    fake = Fake()
    fake.replies[(route, 1)] = Reply(200, {"total_count": 4, "jobs": jobs[:1]}, 2)
    fake.replies[(route, 2)] = Reply(200, {"total_count": 5, "jobs": jobs[1:]}, None)
    refused(fake, Error.PAGINATION)
    route = PREFIX + f"/pulls/{PR}/reviews"
    fake = Fake()
    fake.replies[(route, 1)] = Reply(200, [], 2)
    refused(fake, Error.PAGINATION)
    fake = Fake()
    fake.replies[(route, 1)] = Reply(200, [review()], 2)
    fake.replies[(route, 2)] = Reply(200, [review()], None)
    refused(fake, Error.REVIEW)


@pytest.mark.parametrize(
    "path,value",
    [
        ((f"/pulls/{PR}", "head", "sha"), "d" * 40),
        ((f"/pulls/{PR}", "updated_at"), MERGED),
        ((f"/actions/runs/{RUN}", "run_attempt"), 2),
        ((f"/pulls/{PR}/reviews",), [review(91)]),
    ],
)
def test_movement_during_complete_double_read_refuses(path, value):
    first, second = fixture(), fixture()
    mutate(second, path, value)
    refused(Fake(first, second))


def test_recheck_reads_again_and_compares_all_provenance_without_attesting_approval():
    previous = read_evidence(Fake(), REQUEST)
    current = read_evidence(Fake(), REQUEST, previous)
    assert current.error is None and current._binding == previous._binding
    never_starts(current)
    assert (
        next(f.state for f in current.facts if f.name is FactName.APPROVAL_RECHECK)
        is State.UNKNOWN
    )
    changed = fixture()
    changed[f"/pulls/{PR}"]["updated_at"] = MERGED
    refused(Fake(changed), Error.CHANGED, previous=previous)
    refused(Fake(), Error.PREVIOUS, previous={"attested": True})
    refused(
        Fake(),
        Error.PREVIOUS,
        previous=read_evidence(
            Fake(), Request(PR, SHA, BRANCH, RUN, "refs/heads/main")
        ),
    )
    fake = Fake()
    refused(
        fake, Error.PREVIOUS, request=Request(PR, SHA, "other", RUN), previous=previous
    )
    assert fake.calls == []


def test_every_required_payload_field_missing_or_null_is_refused():
    original = fixture()
    for route, record in original.items():
        records = [record] if type(record) is dict else record
        for index, item in enumerate(records):
            for key in item:
                for missing in (False, True):
                    data = copy.deepcopy(original)
                    target = data[route] if type(record) is dict else data[route][index]
                    if (
                        key in {"body", "html_url", "merge_commit_sha"}
                        or target[key] is None
                    ):
                        continue
                    if missing:
                        del target[key]
                    else:
                        target[key] = None
                    refused(Fake(data))


def test_required_nested_fields_are_not_replaced_by_attested_flags():
    original = fixture()
    paths = (
        ("", "owner"),
        (f"/pulls/{PR}", "head"),
        (f"/pulls/{PR}", "base"),
        (f"/actions/runs/{RUN}", "head_commit"),
        (f"/actions/runs/{RUN}", "head_repository"),
        (f"/actions/runs/{RUN}", "pull_requests", 0, "head"),
        (f"/actions/runs/{RUN}", "pull_requests", 0, "base"),
        (f"/actions/runs/{RUN}/attempts/1/jobs", "jobs", 0),
        (f"/pulls/{PR}/reviews", 0, "user"),
    )
    for path in paths:
        record = original
        for part in path:
            record = record[part]
        for key in record:
            if key == "steps":
                continue
            data = copy.deepcopy(original)
            target = data
            for part in path:
                target = target[part]
            del target[key]
            target["attested"] = True
            refused(Fake(data))


def test_readonly_no_live_imports_callers_io_or_cli():
    path = ROOT / "scripts/github_campaign_evidence.py"
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
        "datetime",
        "enum",
        "typing",
    }
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            assert n.func.id not in {
                "open",
                "print",
                "input",
                "eval",
                "exec",
                "__import__",
            }
    for folder in (".github", "scripts", "custom_components"):
        for source in (ROOT / folder).rglob("*"):
            if (
                source.is_file()
                and source.suffix in {".py", ".cjs", ".yml"}
                and source != path
            ):
                assert "github_campaign_evidence" not in source.read_text()
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
