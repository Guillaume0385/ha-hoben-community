"""Closed pre-worker diagnostics and publication, synthetic identity only."""

import errno
import json
import os
import stat
import subprocess
import sys

import pytest

from scripts import run_campaign as parent
from scripts.campaign_runtime_contract import validate_report
from tests.test_campaign_publication import node
from tests.test_campaign_runtime import PROVENANCE, ROOT, envelope, node_accepts


def source(folder, campaign="protocol", selection="read-v4-state"):
    event = folder / "event.json"
    event.write_text(json.dumps({"inputs": {"scenario": selection}}))
    return {
        "PATH": os.environ["PATH"],
        "RUNNER_TEMP": str(folder),
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": "Guillaume0385/ha-hoben-community",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_REF": PROVENANCE["ref"],
        "GITHUB_SHA": PROVENANCE["sha"],
        "GITHUB_RUN_ID": str(PROVENANCE["run_id"]),
        "GITHUB_RUN_ATTEMPT": str(PROVENANCE["run_attempt"]),
        "HOBEN_USER_GUID": "a" * 32,
    }


@pytest.fixture
def entry(tmp_path, monkeypatch):
    env = source(tmp_path)
    monkeypatch.setattr(os, "environ", env)
    monkeypatch.setattr(sys, "argv", ["run_campaign.py", "protocol"])
    monkeypatch.setattr(parent.signal, "signal", lambda *_: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("PRIVATE_PAYLOAD must not reach a collector")

    monkeypatch.setattr(parent, "run", forbidden)
    return env


def report(folder):
    file = folder / "hoben-campaign-public/report.json"
    value = validate_report(json.loads(file.read_text()))
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert stat.S_IMODE(file.parent.stat().st_mode) == 0o700
    assert node_accepts(value)
    assert "PRIVATE_PAYLOAD" not in file.read_text()
    return value


@pytest.mark.parametrize(
    "field,value",
    [
        ("HOBEN_USER_GUID", ""),
        ("HOBEN_USER_GUID", "PRIVATE_PAYLOAD"),
        ("HOBEN_USER_GUID", "a" * 31),
        ("HOBEN_USER_GUID", "é" * 32),
    ],
    ids=[
        "empty-user",
        "invalid-user",
        "short-user",
        "non-ascii-user",
    ],
)
def test_identity_failure_is_closed_and_has_a_not_run_report(
    field, value, entry, tmp_path, capfd
):
    entry[field] = value
    assert parent.main() == 1
    captured = capfd.readouterr()
    assert captured.out == "" and captured.err == "::error::identity_refused\n"
    r = report(tmp_path)
    assert r["stages"][0]["status"] == "NOT RUN"
    assert r["stages"][0]["reason"] == "identity_refused"
    assert not r["stages"][0]["started"]
    assert r["collection_result"] == "failure" and r["actions_result"] == "FAILURE"


@pytest.mark.parametrize("campaign", ["protocol", "ha"])
def test_refusal_report_survives_both_validators_and_fresh_runner_publication(
    campaign, entry, tmp_path, monkeypatch, capfd
):
    entry.update(source(tmp_path, campaign, "all"))
    entry.pop("HOBEN_USER_GUID")
    if campaign == "ha":
        (tmp_path / "hoben-ha-runtime.id").write_text("sha256:" + "a" * 64)
    monkeypatch.setattr(sys, "argv", ["run_campaign.py", campaign])
    assert parent.main() == 1
    assert capfd.readouterr().err == "::error::identity_refused\n"
    r = report(tmp_path)
    assert all(s["status"] == "NOT RUN" and not s["started"] for s in r["stages"])
    assert all(s["reason"] == "previous_failure" for s in r["stages"][1:])
    assert node("prepare", tmp_path, campaign, "all").returncode == 0
    encoded = (tmp_path / "output").read_text().removeprefix("report_b64=").strip()
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    result = node(
        "publish", publisher, campaign, "all", encoded=encoded, collect="failure"
    )
    assert result.returncode == 1
    public = validate_report(
        json.loads((publisher / "hoben-campaign-published/report.json").read_text())
    )
    assert public == r
    summary = (publisher / "summary").read_text()
    assert "identity_refused" in summary and "Résultat global : **FAILURE**" in summary
    assert "PRIVATE_PAYLOAD" not in summary + result.stdout + result.stderr


@pytest.mark.parametrize(
    "fault",
    ["actor", "event", "ref", "provenance", "selection", "json", "symlink", "argv"],
)
def test_unverified_context_has_only_a_closed_diagnostic(
    fault, entry, tmp_path, monkeypatch, capfd
):
    if fault in {"actor", "event", "ref", "provenance"}:
        field = {
            "actor": "GITHUB_ACTOR",
            "event": "GITHUB_EVENT_NAME",
            "ref": "GITHUB_REF",
            "provenance": "GITHUB_RUN_ID",
        }[fault]
        entry[field] = "PRIVATE_PAYLOAD"
    elif fault == "selection":
        (tmp_path / "event.json").write_text(
            '{"inputs":{"scenario":"PRIVATE_PAYLOAD"}}'
        )
    elif fault == "json":
        (tmp_path / "event.json").write_text("PRIVATE_PAYLOAD")
    elif fault == "symlink":
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "event.json")
        entry["GITHUB_EVENT_PATH"] = str(link)
    else:
        monkeypatch.setattr(sys, "argv", ["run_campaign.py"])
    assert parent.main() == 1
    captured = capfd.readouterr()
    assert captured.out == "" and captured.err == "::error::context_refused\n"
    assert not (tmp_path / "hoben-campaign-public").exists()


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "missing-temp"])
def test_unsafe_report_storage_is_never_reused_or_overwritten(
    kind, entry, tmp_path, capfd
):
    target = tmp_path / "hoben-campaign-public"
    if kind == "file":
        target.write_text("PRIVATE_PAYLOAD")
    elif kind in {"directory", "symlink"}:
        folder = target if kind == "directory" else tmp_path / "outside"
        folder.mkdir()
        (folder / "report.json").write_text("PRIVATE_PAYLOAD")
        if kind == "symlink":
            target.symlink_to(folder, target_is_directory=True)
    else:
        entry.pop("RUNNER_TEMP")
    assert parent.main() == 1
    assert capfd.readouterr().err == "::error::report_refused\n"
    if kind == "file":
        assert target.read_text() == "PRIVATE_PAYLOAD"
    elif kind != "missing-temp":
        assert (target / "report.json").read_text() == "PRIVATE_PAYLOAD"


def test_worker_preparation_failure_is_not_an_identity_diagnosis(
    entry, tmp_path, monkeypatch, capfd
):
    entry.update(source(tmp_path, "ha", "hoben-live"))
    monkeypatch.setattr(sys, "argv", ["run_campaign.py", "ha"])
    assert parent.main() == 1  # no image receipt exists; no Docker/HA is invoked
    assert capfd.readouterr().err == "::error::worker_failure\n"
    assert report(tmp_path)["stages"][0]["reason"] == "worker_failure"


@pytest.mark.parametrize(
    "user",
    ["B" * 32, "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"],
    ids=["compact", "canonical"],
)
@pytest.mark.parametrize("campaign", ["protocol", "ha"])
def test_user_identity_alone_reaches_collection_without_public_identity(
    user, campaign, entry, tmp_path, monkeypatch, capfd
):
    selection = "session-open" if campaign == "protocol" else "open-errors"
    entry.update(source(tmp_path, campaign, selection))
    entry["HOBEN_USER_GUID"] = user
    monkeypatch.setattr(sys, "argv", ["run_campaign.py", campaign])
    if campaign == "ha":
        (tmp_path / "hoben-ha-runtime.id").write_text("sha256:" + "a" * 64)
    seen = []

    def collect(campaign, selection, provenance, payload, **kwargs):
        seen.append(json.loads(payload))
        r = envelope(campaign, selection)
        r.update(collection_result="pending", actions_result="FAILURE")
        return r

    monkeypatch.setattr(parent, "run", collect)
    assert parent.main() == 0
    assert seen == [{"user_guid": "b" * 32, "device_guid": "0" * 32}]
    assert capfd.readouterr() == ("", "")
    r = report(tmp_path)
    assert r["stages"][0]["status"] == "SUCCESS"
    assert "b" * 32 not in json.dumps(r) and "0" * 32 not in json.dumps(r)


def test_unexpected_error_after_entering_collection_cannot_invent_a_preflight_report(
    entry, tmp_path, capfd
):
    assert parent.main() == 1  # fixture's collector raises a private exception
    captured = capfd.readouterr()
    assert captured.out == "" and captured.err == "::error::worker_failure\n"
    assert not (tmp_path / "hoben-campaign-public/report.json").exists()


def test_tls_only_still_requires_no_identity(entry, tmp_path, monkeypatch, capfd):
    entry.update(source(tmp_path, selection="tls-only"))
    entry.pop("HOBEN_USER_GUID")

    def collect(campaign, selection, provenance, payload, **kwargs):
        assert json.loads(payload) == {"user_guid": "", "device_guid": ""}
        r = envelope(campaign, selection)
        r.update(collection_result="pending", actions_result="FAILURE")
        return r

    monkeypatch.setattr(parent, "run", collect)
    assert parent.main() == 0 and capfd.readouterr() == ("", "")
    assert report(tmp_path)["stages"][0]["status"] == "SUCCESS"


def test_failed_refusal_report_write_has_only_two_fixed_diagnostics(
    entry, tmp_path, monkeypatch, capfd
):
    entry["HOBEN_USER_GUID"] = "PRIVATE_PAYLOAD"

    def denied(*args):
        raise OSError("PRIVATE_PAYLOAD")

    monkeypatch.setattr(parent, "write_report", denied)
    assert parent.main() == 1
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "::error::identity_refused\n::error::report_refused\n"
    assert not (tmp_path / "hoben-campaign-public/report.json").exists()


def test_invalid_collected_report_is_never_replaced_by_a_not_run_receipt(
    entry, tmp_path, monkeypatch, capfd
):
    def invalid(*args, **kwargs):
        return {**envelope("protocol", "read-v4-state"), "private": "PRIVATE_PAYLOAD"}

    monkeypatch.setattr(parent, "run", invalid)
    assert parent.main() == 1
    assert capfd.readouterr() == ("", "::error::report_refused\n")
    assert not (tmp_path / "hoben-campaign-public/report.json").exists()


def test_diagnostic_channel_rejects_unknown_or_private_text(capfd):
    with pytest.raises(ValueError):
        parent.diagnostic("PRIVATE_PAYLOAD")
    assert capfd.readouterr() == ("", "")


def test_real_cli_exit_is_closed_without_any_subprocess_or_socket(tmp_path):
    env = source(tmp_path)
    env["HOBEN_USER_GUID"] = "PRIVATE_PAYLOAD"
    code = """
import runpy,socket,subprocess,sys
def denied(*a,**k):raise AssertionError('PRIVATE_PAYLOAD')
socket.create_connection=socket.getaddrinfo=denied
socket.socket.connect=socket.socket.connect_ex=denied
subprocess.Popen=denied
sys.argv=['scripts/run_campaign.py','protocol']
runpy.run_path('scripts/run_campaign.py',run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr == "::error::identity_refused\n"
    assert report(tmp_path)["stages"][0]["reason"] == "identity_refused"


@pytest.mark.parametrize("fail_at", [2, 3, 4])
def test_partial_pipe_allocation_closes_every_owned_descriptor(fail_at, monkeypatch):
    allocated = []
    real_pipe = os.pipe

    def pipe():
        if len(allocated) == (fail_at - 1) * 2:
            raise OSError("PRIVATE_PAYLOAD")
        pair = real_pipe()
        allocated.extend(pair)
        return pair

    monkeypatch.setattr(os, "pipe", pipe)
    try:
        value = parent.execute("protocol", "tls-only", b"{}", 5, clock=lambda: 0)
        assert value["status"] == "NOT RUN" and value["reason"] == "worker_failure"
        for fd in allocated:
            with pytest.raises(OSError) as error:
                os.fstat(fd)
            assert error.value.errno == errno.EBADF
    finally:
        for fd in allocated:
            try:
                os.close(fd)
            except OSError:
                pass
