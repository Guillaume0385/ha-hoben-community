"""Exercise actual Node projection/publication with bounded synthetic files."""

import base64
import json
import os
import subprocess

import pytest
import yaml

from scripts.campaign_runtime_contract import CHOICES, validate_report
from tests.test_campaign_runtime import ROOT, envelope


def node(mode, folder, campaign, selected, *, encoded="", collect="success"):
    event = folder / "event.json"
    event.write_text(json.dumps({"inputs": {"scenario": selected}}))
    env = {
        "PATH": os.environ["PATH"],
        "CAMPAIGN": campaign,
        "RUNNER_TEMP": str(folder),
        "GITHUB_OUTPUT": str(folder / "output"),
        "GITHUB_STEP_SUMMARY": str(folder / "summary"),
        "GITHUB_EVENT_PATH": str(event),
        "PUBLIC_REPORT_B64": encoded,
        "COLLECT_RESULT": collect,
    }
    result = subprocess.run(
        ["node", ".github/scripts/campaign-report.cjs", mode],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert "PRIVATE_PAYLOAD" not in result.stdout + result.stderr
    return result


@pytest.mark.parametrize(
    "campaign,scenario", [(c, s) for c in CHOICES for s in CHOICES[c]]
)
def test_prepare_and_fresh_runner_publication_have_truthful_per_scenario_results(
    campaign, scenario, tmp_path
):
    collector, publisher = tmp_path / "collector", tmp_path / "publisher"
    folder = collector / "hoben-campaign-public"
    folder.mkdir(parents=True)
    publisher.mkdir()
    report = envelope(campaign, scenario)
    report.update(collection_result="pending", actions_result="FAILURE")
    (folder / "report.json").write_text(json.dumps(report, separators=(",", ":")))
    assert node("prepare", collector, campaign, scenario).returncode == 0
    encoded = (collector / "output").read_text().removeprefix("report_b64=").strip()
    result = node("publish", publisher, campaign, scenario, encoded=encoded)
    public = json.loads(
        (publisher / "hoben-campaign-published/report.json").read_text()
    )
    validate_report(public)
    expected = (
        "FAILURE" if scenario in {"all", "h1h2", "session-reconnect"} else "SUCCESS"
    )
    assert public["actions_result"] == expected and result.returncode == (
        0 if expected == "SUCCESS" else 1
    )
    text = (publisher / "summary").read_text()
    for s in public["stages"]:
        assert "| " + s["scenario"] + " | " + s["status"] + " |" in text


@pytest.mark.parametrize("collect", ["failure", "cancelled", "skipped", "", "unknown"])
def test_collection_job_failure_prevents_green_artifact_even_with_successful_stage(
    collect, tmp_path
):
    report = envelope("protocol", "tls-only")
    encoded = base64.b64encode(
        json.dumps(report, separators=(",", ":")).encode()
    ).decode()
    result = node(
        "publish", tmp_path, "protocol", "tls-only", encoded=encoded, collect=collect
    )
    assert result.returncode == 1
    public = json.loads((tmp_path / "hoben-campaign-published/report.json").read_text())
    assert (
        public["stages"][0]["status"] == "SUCCESS"
        and public["actions_result"] == "FAILURE"
    )
    validate_report(public)


@pytest.mark.parametrize(
    "encoded",
    ["", "PRIVATE_PAYLOAD", "e30=", "a" * 100000],
    ids=["missing", "invalid", "empty-object", "oversized"],
)
def test_absent_invalid_or_oversized_report_is_not_run_without_any_upload(
    encoded, tmp_path
):
    result = node("publish", tmp_path, "ha", "all", encoded=encoded)
    assert (
        result.returncode == 1 and not (tmp_path / "hoben-campaign-published").exists()
    )
    text = (tmp_path / "summary").read_text()
    rows = [line for line in text.splitlines() if line.startswith("| ")][2:]
    assert len(rows) == 7 and all(" | NOT RUN | " in line for line in rows)
    assert "Résultat global : **FAILURE**" in text


@pytest.mark.parametrize("corrupt", ["extra", "symlink", "oversized", "truncated"])
def test_private_or_unsafe_collector_file_never_reaches_actions_output(
    corrupt, tmp_path
):
    folder = tmp_path / "hoben-campaign-public"
    folder.mkdir()
    report = envelope("protocol", "tls-only")
    if corrupt == "extra":
        report["private"] = "PRIVATE_PAYLOAD"
    data = json.dumps(report, separators=(",", ":"))
    if corrupt == "oversized":
        data = "x" * (128 * 1024 + 1)
    if corrupt == "truncated":
        data = data[:-1]
    target = folder / "report.json"
    if corrupt == "symlink":
        source = tmp_path / "private"
        source.write_text(data)
        target.symlink_to(source)
    else:
        target.write_text(data)
    assert node("prepare", tmp_path, "protocol", "tls-only").returncode == 1
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("campaign", CHOICES)
def test_workflow_wiring_preserves_native_environments_mutex_and_no_live_ci(campaign):
    path = (
        ROOT
        / ".github/workflows"
        / (
            "hoben-protocol-manual.yml"
            if campaign == "protocol"
            else "hoben-ha-manual.yml"
        )
    )
    w = yaml.safe_load(path.read_text())
    assert set(w["on"]) == {"workflow_dispatch"}
    assert w["on"]["workflow_dispatch"]["inputs"]["scenario"]["options"] == list(
        CHOICES[campaign]
    )
    assert w["permissions"] == {} and w["concurrency"] == {
        "group": "hoben-read-only-observation",
        "cancel-in-progress": False,
        "queue": "max",
    }
    assert set(w["jobs"]) == {"admission", "collect", "result"}
    admission, collect, result = (
        w["jobs"][k] for k in ("admission", "collect", "result")
    )
    assert admission["permissions"] == {} and "environment" not in admission
    assert collect["environment"] == (
        "hoben-experimental" if campaign == "protocol" else "hoben-live"
    )
    assert (
        "collector_ready == 'true'" in collect["if"] and collect["needs"] == "admission"
    )
    for job in (collect, result):
        assert job["permissions"] == {"contents": "read"}
        checkout = next(s for s in job["steps"] if "checkout@" in s.get("uses", ""))
        assert checkout["with"] == {
            "ref": "${{ github.sha }}",
            "persist-credentials": False,
        }
    assert (
        result["if"] == "always()"
        and result["needs"] == ["admission", "collect"]
        and "environment" not in result
    )
    secret_steps = [s for s in collect["steps"] if "secrets." in json.dumps(s)]
    assert (
        len(secret_steps) == 1
        and secret_steps[0]["run"] == "python -I scripts/run_campaign.py " + campaign
    )
    assert "secrets." not in json.dumps(
        result
    ) and "${{ inputs.scenario }}" not in json.dumps(w)
    artifact = next(
        s for s in result["steps"] if "upload-artifact@" in s.get("uses", "")
    )
    assert artifact["with"]["retention-days"] == 7 and artifact["with"][
        "path"
    ].endswith("hoben-campaign-published/report.json")
    for prohibited in (
        "github_campaign_",
        "manual-hoben-gate",
        "createRef",
        "MANUAL_HOBEN_PR",
    ):
        assert prohibited not in json.dumps(w)
    ordinary = (ROOT / ".github/workflows/validate.yml").read_text()
    assert "run_campaign.py" not in ordinary and "secrets.HOBEN" not in ordinary
