"""018+019: exercise current embedded controllers and both public validators.

No workflow dispatch, Hoben transport or Docker call is made. The run parent,
closed synthetic receipts, actual YAML commands and fresh publication runner
are connected locally; HA peers separately exercise the real HA implementation.
"""

import base64
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.campaign_runtime_contract import (
    CHOICES,
    SECONDS,
    observed_status,
    plan,
    stage,
    validate_report,
)
from scripts.ha_campaign_evidence import project
from scripts.run_campaign import context, run
from tests.test_campaign_minimal_admission import context as admission_context
from tests.test_campaign_minimal_admission import controller
from tests.test_campaign_runtime import (
    PROVENANCE,
    ROOT,
    envelope,
    ha_detail,
    node_accepts,
    observed,
)


def workflow(campaign):
    name = "hoben-" + ("protocol" if campaign == "protocol" else "ha") + "-manual.yml"
    return name, yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def command(step, env):
    """Run the committed shell step, with no network-capable Node modules."""
    # The scripts load only public code and files; deny subprocess/network I/O
    # even if a future change accidentally introduces a network dependency.
    prelude = """
const Module=require('node:module'),load=Module._load;
Module._load=function(n,...a){
  if(/http|https|net|tls|dns|child_process/.test(n))throw Error('offline');
  return load.call(this,n,...a);};
globalThis.fetch=()=>{throw Error('offline');};
"""
    # NODE_OPTIONS preloads the restriction in the actual YAML command.
    restrict = Path(env["RUNNER_TEMP"]) / "campaign-offline-node.cjs"
    restrict.write_text(prelude)
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        env={**env, "NODE_OPTIONS": "--require=" + str(restrict)},
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )


@pytest.mark.parametrize("campaign", CHOICES)
@pytest.mark.parametrize("selection", ["individual", "all"])
@pytest.mark.parametrize("ref,attempt", [("experimental", 1), ("main", 3)])
def test_current_workflow_from_admission_to_fresh_runner_report(
    campaign, selection, ref, attempt, tmp_path, monkeypatch
):
    import tests.test_campaign_minimal_admission as historical

    filename, w = workflow(campaign)
    monkeypatch.setattr(historical, "workflow", lambda _: w)
    selection = CHOICES[campaign][0] if selection == "individual" else selection
    ctx = admission_context(selection, "refs/heads/" + ref)
    admitted, outputs, _ = controller(
        filename,
        "admission",
        ctx,
        tmp_path,
        {"GITHUB_RUN_ATTEMPT": str(attempt)},
    )
    assert admitted.returncode == 0 and outputs["collector_ready"] == "true"
    source = {
        "GITHUB_EVENT_PATH": str(tmp_path / "event.json"),
        "GITHUB_REPOSITORY": ctx["github.repository"],
        "GITHUB_EVENT_NAME": ctx["github.event_name"],
        "GITHUB_ACTOR": ctx["github.actor"],
        "GITHUB_TRIGGERING_ACTOR": ctx["github.triggering_actor"],
        "GITHUB_REF": ctx["github.ref"],
        "GITHUB_SHA": PROVENANCE["sha"],
        "GITHUB_RUN_ID": str(PROVENANCE["run_id"]),
        "GITHUB_RUN_ATTEMPT": str(attempt),
    }
    selected, provenance = context(source, campaign)
    now, visited = [0.0], []

    def executor(c, s, payload, deadline, **kwargs):
        assert payload == b"synthetic" and deadline <= SECONDS[c][selected]
        value = observed(c, s)
        assert value["metrics"]["cleanup"]
        now[0] += value["elapsed_ms"] / 1000
        visited.append(s)
        return value

    report = run(
        campaign,
        selected,
        provenance,
        b"synthetic",
        executor=executor,
        clock=lambda: now[0],
    )
    assert visited == list(plan(campaign, selected))
    collector, publisher = tmp_path / "collect", tmp_path / "result"
    folder = collector / "hoben-campaign-public"
    folder.mkdir(parents=True)
    publisher.mkdir()
    (folder / "report.json").write_text(json.dumps(report, separators=(",", ":")))
    env = {
        "PATH": os.environ["PATH"],
        "CAMPAIGN": campaign,
        "GITHUB_EVENT_PATH": source["GITHUB_EVENT_PATH"],
        "RUNNER_TEMP": str(collector),
        "GITHUB_OUTPUT": str(collector / "output"),
        "GITHUB_STEP_SUMMARY": str(collector / "summary"),
    }
    exports = next(s for s in w["jobs"]["collect"]["steps"] if s.get("id") == "exports")
    assert exports["if"] == "always()" and command(exports, env).returncode == 0
    encoded = (collector / "output").read_text().removeprefix("report_b64=").strip()
    env.update(
        RUNNER_TEMP=str(publisher),
        GITHUB_OUTPUT=str(publisher / "output"),
        GITHUB_STEP_SUMMARY=str(publisher / "summary"),
        PUBLIC_REPORT_B64=encoded,
        COLLECT_RESULT="success",
    )
    public_step = next(
        s for s in w["jobs"]["result"]["steps"] if s.get("id") == "public"
    )
    result = command(public_step, env)
    public = json.loads(
        (publisher / "hoben-campaign-published/report.json").read_text()
    )
    validate_report(public)
    assert public["provenance"] == provenance
    assert result.returncode == (0 if selection != "all" else 1)
    summary = (publisher / "summary").read_text()
    assert provenance["sha"] in summary and provenance["ref"] in summary
    assert "tentative `" + str(attempt) + "`" in summary
    assert "Durée totale" in summary and "plafond absolu" in summary
    assert f"{SECONDS[campaign][selection]:.3f} s" in summary
    assert "PRIVATE_PAYLOAD" not in summary + result.stdout + result.stderr
    if campaign == "ha":
        assert "1 Gio" in summary and "128 PID" in summary and "RX" not in summary
    else:
        if selection == "all":
            assert "1 Mio RX par session" in summary


@pytest.mark.parametrize("campaign", CHOICES)
@pytest.mark.parametrize(
    "field,value",
    [
        ("github.actor", "SYNTHETIC_PRIVATE_INPUT"),
        ("github.ref", "refs/heads/other"),
        ("github.event_name", "push"),
        ("inputs.scenario", "SYNTHETIC_PRIVATE_INPUT"),
    ],
)
def test_current_denial_has_no_checkout_no_false_not_connected_diagnosis(
    campaign, field, value, tmp_path, monkeypatch
):
    import tests.test_campaign_minimal_admission as historical

    filename, w = workflow(campaign)
    monkeypatch.setattr(historical, "workflow", lambda _: w)
    ctx = admission_context(**{field: value})
    admitted, outputs, _ = controller(filename, "admission", ctx, tmp_path)
    assert admitted.returncode == 1 and outputs["admitted"] == "false"
    denied_ctx = {
        **ctx,
        "needs.admission.result": "failure",
        "needs.admission.outputs.admitted": "false",
    }
    result, _, summary = controller(filename, "result", denied_ctx, tmp_path)
    assert result.returncode == 1 and "admission_not_verified" in result.stderr
    assert "non raccordée" not in summary and "SUCCESS" not in summary
    assert all("uses" not in s for s in w["jobs"]["admission"]["steps"])


@pytest.mark.parametrize("scenario", ["refresh-v4", "session-reuse", "availability"])
def test_ha_failed_or_missing_scheduled_read_cannot_be_hidden_by_later_success(
    scenario,
):
    for fault in ("earlier_error", "missing", "inactive"):
        d = ha_detail(scenario)
        e = d["evidence"]
        if fault == "earlier_error":
            e["samples"][0].update(decoded=False, available=False, error="transport")
        elif fault == "missing":
            e["samples"].pop()
        else:
            e["window"]["active"] = False
        metrics = project(scenario, d)
        assert observed_status("ha", scenario, metrics) == "FAILURE"
        value = stage(
            "ha",
            scenario,
            started=True,
            reason="observed",
            elapsed_ms=d["supervisor"]["elapsed_ms"],
            metrics=metrics,
            detail=d,
        )
        r = envelope("ha", scenario, [value])
        assert validate_report(r) and node_accepts(r)
        r["stages"][0]["status"] = r["actions_result"] = "SUCCESS"
        with pytest.raises(ValueError):
            validate_report(r)
        assert not node_accepts(r)


@pytest.mark.parametrize("campaign", CHOICES)
def test_public_validators_agree_on_mutations_of_all_report_layers(campaign):
    report = envelope(campaign, "all")
    cases = [report]

    # Include stages/evidence explicitly; nested samples are traversed too.
    def layers(value, path=()):
        if isinstance(value, dict):
            yield path
            for k, v in value.items():
                yield from layers(v, (*path, k))
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            for i, v in enumerate(value):
                yield from layers(v, (*path, i))

    for path in layers(report):
        bad = copy.deepcopy(report)
        target = bad
        for k in path:
            target = target[k]
        target["private"] = "PRIVATE_PAYLOAD"
        cases.append(bad)
    for key, bad_value in [
        ("run_id", 0),
        ("run_attempt", 2**53),
        ("sha", "PRIVATE_PAYLOAD"),
    ]:
        bad = copy.deepcopy(report)
        bad["provenance"][key] = bad_value
        cases.append(bad)
    for s in report["stages"]:
        for field, bad_value in [
            ("elapsed_ms", -1),
            ("elapsed_ms", SECONDS[campaign][s["scenario"]] * 1000 + 1),
            ("started", 1),
            ("status", "SUCCESS"),
            ("reason", "PRIVATE_PAYLOAD"),
        ]:
            bad = copy.deepcopy(report)
            bad["stages"][report["stages"].index(s)][field] = bad_value
            cases.append(bad)
    expected = []
    for value in cases:
        try:
            validate_report(value)
            expected.append(True)
        except (ValueError, TypeError):
            expected.append(False)
    code = """
const p=require('./.github/scripts/campaign-report.cjs');let s='';
process.stdin.on('data',v=>s+=v);process.stdin.on('end',()=>{
const verdicts=JSON.parse(s).map(v=>{
  try{p.validate(v);return true;}catch(_){return false;}});
process.stdout.write(JSON.stringify(verdicts));});
"""
    result = subprocess.run(
        ["node", "-e", code],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=5,
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == expected
    assert expected[0] and expected.count(False) > 30


@pytest.mark.parametrize("campaign", CHOICES)
@pytest.mark.parametrize("collect", ["failure", "cancelled"])
def test_cancelled_all_preserves_attested_prefix_and_unstarted_suffix(
    campaign, collect, tmp_path
):
    from tests.test_campaign_publication import node

    names = plan(campaign, "all")
    values = [observed(campaign, names[0])]
    values.extend(stage(campaign, s, reason="cancelled") for s in names[1:])
    r = envelope(campaign, "all", values)
    encoded = base64.b64encode(json.dumps(r, separators=(",", ":")).encode()).decode()
    assert (
        node(
            "publish", tmp_path, campaign, "all", encoded=encoded, collect=collect
        ).returncode
        == 1
    )
    public = json.loads((tmp_path / "hoben-campaign-published/report.json").read_text())
    assert (
        public["stages"][0]["status"] == "SUCCESS"
        and public["actions_result"] == "FAILURE"
    )
    assert all(
        s["status"] == "NOT RUN" and not s["started"] for s in public["stages"][1:]
    )
    assert "Job collect : `" + collect + "`" in (tmp_path / "summary").read_text()


@pytest.mark.parametrize("cause", ["authentication", "cleanup_failed", "memory"])
def test_summary_uses_attested_categorical_cause_instead_of_generic_observed(
    cause, tmp_path
):
    from tests.test_campaign_publication import node

    if cause == "memory":
        d = ha_detail("cleanup")
        d["supervisor"].update(reason="memory", oom_killed=True)
        value = stage(
            "ha",
            "cleanup",
            started=True,
            reason="observed",
            elapsed_ms=8000,
            metrics=project("cleanup", d),
            detail=d,
        )
        campaign, selection = "ha", "cleanup"
    else:
        campaign, selection = "protocol", "tls-only"
        value = observed(campaign, selection)
        value["metrics"].update(
            error="authentication" if cause == "authentication" else "none",
            cleanup=cause != "cleanup_failed",
        )
        value["status"] = "FAILURE"
    r = envelope(campaign, selection, [value])
    encoded = base64.b64encode(json.dumps(r, separators=(",", ":")).encode()).decode()
    assert (
        node("publish", tmp_path, campaign, selection, encoded=encoded).returncode == 1
    )
    summary = (tmp_path / "summary").read_text()
    assert " | FAILURE | " + cause + " | " in summary
    assert "Résultat global : **FAILURE**" in summary


@pytest.mark.parametrize("corrupt", ["duplicate", "whitespace", "fractional"])
def test_noncanonical_or_ambiguous_json_never_leaves_collector(corrupt, tmp_path):
    from tests.test_campaign_publication import node

    r = envelope("protocol", "tls-only")
    raw = json.dumps(r, separators=(",", ":"))
    if corrupt == "duplicate":
        raw = raw.replace('"schema":1', '"schema":0,"schema":1')
    elif corrupt == "fractional":
        raw = raw.replace('"schema":1', '"schema":1.0')
    else:
        raw = " " + raw
    folder = tmp_path / "hoben-campaign-public"
    folder.mkdir()
    (folder / "report.json").write_text(raw)
    assert node("prepare", tmp_path, "protocol", "tls-only").returncode == 1
    assert not (tmp_path / "output").exists()
