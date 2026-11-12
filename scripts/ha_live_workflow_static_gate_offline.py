"""#207 D4-C1: conservative *offline* YAML structure audit, never a live gate.

A syntactically credible workflow cannot prove shell behavior, durable claims,
actual reviewer approval, execution or GitHub provenance. No calls or secrets.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Any

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

WORKFLOW = ".github/workflows/hoben-ha-manual.yml"
ROOT = "/repos/Guillaume0385/ha-hoben-community"
GROUP = "hoben-read-only-observation"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SHA = re.compile(r"[a-f0-9]{40}\Z")
MAX_YAML_BYTES = 48 * 1024
MAX_NODES = 800
MAX_DEPTH = 16

# Exact, closed expressions. Merely finding a substring such as 'recheck' in
# shell or comments would not establish any execution ordering.
ENTRY = (
    "${{ github.repository == 'Guillaume0385/ha-hoben-community' && "
    "github.ref == 'refs/heads/experimental' && "
    "github.actor == 'Guillaume0385' && "
    "github.triggering_actor == 'Guillaume0385' && "
    "github.event_name == 'workflow_dispatch' && "
    "github.run_attempt == 1 && inputs.scenario == 'hoben-live' }}"
)
CLAIM_IF = (
    "${{ needs.preflight.result == 'success' && "
    "needs.preflight.outputs.admitted == 'true' }}"
)
COLLECT_IF = (
    "${{ needs.claim.result == 'success' && "
    "needs.claim.outputs.claim_ref != '' }}"
)
WORKER_IF = (
    "${{ success() && steps.recheck.outcome == 'success' && "
    "steps.recheck.outputs.allowed == 'true' }}"
)
ALWAYS = "${{ always() }}"


class _Refused(Exception):
    """Private validation exception. Never include input in public errors."""


def _require(condition: bool) -> None:
    if not condition:
        raise _Refused


def _keys(value: Any, required: set[str]) -> None:
    _require(type(value) is dict and set(value) == required)


def _guard_tree(value: Any, depth: int = 0, count: list[int] | None = None) -> None:
    if count is None:
        count = [0]
    count[0] += 1
    _require(count[0] <= MAX_NODES and depth <= MAX_DEPTH)
    if type(value) is dict:
        for key, child in value.items():
            _require(type(key) is str and len(key) <= 128)
            _guard_tree(child, depth + 1, count)
    elif type(value) is list:
        _require(len(value) <= 100)
        for child in value:
            _guard_tree(child, depth + 1, count)
    else:
        _require(type(value) in (str, int, bool, type(None)))
        if type(value) is str:
            _require(len(value) <= MAX_YAML_BYTES * 2)


class _StrictLoader(yaml.SafeLoader):
    """Do not apply YAML 1.1's surprising 'on' => boolean resolution."""


_StrictLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in rules if tag != "tag:yaml.org,2002:bool"]
    for k, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false|True|False)$"), list("tTfF")
)


def _mapping(loader: _StrictLoader, node: MappingNode) -> dict[str, Any]:
    _require(isinstance(node, MappingNode))
    result: dict[str, Any] = {}
    for key_node, val_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        _require(type(key) is str and key not in result and key != "<<")
        result[key] = loader.construct_object(val_node, deep=True)
    return result


_StrictLoader.add_constructor("tag:yaml.org,2002:map", _mapping)


def _decode_yaml(text: str) -> dict[str, Any]:
    _require(type(text) is str and 0 < len(text.encode("utf-8")) <= MAX_YAML_BYTES)
    # Structural token inspection also rejects alias expansion, explicit YAML
    # type tags, merge tricks and repeated anchors before constructing values.
    for token in yaml.scan(text, Loader=_StrictLoader):
        _require(not isinstance(token, (AliasToken, AnchorToken, TagToken)))
    doc = yaml.load(text, Loader=_StrictLoader)
    _guard_tree(doc)
    _require(type(doc) is dict)
    return doc


def _source_text(source: dict[str, Any], commit_sha: str) -> str:
    _keys(source, {"request", "status", "items", "next"})
    _require(source["status"] == 200 and type(source["status"]) is int)
    _require(source["next"] is None)
    route = f"{ROOT}/contents/{WORKFLOW}?ref={commit_sha}"
    _require(source["request"] == route)
    item = source["items"]
    _keys(item, {"path", "sha", "encoding", "content"})
    _require(item["path"] == WORKFLOW and item["encoding"] == "base64")
    _require(type(item["sha"]) is str and SHA.fullmatch(item["sha"]) is not None)
    content = item["content"]
    _require(type(content) is str and len(content) <= MAX_YAML_BYTES * 2)
    # GitHub Contents REST may wrap base64 with LF; no other whitespace,
    # non-canonical base64, decompression, redirects or remote fallback.
    _require(re.fullmatch(r"[A-Za-z0-9+/=\n]+", content) is not None)
    encoded = content.replace("\n", "")
    raw = base64.b64decode(encoded, validate=True)
    _require(base64.b64encode(raw).decode("ascii") == encoded)
    _require(0 < len(raw) <= MAX_YAML_BYTES)
    blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    _require(hashlib.sha1(blob).hexdigest() == item["sha"])
    return raw.decode("utf-8", errors="strict")


def _script(step: dict[str, Any], sid: str, *, condition: str | None = None,
            secret: bool = False, claim_ref: bool = False) -> None:
    expected = {"id", "run", "shell"}
    if condition is not None:
        expected.add("if")
    if secret or claim_ref:
        expected.add("env")
    _keys(step, expected)
    _require(step["id"] == sid and step["shell"] == "bash")
    # Content cannot be reasoned about safely by a structural audit. It can
    # never elevate the verdict from structural candidate to live permission.
    run = step["run"]
    _require(type(run) is str and 1 <= len(run) <= 2048)
    _require("${{" not in run and "secrets." not in run)
    if condition is not None:
        _require(step["if"] == condition)
    if secret:
        _keys(step["env"], {"HOBEN_USER_GUID"})
        _require(step["env"]["HOBEN_USER_GUID"] == "${{ secrets.HOBEN_USER_GUID }}")
    if claim_ref:
        _keys(step["env"], {"CLAIM_REF"})
        _require(step["env"]["CLAIM_REF"] == "${{ needs.claim.outputs.claim_ref }}")


def _checkout(step: dict[str, Any]) -> None:
    _keys(step, {"id", "uses", "with"})
    _require(step["id"] == "checkout" and step["uses"] == CHECKOUT)
    _keys(step["with"], {"ref", "persist-credentials"})
    _require(step["with"]["ref"] == "${{ github.sha }}")
    _require(step["with"]["persist-credentials"] is False)


def _job(job: dict[str, Any], name: str) -> None:
    base = {"runs-on", "timeout-minutes", "permissions", "steps"}
    if name != "preflight":
        base |= {"needs", "if"}
    else:
        base.add("if")
    if name in ("preflight", "claim"):
        base.add("outputs")
    if name == "collect":
        base.add("environment")
    _keys(job, base)
    _require(job["runs-on"] == "ubuntu-latest")
    _require(type(job["timeout-minutes"]) is int and 1 <= job["timeout-minutes"] <= 40)
    permissions = {"contents": "write"} if name == "claim" else (
        {"contents": "read"} if name in ("collect", "result") else {}
    )
    _require(job["permissions"] == permissions)
    expected = {
        "preflight": (None, ENTRY),
        "claim": ("preflight", CLAIM_IF),
        "collect": ("claim", COLLECT_IF),
        "result": ("collect", ALWAYS),
    }
    needs, cond = expected[name]
    _require(job["if"] == cond)
    if needs is not None:
        _require(job["needs"] == needs)
    if name == "preflight":
        _keys(job["outputs"], {"admitted"})
        _require(
            job["outputs"]["admitted"] == "${{ steps.preflight.outputs.admitted }}"
        )
    if name == "claim":
        _keys(job["outputs"], {"claim_ref"})
        _require(job["outputs"]["claim_ref"] == "${{ steps.claim.outputs.claim_ref }}")
    if name == "collect":
        _require(job["environment"] == "hoben-live")
    steps = job["steps"]
    _require(type(steps) is list)
    ids = {"preflight": ["checkout", "preflight"], "claim": ["checkout", "claim"],
           "collect": ["checkout", "recheck", "worker", "cleanup"],
           "result": ["checkout", "publish"]}[name]
    _require([s.get("id") if type(s) is dict else None for s in steps] == ids)
    _checkout(steps[0])
    if name == "preflight":
        _script(steps[1], "preflight")
    elif name == "claim":
        _script(steps[1], "claim")
    elif name == "collect":
        _script(steps[1], "recheck", claim_ref=True)
        _script(steps[2], "worker", condition=WORKER_IF, secret=True)
        _script(steps[3], "cleanup", condition=ALWAYS)
    else:
        _script(steps[1], "publish")


def _structure(tree: dict[str, Any]) -> None:
    _keys(tree, {"name", "on", "permissions", "concurrency", "jobs"})
    _require(tree["name"] == "Vérification réelle Home Assistant")
    _keys(tree["on"], {"workflow_dispatch"})
    _keys(tree["on"]["workflow_dispatch"], {"inputs"})
    _keys(tree["on"]["workflow_dispatch"]["inputs"], {"scenario"})
    selection = tree["on"]["workflow_dispatch"]["inputs"]["scenario"]
    _keys(selection, {"type", "required", "default", "options"})
    _require(selection == {"type": "choice", "required": True,
                           "default": "hoben-live", "options": ["hoben-live"]})
    _require(tree["permissions"] == {})
    _keys(tree["concurrency"], {"group", "cancel-in-progress", "queue"})
    _require(
        tree["concurrency"]
        == {"group": GROUP, "cancel-in-progress": False, "queue": "max"}
    )
    jobs = tree["jobs"]
    _keys(jobs, {"preflight", "claim", "collect", "result"})
    for name, job in jobs.items():
        _job(job, name)


@dataclass(frozen=True)
class AuditVerdict:
    """Offline-only structural result; never an authorization or an attestation."""

    execution: str = "offline"
    admission: str = "NOT RUN"
    secrets_allowed: bool = False
    live_ready: bool = False
    complete: bool = False
    structure: str = "REFUSED"


def audit_workflow(
    payload: Any, *, expected_commit_sha: str | None = None
) -> AuditVerdict:
    """Audit synthetic YAML, AST or B1/B2 single-page Contents REST fixture.

    A structural candidate *never* grants a live run, authenticated evidence,
    a durable anti-replay claim, environment approval or secret access.
    Any unresolvable or malformed input refuses without echoing its bytes.
    """
    try:
        _guard_tree(payload)
        if type(payload) is str:
            tree = _decode_yaml(payload)
        elif type(payload) is dict and "request" in payload:
            _require(
                type(expected_commit_sha) is str
                and SHA.fullmatch(expected_commit_sha) is not None
            )
            tree = _decode_yaml(_source_text(payload, expected_commit_sha))
        else:
            _require(type(payload) is dict)
            tree = payload
        _structure(tree)
        return AuditVerdict(structure="CANDIDATE_ONLY")
    except (Exception, binascii.Error, UnicodeError):
        # Public failures are a fixed category; no private YAML or token echo.
        return AuditVerdict()
