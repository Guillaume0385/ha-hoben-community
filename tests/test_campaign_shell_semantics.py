"""Injected YAML fixtures/mutations only; no shell execution, DNS or sockets."""

import ast
import builtins
import copy
import os
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest
import yaml

import scripts.campaign_shell_semantics as semantics
from scripts.ha_campaign_plan import CHOICES as HA_CHOICES
from scripts.protocol_campaign_plan import CHOICES as PROTOCOL_CHOICES

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = tuple(semantics.Campaign)


def source(campaign=semantics.Campaign.PROTOCOL):
    return (
        ROOT
        / "tests/fixtures/campaign_shells_013"
        / ("hoben-" + campaign.value + "-manual.yml")
    ).read_bytes()


def document(campaign=semantics.Campaign.PROTOCOL):
    return yaml.safe_load(source(campaign))


def encode(value):
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).encode()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in static shell tests")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def never_starts(result):
    assert (
        type(result) is semantics.Observation
        and not result
        and result.can_start is False
    )
    assert result.execution == "NOT RUN" and result.actions_result == "FAILURE"
    assert len(result.facts) == len(semantics.FactName)
    assert all(
        type(f.name) is semantics.FactName and type(f.state) is semantics.State
        for f in result.facts
    )
    assert "SYNTHETIC_PRIVATE_INPUT" not in repr(result)
    assert "printf" not in repr(result) and "GITHUB_STEP_SUMMARY" not in repr(result)


def refused(result, error=None):
    never_starts(result)
    assert type(result.error) is semantics.Error
    if error is not None:
        assert result.error is error
    assert all(f.state is semantics.State.UNKNOWN for f in result.facts)
    assert result._binding is None


@pytest.mark.parametrize("campaign", CAMPAIGNS)
def test_historical_shell_and_reserialization_match_static_contract_only(
    campaign,
):
    for data in (source(campaign), encode(document(campaign))):
        result = semantics.validate_shell(campaign, data)
        assert result.error is None
        never_starts(result)
        assert len(result._binding) == 64
        assert {
            f.name for f in result.facts if f.state is semantics.State.ATTESTED
        } == {
            semantics.FactName.TRIGGER,
            semantics.FactName.SCENARIOS,
            semantics.FactName.PERMISSIONS,
            semantics.FactName.JOB,
            semantics.FactName.SCRIPT,
        }
    options = document(campaign)["on"]["workflow_dispatch"]["inputs"]["scenario"][
        "options"
    ]
    assert tuple(options) == (
        PROTOCOL_CHOICES if campaign is semantics.Campaign.PROTOCOL else HA_CHOICES
    )


@pytest.mark.parametrize(
    "bad", [None, True, "protocol", "ha", "main", "SYNTHETIC_PRIVATE_INPUT", {}, []]
)
def test_only_campaign_enum_is_accepted(bad):
    refused(semantics.validate_shell(bad, source()), semantics.Error.CAMPAIGN)


@pytest.mark.parametrize("campaign", CAMPAIGNS)
def test_current_workflow_is_outside_historical_013_contract(campaign):
    current = (
        ROOT / ".github/workflows" / ("hoben-" + campaign.value + "-manual.yml")
    ).read_bytes()
    refused(semantics.validate_shell(campaign, current))


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        {},
        [],
        "SYNTHETIC_PRIVATE_INPUT",
        bytearray(b"name: test"),
        memoryview(b"name: test"),
    ],
)
def test_only_immutable_bytes_are_accepted(bad):
    refused(
        semantics.validate_shell(semantics.Campaign.PROTOCOL, bad),
        semantics.Error.BYTES,
    )


@pytest.mark.parametrize("campaign", CAMPAIGNS)
def test_size_boundary_and_encoding_are_bounded_before_parsing(campaign):
    data = source(campaign)
    exact = data + b"#" + b"x" * (semantics.MAX_YAML_BYTES - len(data) - 2) + b"\n"
    assert len(exact) == semantics.MAX_YAML_BYTES
    assert semantics.validate_shell(campaign, exact).error is None
    refused(semantics.validate_shell(campaign, exact + b"x"), semantics.Error.SIZE)
    refused(semantics.validate_shell(campaign, b""), semantics.Error.SIZE)
    refused(semantics.validate_shell(campaign, b"\xff"), semantics.Error.UTF8)
    refused(
        semantics.validate_shell(campaign, b"\xef\xbb\xbf" + data), semantics.Error.UTF8
    )


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize(
    "trigger",
    [
        "push",
        "pull_request",
        "schedule",
        "workflow_call",
        "issue_comment",
        "workflow_run",
    ],
)
def test_extra_automatic_or_reusable_trigger_refuses(campaign, trigger):
    doc = document(campaign)
    doc["on"][trigger] = {}
    refused(semantics.validate_shell(campaign, encode(doc)), semantics.Error.TRIGGER)


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "extra",
        "reversed",
        "no_all",
        "other_campaign",
        "default",
        "type",
        "required_int",
        "required_string",
        "extra_input",
    ],
)
def test_choices_exactly_match_plan_and_current_default(campaign, case):
    doc = document(campaign)
    inputs = doc["on"]["workflow_dispatch"]["inputs"]
    choice = inputs["scenario"]
    options = choice["options"]
    if case == "missing":
        options.pop(0)
    elif case == "duplicate":
        options.append(options[0])
    elif case == "extra":
        options.append("SYNTHETIC_PRIVATE_INPUT")
    elif case == "reversed":
        options.reverse()
    elif case == "no_all":
        options.remove("all")
    elif case == "other_campaign":
        choice["options"] = list(
            HA_CHOICES if campaign is semantics.Campaign.PROTOCOL else PROTOCOL_CHOICES
        )
    elif case == "default":
        choice["default"] = "all"
    elif case == "type":
        choice["type"] = "string"
    elif case == "required_int":
        choice["required"] = 1
    elif case == "required_string":
        choice["required"] = "true"
    else:
        inputs["ref"] = {"type": "string"}
    refused(semantics.validate_shell(campaign, encode(doc)), semantics.Error.SCENARIOS)


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize("level", ["workflow", "job"])
@pytest.mark.parametrize(
    "bad", [{"contents": "read"}, {"contents": "write"}, "read-all", [], None]
)
def test_permissions_cannot_be_added_or_approximated(campaign, level, bad):
    doc = document(campaign)
    target = doc if level == "workflow" else doc["jobs"]["not-activated"]
    target["permissions"] = bad
    refused(semantics.validate_shell(campaign, encode(doc)))


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize("level", ["workflow", "job", "step"])
@pytest.mark.parametrize(
    "key,value",
    [
        ("environment", "hoben-live"),
        ("env", {"TOKEN": "SYNTHETIC_PRIVATE_INPUT"}),
        ("secrets", "inherit"),
        ("if", "always()"),
        ("uses", "actions/checkout@v7"),
        ("continue-on-error", True),
        ("defaults", {"run": {"shell": "bash"}}),
    ],
)
def test_unknown_keys_environments_secrets_actions_conditions_and_bypasses_refuse(
    campaign, level, key, value
):
    doc = document(campaign)
    job = doc["jobs"]["not-activated"]
    target = doc if level == "workflow" else job if level == "job" else job["steps"][0]
    target[key] = value
    refused(semantics.validate_shell(campaign, encode(doc)))


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize(
    "case",
    [
        "extra_job",
        "renamed_job",
        "extra_step",
        "runner",
        "timeout",
        "bool_timeout",
        "quoted_timeout",
        "shell",
        "reusable",
    ],
)
def test_single_fixed_bounded_job_and_one_bash_step_only(campaign, case):
    doc = document(campaign)
    job = doc["jobs"]["not-activated"]
    if case == "extra_job":
        doc["jobs"]["other"] = copy.deepcopy(job)
    elif case == "renamed_job":
        doc["jobs"] = {"other": job}
    elif case == "extra_step":
        job["steps"].append(copy.deepcopy(job["steps"][0]))
    elif case == "runner":
        job["runs-on"] = "self-hosted"
    elif case == "timeout":
        job["timeout-minutes"] = 2
    elif case == "bool_timeout":
        job["timeout-minutes"] = True
    elif case == "quoted_timeout":
        job["timeout-minutes"] = "1"
    elif case == "shell":
        job["steps"][0]["shell"] = "python"
    else:
        doc["jobs"] = {
            "not-activated": {"uses": "./.github/workflows/hoben-manual.yml"}
        }
    refused(semantics.validate_shell(campaign, encode(doc)))


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize(
    "attack",
    [
        "echo SYNTHETIC_PRIVATE_INPUT\nexit 1\n",
        "curl https://private.invalid\nexit 1\n",
        "python collector.py\nexit 1\n",
        "exit 1\necho SYNTHETIC_PRIVATE_INPUT\n",
        "$(touch SYNTHETIC_PRIVATE_INPUT)\nexit 1\n",
        "`touch SYNTHETIC_PRIVATE_INPUT`\nexit 1\n",
        "exit 0\n",
    ],
)
def test_exit_one_alone_never_approves_arbitrary_scripts(campaign, attack):
    doc = document(campaign)
    doc["jobs"]["not-activated"]["steps"][0]["run"] = attack
    refused(semantics.validate_shell(campaign, encode(doc)), semantics.Error.SCRIPT)


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize(
    "case",
    [
        "append",
        "prepend",
        "replace_printf",
        "redirect",
        "semicolon",
        "summary_substitution",
        "remove_line",
        "reorder",
        "exit",
        "different_literal",
    ],
)
def test_entire_approved_refusal_sequence_is_checked(campaign, case):
    doc = document(campaign)
    step = doc["jobs"]["not-activated"]["steps"][0]
    script = step["run"]
    if case == "append":
        script += "echo SYNTHETIC_PRIVATE_INPUT\n"
    elif case == "prepend":
        script = "echo SYNTHETIC_PRIVATE_INPUT\n" + script
    elif case == "replace_printf":
        script = script.replace("printf", "eval", 1)
    elif case == "redirect":
        script = script.replace("$GITHUB_STEP_SUMMARY", "/tmp/SYNTHETIC_PRIVATE_INPUT")
    elif case == "semicolon":
        script = script.replace("exit 1", "exit 1; touch SYNTHETIC_PRIVATE_INPUT")
    elif case == "summary_substitution":
        script = script.replace(
            "$GITHUB_STEP_SUMMARY", "$(touch SYNTHETIC_PRIVATE_INPUT)"
        )
    elif case == "remove_line":
        script = "\n".join(script.splitlines()[1:]) + "\n"
    elif case == "reorder":
        lines = script.splitlines()
        lines[0], lines[1] = lines[1], lines[0]
        script = "\n".join(lines) + "\n"
    elif case == "exit":
        script = script.replace("exit 1", "exit 0")
    else:
        script = script.replace("NOT RUN", "SUCCESS")
    step["run"] = script
    refused(semantics.validate_shell(campaign, encode(doc)), semantics.Error.SCRIPT)


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize(
    "fragment", [b"permissions: {}\n", b"'on': {}\n", b"name: other\n"]
)
def test_duplicate_root_keys_are_never_silently_overwritten(campaign, fragment):
    refused(
        semantics.validate_shell(campaign, source(campaign) + fragment),
        semantics.Error.DUPLICATE,
    )


@pytest.mark.parametrize("campaign", CAMPAIGNS)
def test_duplicate_nested_mapping_keys_refuse(campaign):
    data = source(campaign).replace(
        b"    timeout-minutes: 1\n", b"    timeout-minutes: 1\n    timeout-minutes: 1\n"
    )
    refused(semantics.validate_shell(campaign, data), semantics.Error.DUPLICATE)


@pytest.mark.parametrize(
    "payload",
    [
        b"!!python/object/apply:os.system ['touch SYNTHETIC_PRIVATE_INPUT']\n",
        b"!!str SYNTHETIC_PRIVATE_INPUT\n",
        b"value: &private []\n",
        b"value: *private\n",
        b"value: &private {nested: *private}\n",
        b"%YAML 1.1\n---\nvalue: test\n",
        b"%TAG !e! tag:example.com,2026:\n---\nvalue: test\n",
    ],
)
def test_tags_anchors_aliases_directives_never_construct_or_execute(
    payload, monkeypatch
):
    def denied(*args, **kwargs):
        raise AssertionError("Execution/I/O forbidden")

    monkeypatch.setattr(os, "system", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(builtins, "open", denied)
    refused(
        semantics.validate_shell(semantics.Campaign.PROTOCOL, payload),
        semantics.Error.FEATURE,
    )


@pytest.mark.parametrize(
    "data",
    [
        b"[unterminated",
        b"a: [}\n",
        b"a: \x00\n",
        b"a:\n b: 1\n  c: 2\n",
        b"---\na: 1\n---\nb: 2\n",
        b"a: 1\na: 2\n",
    ],
)
def test_malformed_multiple_documents_and_duplicates_fail_closed(data, capsys):
    refused(semantics.validate_shell(semantics.Campaign.PROTOCOL, data))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("campaign", CAMPAIGNS)
@pytest.mark.parametrize(
    "old,new",
    [
        (b"'on':", b"on:"),
        (b"required: true", b"required: yes"),
        (b"timeout-minutes: 1", b"timeout-minutes: 01"),
        (b"timeout-minutes: 1", b"timeout-minutes: 0x1"),
    ],
)
def test_cross_yaml_version_scalar_ambiguities_are_conservatively_refused(
    campaign, old, new
):
    refused(
        semantics.validate_shell(campaign, source(campaign).replace(old, new)),
        semantics.Error.SCALAR,
    )


@pytest.mark.parametrize("campaign", CAMPAIGNS)
def test_actions_expressions_are_refused_even_in_comments(campaign):
    refused(
        semantics.validate_shell(
            campaign, source(campaign) + b"# ${{ secrets.PRIVATE }}\n"
        ),
        semantics.Error.SUBSTITUTION,
    )


def test_parser_depth_node_and_token_limits():
    campaign = semantics.Campaign.PROTOCOL
    refused(
        semantics.validate_shell(campaign, ("[" * 20 + "value" + "]" * 20).encode()),
        semantics.Error.COMPLEXITY,
    )
    # This stays below the token ceiling but exceeds the node ceiling.
    nodes = ("[" + ",".join("a" for _ in range(150)) + "]").encode()
    refused(semantics.validate_shell(campaign, nodes), semantics.Error.COMPLEXITY)
    tokens = ("[" + ",".join("a" for _ in range(300)) + "]").encode()
    refused(semantics.validate_shell(campaign, tokens), semantics.Error.COMPLEXITY)


def test_global_safe_loader_is_not_modified_and_output_is_immutable():
    assert yaml.safe_load("key: yes") == {"key": True}
    result = semantics.validate_shell(
        semantics.Campaign.HA, source(semantics.Campaign.HA)
    )
    assert result.error is None
    assert yaml.safe_load("key: yes") == {"key": True}
    with pytest.raises(FrozenInstanceError):
        result.can_start = True
    with pytest.raises(FrozenInstanceError):
        result.facts[0].state = semantics.State.UNKNOWN
    with pytest.raises(TypeError):
        semantics.Observation(result.facts, None, can_start=True)
    assert {f.name for f in fields(result)} == {
        "facts",
        "error",
        "_binding",
        "can_start",
        "execution",
        "actions_result",
    }


def test_validator_has_no_io_or_runtime_consumer_and_cli_refuses():
    path = ROOT / "scripts/campaign_shell_semantics.py"
    parsed = ast.parse(path.read_text())
    imports = {
        n.module if isinstance(n, ast.ImportFrom) else alias.name
        for n in ast.walk(parsed)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for alias in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert imports == {"hashlib", "re", "dataclasses", "enum", "types", "yaml"}
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
            "campaign_shell_semantics" in p.read_text()
            for p in (ROOT / folder).rglob("*")
            if p != path and p.is_file() and p.suffix in {".py", ".cjs", ".yml"}
        )
    result = subprocess.run(
        [sys.executable, "-I", str(path)], env={}, capture_output=True, timeout=5
    )
    assert result.returncode == 1 and result.stdout == result.stderr == b""
