"""Pure static contract for two inert shells; never executes YAML or Bash."""

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

if __name__ == "__main__":
    raise SystemExit(1)
else:
    import yaml

MAX_YAML_BYTES = 16 * 1024
MAX_TOKENS, MAX_NODES, MAX_DEPTH = 512, 128, 12


class Campaign(Enum):
    """The only accepted campaign selectors."""

    PROTOCOL = "protocol"
    HA = "ha"


_CHOICES = MappingProxyType(
    {
        Campaign.PROTOCOL: (
            "tls-only",
            "session-open",
            "read-v4-state",
            "h1h2",
            "session-300",
            "session-reconnect",
            "all",
        ),
        Campaign.HA: (
            "hoben-live",
            "open-errors",
            "refresh-v4",
            "session-reuse",
            "session-reconnect",
            "cleanup",
            "availability",
            "all",
        ),
    }
)
_TITLES = MappingProxyType(
    {
        Campaign.PROTOCOL: "Tests expérimentaux MyHOBEN",
        Campaign.HA: "Vérification réelle Home Assistant",
    }
)


class State(Enum):
    """Attested here means only a static property of supplied bytes."""

    ATTESTED = "attested"
    UNKNOWN = "unknown"


class FactName(Enum):
    """Input syntax/semantics never establish provenance or execution rights."""

    TRIGGER = "static_dispatch_only"
    SCENARIOS = "static_closed_plan_choices"
    PERMISSIONS = "static_empty_workflow_and_job_permissions"
    JOB = "static_single_bounded_inert_job"
    SCRIPT = "static_exact_approved_refusal_sequence"
    SOURCE = "authenticated_source_and_git_identity"
    LOADED_YAML = "yaml_loaded_by_github_at_executed_commit"
    WORKFLOW_REF = "executed_workflow_ref"
    REGISTRY = "actions_workflow_registry"
    UI_MAIN = "ui_and_main_availability"
    ADMISSION = "admission_and_gates"
    PROTECTION = "effective_branch_protection"
    REVIEW = "manager_review"
    APPROVALS = "environment_and_approvals"
    CLAIM = "atomic_claim"
    MUTEX = "mutex"
    REPLAY = "anti_replay"
    FRESHNESS = "global_freshness_and_atomicity"
    AUTHORIZATION = "execution_authorization"


class Error(Enum):
    """No input text, script, parser exception or private value in diagnostics."""

    CAMPAIGN = "invalid_shell_campaign"
    BYTES = "yaml_bytes_required"
    SIZE = "yaml_size_invalid_or_excessive"
    UTF8 = "yaml_utf8_unverified"
    COMPLEXITY = "yaml_complexity_exceeded"
    YAML = "yaml_malformed_or_multiple_documents"
    FEATURE = "yaml_tag_anchor_alias_or_directive_refused"
    SCALAR = "yaml_scalar_or_mapping_key_refused"
    DUPLICATE = "yaml_duplicate_key"
    SUBSTITUTION = "actions_substitution_refused"
    SCHEMA = "shell_schema_unverified"
    TRIGGER = "shell_trigger_unverified"
    SCENARIOS = "shell_scenarios_unverified"
    PERMISSIONS = "shell_permissions_unverified"
    JOB = "shell_job_unverified"
    SCRIPT = "shell_refusal_script_unverified"


@dataclass(frozen=True)
class Fact:
    """Closed static property and state only."""

    name: FactName
    state: State


@dataclass(frozen=True)
class Observation:
    """No YAML/script retained; even success remains NOT RUN/FAILURE."""

    facts: tuple[Fact, ...]
    error: Error | None
    _binding: str | None = field(default=None, repr=False)
    can_start: bool = field(default=False, init=False)
    execution: str = field(default="NOT RUN", init=False)
    actions_result: str = field(default="FAILURE", init=False)

    def __bool__(self):
        return False


_PROVEN = frozenset(
    {
        FactName.TRIGGER,
        FactName.SCENARIOS,
        FactName.PERMISSIONS,
        FactName.JOB,
        FactName.SCRIPT,
    }
)


class _Denied(Exception):
    pass


def _need(condition, error):
    if not condition:
        raise _Denied(error)


class _Loader(yaml.SafeLoader):
    """Local SafeLoader subclass, with no mutation of PyYAML's global loaders."""

    def __init__(self, text):
        super().__init__(text)
        self._depth = self._nodes = 0

    def compose_node(self, parent, index):
        self._nodes += 1
        self._depth += 1
        _need(self._nodes <= MAX_NODES and self._depth <= MAX_DEPTH, Error.COMPLEXITY)
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_object(self, node, deep=False):
        # Only these primitive constructors are needed by the approved schema.
        kind = node.tag.removeprefix("tag:yaml.org,2002:")
        _need(kind in {"map", "seq", "str", "int", "bool"}, Error.SCALAR)
        if kind == "bool":
            _need(node.value in ("true", "false"), Error.SCALAR)
        elif kind == "int":
            _need(
                re.fullmatch(r"0|[1-9][0-9]{0,2}", node.value) is not None, Error.SCALAR
            )
        return super().construct_object(node, deep=deep)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            _need(key_node.tag == "tag:yaml.org,2002:str", Error.SCALAR)
            key = self.construct_object(key_node, deep=deep)
            _need(key not in result, Error.DUPLICATE)
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _parse(text):
    tokens = yaml.scan(text, Loader=yaml.SafeLoader)
    try:
        for count, token in enumerate(tokens, 1):
            _need(count <= MAX_TOKENS, Error.COMPLEXITY)
            _need(
                not isinstance(
                    token,
                    (
                        yaml.tokens.TagToken,
                        yaml.tokens.AnchorToken,
                        yaml.tokens.AliasToken,
                        yaml.tokens.DirectiveToken,
                    ),
                ),
                Error.FEATURE,
            )
    finally:
        tokens.close()
    loader = _Loader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def _closed(value, keys, error):
    _need(
        type(value) is dict
        and all(type(k) is str for k in value)
        and value.keys() == set(keys.split()),
        error,
    )


def _same(value, expected):
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return value.keys() == expected.keys() and all(
            _same(value[k], v) for k, v in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _same(a, b) for a, b in zip(value, expected, strict=True)
        )
    return value == expected


def _script(campaign):
    """Exact five approved printf statements then exit 1, never invoked here."""
    ha = campaign is Campaign.HA
    summaries = (
        "## " + _TITLES[campaign] + " — NOT RUN",
        "Campagne non activée. Tous les choix, y compris all, sont refusés.",
        ("Aucun client ou coordinator exécuté." if ha else "Aucun test réel exécuté.")
        + " Une tâche et une revue distinctes sont nécessaires avant activation.",
        "Résultat global : FAILURE (non activé). Aucune validation "
        + ("Home Assistant." if ha else "protocolaire."),
    )
    lines = [f"printf '%s\\n' '{s}' >> \"$GITHUB_STEP_SUMMARY\"" for s in summaries]
    label = "HA" if ha else "MyHOBEN"
    lines.append(
        f"printf '%s\\n' '::error::NOT RUN: campagne {label} non activée "
        "pour tous les scénarios et toutes les branches.'"
    )
    return "\n".join((*lines, "exit 1", ""))


def _validate(campaign, document):
    _closed(document, "name on permissions jobs", Error.SCHEMA)
    suffix = " (non activés)" if campaign is Campaign.PROTOCOL else " (non activée)"
    _need(document["name"] == _TITLES[campaign] + suffix, Error.SCHEMA)
    _closed(document["on"], "workflow_dispatch", Error.TRIGGER)
    dispatch = document["on"]["workflow_dispatch"]
    _closed(dispatch, "inputs", Error.TRIGGER)
    _closed(dispatch["inputs"], "scenario", Error.SCENARIOS)
    choices = _CHOICES[campaign]
    _need(
        _same(
            dispatch["inputs"]["scenario"],
            {
                "description": (
                    "Choix prévu uniquement — tous les scénarios sont NOT RUN"
                ),
                "required": True,
                "type": "choice",
                "default": choices[0],
                "options": list(choices),
            },
        ),
        Error.SCENARIOS,
    )
    _need(_same(document["permissions"], {}), Error.PERMISSIONS)
    _closed(document["jobs"], "not-activated", Error.JOB)
    job = document["jobs"]["not-activated"]
    _closed(job, "runs-on timeout-minutes permissions steps", Error.JOB)
    _need(
        type(job["runs-on"]) is str
        and job["runs-on"] == "ubuntu-latest"
        and type(job["timeout-minutes"]) is int
        and job["timeout-minutes"] == 1,
        Error.JOB,
    )
    _need(_same(job["permissions"], {}), Error.PERMISSIONS)
    _need(type(job["steps"]) is list and len(job["steps"]) == 1, Error.JOB)
    step = job["steps"][0]
    _closed(step, "name shell run", Error.SCRIPT)
    _need(
        _same(
            step,
            {
                "name": "Refuser toute collecte non activée",
                "shell": "bash",
                "run": _script(campaign),
            },
        ),
        Error.SCRIPT,
    )


def _result(error=None, binding=None):
    return Observation(
        tuple(
            Fact(n, State.ATTESTED if error is None and n in _PROVEN else State.UNKNOWN)
            for n in FactName
        ),
        error,
        binding,
    )


def validate_shell(campaign: Campaign, content: bytes) -> Observation:
    """Check only the approved static subset; never authenticate or execute it."""
    try:
        _need(type(campaign) is Campaign, Error.CAMPAIGN)
        _need(type(content) is bytes, Error.BYTES)
        _need(0 < len(content) <= MAX_YAML_BYTES, Error.SIZE)
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeError:
            raise _Denied(Error.UTF8) from None
        _need(not text.startswith("\ufeff"), Error.UTF8)
        _need("${{" not in text, Error.SUBSTITUTION)
        _validate(campaign, _parse(text))
        return _result(
            binding=hashlib.sha256(
                campaign.value.encode() + b"\0" + content
            ).hexdigest()
        )
    except _Denied as error:
        return _result(error.args[0])
    except Exception:
        return _result(Error.YAML)
