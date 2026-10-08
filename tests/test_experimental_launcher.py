"""Verify the real main launcher removes every inherited runner credential."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import launch_experimental_boundary as launcher

MAIN, SHA = "a" * 40, "b" * 40


@pytest.fixture
def launch_context(tmp_path, monkeypatch):
    trusted, candidate = tmp_path / "trusted", tmp_path / "candidate"
    trusted.mkdir()
    (candidate / "scripts").mkdir(parents=True)
    entry = candidate / "scripts/run_experimental_boundary.py"
    entry.write_text("# reviewed synthetic entry\n")
    monkeypatch.setattr(launcher, "ROOT", trusted)
    monkeypatch.setattr(
        launcher, "checkout_sha", lambda p: MAIN if p == trusted else SHA
    )
    variables = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": launcher.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "issues",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": launcher.WORKFLOW,
        "GITHUB_WORKFLOW_SHA": MAIN,
        "GITHUB_SHA": MAIN,
        "GITHUB_RUN_ID": "123",
        "GITHUB_EVENT_PATH": str(tmp_path / "event.json"),
        "RUNNER_TEMP": str(tmp_path),
        "EXPERIMENTAL_APPROVED_SHA": SHA,
        "EXPERIMENTAL_PHASE": "live",
        "HOBEN_USER_GUID": "SYNTHETIC_IDENTITY",
        "HOBEN_DEVICE_GUID": "0" * 32,
        "GITHUB_TOKEN": "SYNTHETIC_WRITE_TOKEN",
        "GH_TOKEN": "SYNTHETIC_WRITE_TOKEN",
        "ACTIONS_RUNTIME_TOKEN": "SYNTHETIC_ARTIFACT_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "SYNTHETIC_OIDC_TOKEN",
        "ACTIONS_RESULTS_URL": "https://synthetic.invalid",
        "PYTHONPATH": "/tmp/forged-code",
        "ARBITRARY_VALUE": "PRIVATE",
        "RUNNER_DEBUG": "1",
    }
    for k, v in variables.items():
        monkeypatch.setenv(k, v)
    calls = []
    monkeypatch.setattr(launcher.os, "execve", lambda *args: calls.append(args))
    return SimpleNamespace(
        trusted=trusted, candidate=candidate, entry=entry, calls=calls
    )


def test_launch_replaces_process_with_reviewed_entry_and_an_environment_allowlist(
    launch_context,
):
    launcher.launch()
    executable, arguments, variables = launch_context.calls[0]
    assert arguments == [executable, "-I", str(launch_context.entry), "live"]
    assert variables["HOBEN_USER_GUID"] == "SYNTHETIC_IDENTITY"
    assert variables["EXPERIMENTAL_APPROVED_SHA"] == SHA
    assert set(variables) == set(launcher.CONTEXT) | {
        "PATH",
        "HOBEN_USER_GUID",
        "HOBEN_DEVICE_GUID",
    }
    assert variables["PATH"] == "/usr/bin:/bin"
    assert "SYNTHETIC_WRITE_TOKEN" not in variables.values()
    assert "SYNTHETIC_ARTIFACT_TOKEN" not in variables.values()
    assert "SYNTHETIC_IDENTITY" not in arguments


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_REF", "refs/heads/experimental"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_ACTOR", "other"),
        ("GITHUB_TRIGGERING_ACTOR", "other"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_SHA", "short"),
        ("GITHUB_WORKFLOW_SHA", SHA),
        ("GITHUB_WORKFLOW_REF", "candidate.yml"),
        ("EXPERIMENTAL_PHASE", "dry-run"),
        ("EXPERIMENTAL_APPROVED_SHA", MAIN),
    ],
)
def test_changed_context_never_enters_candidate(
    launch_context, monkeypatch, key, value
):
    monkeypatch.setenv(key, value)
    with pytest.raises(
        ValueError, match="Verified experimental prerequisite unavailable"
    ):
        launcher.launch()
    assert not launch_context.calls
    assert os.environ["HOBEN_USER_GUID"] == "SYNTHETIC_IDENTITY"


@pytest.mark.parametrize(
    "change",
    ["main", "candidate", "entry-symlink", "directory-symlink", "missing-entry"],
)
def test_modified_or_redirected_checkout_never_enters_candidate(
    launch_context, monkeypatch, change
):
    if change in {"main", "candidate"}:
        original = launcher.checkout_sha
        directory = (
            launch_context.trusted if change == "main" else launch_context.candidate
        )
        monkeypatch.setattr(
            launcher,
            "checkout_sha",
            lambda p: "c" * 40 if p == directory else original(p),
        )
    elif change == "entry-symlink":
        launch_context.entry.unlink()
        launch_context.entry.symlink_to(Path(__file__))
    elif change == "directory-symlink":
        actual = launch_context.candidate.with_name("redirected")
        launch_context.candidate.rename(actual)
        launch_context.candidate.symlink_to(actual, target_is_directory=True)
    else:
        launch_context.entry.unlink()
    with pytest.raises(
        ValueError, match="Verified experimental prerequisite unavailable"
    ):
        launcher.launch()
    assert not launch_context.calls


def test_checkout_subprocess_cannot_inherit_credentials_or_shell(monkeypatch, tmp_path):
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=(SHA + "\n").encode())

    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setenv("GITHUB_TOKEN", "SYNTHETIC_WRITE_TOKEN")
    assert launcher.checkout_sha(tmp_path) == SHA
    args, kwargs = calls[0]
    assert args == (["/usr/bin/git", "rev-parse", "HEAD"],)
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin"} and "shell" not in kwargs
