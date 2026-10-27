"""Historical 013 shell fixtures: closed YAML and local inert refusal steps."""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {
    "hoben-protocol-manual.yml": (
        "tls-only",
        "session-open",
        "read-v4-state",
        "h1h2",
        "session-300",
        "session-reconnect",
        "all",
    ),
    "hoben-ha-manual.yml": (
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


def workflow(name):
    return yaml.load(
        (ROOT / "tests/fixtures/campaign_shells_013" / name).read_text(),
        Loader=yaml.BaseLoader,
    )


@pytest.mark.parametrize("name", SCENARIOS)
def test_shells_have_only_manual_closed_choices_and_no_execution_capability(name):
    w = workflow(name)
    assert set(w) == {"name", "on", "permissions", "jobs"}
    assert "non activ" in w["name"]
    assert set(w["on"]) == {"workflow_dispatch"}
    assert set(w["on"]["workflow_dispatch"]) == {"inputs"}
    inputs = w["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"scenario"}
    choice = inputs["scenario"]
    assert set(choice) == {"description", "required", "type", "default", "options"}
    assert choice["required"] == "true" and choice["type"] == "choice"
    assert choice["options"] == list(SCENARIOS[name])
    assert choice["default"] in choice["options"]
    assert w["permissions"] == {}
    assert w["jobs"]
    for job in w["jobs"].values():
        # No reusable workflow, environment, credentials, condition or bypass.
        assert set(job) == {"runs-on", "timeout-minutes", "permissions", "steps"}
        assert job["runs-on"] == "ubuntu-latest" and job["permissions"] == {}
        assert 0 < int(job["timeout-minutes"]) <= 1
        assert len(job["steps"]) == 1
        step = job["steps"][0]
        assert set(step) == {"name", "shell", "run"}
        assert step["shell"] == "bash"
        lines = step["run"].splitlines()
        assert lines[-1] == "exit 1" and 2 <= len(lines) <= 10
        # Positive command allowlist: quoted static printf literals and exit 1.
        # No checkout/action, program, substitution, network or collector can
        # hide behind a denylist of known executable/secret names.
        for line in lines[:-1]:
            assert re.fullmatch(
                r"printf '%s\\n' '[^'\n]*'(?: >> \"\$GITHUB_STEP_SUMMARY\")?",
                line,
            )
        assert "${{" not in json.dumps(w)


CASES = [
    (name, scenario) for name, options in SCENARIOS.items() for scenario in options
]


@pytest.mark.parametrize("name,scenario", CASES)
@pytest.mark.parametrize("ref", ["refs/heads/experimental", "refs/heads/main"])
def test_every_choice_including_all_refuses_without_a_dispatch(
    tmp_path, name, scenario, ref
):
    step = next(iter(workflow(name)["jobs"].values()))["steps"][0]
    event, summary = tmp_path / "event.json", tmp_path / "summary with spaces.md"
    event.write_text(json.dumps({"inputs": {"scenario": scenario}}))
    # Execute only the literal shell step, never GitHub Actions or a collector.
    # No inherited credentials, profiles, checkout or runtime tools are needed.
    result = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            step["run"],
        ],
        env={
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": ref,
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 1 and result.stderr == ""
    assert result.stdout.startswith("::error::NOT RUN:")
    assert "SUCCESS" not in result.stdout
    text = summary.read_text()
    assert "NOT RUN" in text and "non activée" in text
    assert "all" in text and "Résultat global : FAILURE" in text
    assert "SUCCESS" not in text
    assert {p.name for p in tmp_path.iterdir()} == {event.name, summary.name}


def test_shells_have_distinct_readable_names():
    names = [workflow(name)["name"] for name in SCENARIOS]
    assert len(set(names)) == len(names)
