"""Actual isolated CLI/launcher and simulated phase failures, never Hoben I/O."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.hoben.transport import TransportError
from scripts import boundary_capture
from scripts import launch_experimental_boundary as launcher
from scripts import run_experimental_boundary as entry
from tests.test_boundary_observations import VirtualStream
from tests.test_experimental_boundary_capture import runner as runner
from tests.test_post_open_handoff import FIELDS, OPENED_PREFIX

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "SYNTHETIC-PRIVATE-EXCEPTION-IDENTITY-RX"


@pytest.fixture
def checkouts(tmp_path):
    """Two local committed checkouts matching the workflow layout and push event."""
    candidate, trusted, storage = [
        tmp_path / n for n in ("candidate", "trusted", "temp")
    ]
    candidate.mkdir()
    storage.mkdir()
    for directory in ("scripts", "custom_components"):
        shutil.copytree(
            ROOT / directory,
            candidate / directory,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    config = candidate / ".github/config"
    config.mkdir(parents=True)
    shutil.copy(ROOT / ".github/config/hoben-experimental.json", config)
    git_env = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    for command in (
        ["init", "--initial-branch=experimental"],
        ["add", "."],
        [
            "-c",
            "user.name=Offline test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Synthetic offline checkout",
        ],
    ):
        subprocess.run(
            ["/usr/bin/git", *command],
            cwd=candidate,
            env=git_env,
            capture_output=True,
            check=True,
            timeout=10,
        )
    sha = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=candidate,
        env=git_env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    shutil.copytree(candidate, trusted)
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "ref": "refs/heads/experimental",
                "before": "f" * 40,
                "after": sha,
                "created": False,
                "deleted": False,
                "forced": False,
                "sender": {"login": "Guillaume0385", "id": 18246624, "type": "User"},
                "repository": {"full_name": entry.REPOSITORY, "id": 1401398724},
            }
        )
    )
    environment = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": entry.REPOSITORY,
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": entry.WORKFLOW,
        "GITHUB_SHA": sha,
        "GITHUB_WORKFLOW_SHA": sha,
        "GITHUB_RUN_ID": "123",
        "GITHUB_EVENT_PATH": str(event),
        "EXPERIMENTAL_APPROVED_SHA": sha,
        "RUNNER_TEMP": str(storage),
        "EXPERIMENTAL_PHASE": "dry-run",
    }
    return SimpleNamespace(
        candidate=candidate,
        trusted=trusted,
        storage=storage,
        environment=environment,
    )


def test_real_isolated_dry_run_loads_without_a_repository_pythonpath(checkouts):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(checkouts.candidate / "scripts/run_experimental_boundary.py"),
            "dry-run",
        ],
        env=checkouts.environment,
        cwd=checkouts.candidate,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == b""
    report = json.loads(
        (checkouts.storage / "hoben-experimental-exports/report.json").read_text()
    )
    assert report["result"] == "dry_run_pass" and report["executed_sessions"] == 0
    assert not list(checkouts.storage.glob("hoben-experimental-private-*"))


@pytest.mark.parametrize("invalid_context", [False, True])
def test_real_launcher_reports_child_refusal_before_any_network(
    checkouts, monkeypatch, capsys, invalid_context
):
    # No Hoben identity is supplied: even with valid synthetic push metadata,
    # the real child must refuse identity before constructing a campaign.
    if invalid_context:
        checkouts.environment["GITHUB_ACTOR"] = PRIVATE
    monkeypatch.setattr(launcher, "ROOT", checkouts.trusted)
    monkeypatch.setattr(launcher.os, "environ", checkouts.environment)
    assert launcher.main() == 1
    phase = "context" if invalid_context else "identity"
    assert capsys.readouterr() == (
        f"H1/H2 failed; phase={phase}; phase_source=child_exit.\n",
        "",
    )
    assert not list(checkouts.storage.glob("hoben-experimental-private-*"))
    assert not list(checkouts.storage.rglob("report.json"))


def test_real_isolated_invalid_argument_cannot_echo_private_text(checkouts):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(checkouts.candidate / "scripts/run_experimental_boundary.py"),
            PRIVATE,
        ],
        env={},
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 10
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize(
    "code,phase",
    [
        (10, "context"),
        (11, "identity"),
        (12, "dns_tls"),
        (13, "open"),
        (14, "collect"),
        (15, "projection"),
        (16, "cleanup"),
        (1, None),
        (-9, None),
        (999, None),
        ("timeout", None),
    ],
)
def test_parent_accepts_only_fixed_exit_phases_and_discards_private_outputs(
    monkeypatch, capsys, code, phase
):
    def run(command, **kwargs):
        assert command[1] == "-I" and command[-1] == "live"
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["stdin"] == subprocess.DEVNULL
        if code == "timeout":
            raise subprocess.TimeoutExpired(
                PRIVATE, 1800, output=PRIVATE, stderr=PRIVATE
            )
        return subprocess.CompletedProcess(command, code, PRIVATE, PRIVATE)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    assert launcher.main() == 1
    source = "child_exit" if phase is not None else "unavailable"
    assert capsys.readouterr() == (
        f"H1/H2 failed; phase={phase or 'context'}; phase_source={source}.\n",
        "",
    )


def test_parent_cleanup_failure_refuses_even_after_child_success(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "hoben-experimental-private-test").mkdir(mode=0o700)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)
    )

    def refused(path):
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(launcher.shutil, "rmtree", refused)
    assert launcher.main() == 1
    assert capsys.readouterr() == (
        "H1/H2 failed; phase=cleanup; phase_source=parent.\n",
        "",
    )


@pytest.mark.parametrize(
    "phase",
    [
        "dns_tls",
        "open",
        "opening_rejected",
        "opening_timeout",
        "collect",
        "projection",
        "cleanup",
    ],
)
def test_actual_collector_preserves_phase_through_projection_and_cleanup(
    runner, monkeypatch, capsys, phase
):
    monkeypatch.setenv("EXPERIMENTAL_PHASE", "live")
    monkeypatch.setenv("HOBEN_USER_GUID", FIELDS["user_guid"])
    monkeypatch.setenv("HOBEN_DEVICE_GUID", "0" * 32)
    original_import = entry.importlib.import_module
    probe = original_import("scripts.probe_opened_client_boundary")
    worlds = []

    async def refused(*args):
        raise TransportError(PRIVATE)

    def bad_projection(*args, **kwargs):
        raise RuntimeError(PRIVATE)

    async def session(capture, **kwargs):
        script = (
            [(0.01, OPENED_PREFIX), (1, RuntimeError(PRIVATE))]
            if phase == "collect"
            else [(0.01, b"\x05\x04")]
            if phase == "opening_rejected"
            else []
            if phase == "opening_timeout"
            else [(0.01, OPENED_PREFIX)]
        )
        world = VirtualStream(script, replies=False)
        worlds.append(world)
        if phase == "dns_tls":
            world.connect = refused
        elif phase == "open":
            world.write = refused
        elif phase == "cleanup":
            world.close = refused
        return await boundary_capture.collect_session(
            capture,
            **kwargs,
            transport_factory=world.factory,
            clock=world.clock,
            sleep=world.sleep,
            waiter=world.wait,
        )

    async def campaign(private, **kwargs):
        async def no_spacing(seconds):
            pass

        return await boundary_capture.run_campaign(
            private,
            **kwargs,
            session_runner=session,
            sleep=no_spacing,
        )

    monkeypatch.setattr(probe, "campaign_with_signals", campaign)
    if phase == "projection":
        monkeypatch.setattr(boundary_capture, "analyze_capture", bad_projection)
    assert (
        entry.main(["live"])
        == {
            "dns_tls": 12,
            "open": 13,
            "opening_rejected": 13,
            "opening_timeout": 13,
            "collect": 14,
            "projection": 15,
            "cleanup": 16,
        }[phase]
    )
    assert worlds and all(w.connects <= 1 and w.maximum_readers <= 1 for w in worlds)
    assert not list(runner.storage.glob("hoben-experimental-private-*"))
    assert capsys.readouterr() == ("", "")
    for public in runner.exports.glob("*"):
        assert public.name == "report.json" and PRIVATE not in public.read_text()
