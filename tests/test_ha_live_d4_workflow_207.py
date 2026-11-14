"""#207 D4-D: static real-workflow wiring and #186 tampering regressions."""

import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_d4_connected_to_existing_manual_ha_workflow():
    workflow = yaml.load(
        (ROOT / ".github/workflows/hoben-ha-manual.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert workflow["name"] == "Vérification réelle Home Assistant"
    assert list(workflow["on"]) == ["workflow_dispatch"]
    assert workflow["concurrency"]["group"] == "hoben-read-only-observation"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    jobs = workflow["jobs"]
    assert jobs["collect"]["environment"] == "hoben-live"
    assert jobs["d4-preflight"]["needs"] == "admission"
    assert jobs["d4-claim"]["needs"] == "d4-preflight"
    assert set(jobs["collect"]["needs"]) == {
        "admission",
        "d4-preflight",
        "d4-claim",
    }
    assert jobs["d4-claim"]["permissions"] == {"contents": "write"}
    assert jobs["d4-preflight"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pull-requests": "read",
    }
    assert "needs.d4-claim.result == 'success'" in jobs["collect"]["if"]
    assert "inputs.scenario != 'all'" in jobs["collect"]["if"]
    assert "scenario !== 'all'" in jobs["admission"]["steps"][0]["run"]
    assert "refs/heads/experimental" in jobs["admission"]["steps"][0]["run"]
    steps = jobs["collect"]["steps"]
    recheck = next(i for i, s in enumerate(steps) if s.get("id") == "d4-recheck")
    capture = next(i for i, s in enumerate(steps) if s.get("id") == "d4-capture")
    old_capture = next(i for i, s in enumerate(steps) if s.get("id") == "capture")
    assert recheck < capture
    assert all("secrets." not in json.dumps(s) for s in steps[:old_capture])
    assert steps[old_capture]["if"] == "inputs.scenario != 'hoben-live'"
    assert steps[capture]["if"].endswith("steps.d4-recheck.outputs.approved == 'true'")
    assert steps[capture]["env"] == {
        "HOBEN_USER_GUID": "${{ secrets.HOBEN_USER_GUID }}"
    }
    assert steps[capture]["run"] == "python -I scripts/ha_live_d4_run.py"
    assert "secrets." not in json.dumps(jobs["d4-preflight"])
    assert "secrets." not in json.dumps(jobs["d4-claim"])
    assert "environment" not in jobs["d4-preflight"]
    assert "environment" not in jobs["d4-claim"]
    assert "environment" not in jobs["result"]
    assert "continue-on-error" not in json.dumps(workflow)
    assert jobs["result"]["steps"][-1]["with"]["retention-days"] == "7"
    # The similarly named Info #186 workflow must remain distinct.
    info = (ROOT / ".github/workflows/hoben-manual.yml").read_text()
    assert "name: Tests Hoben manuels" in info


def test_info_integrity_rejects_unreviewed_ha_edits_and_extra_secrets():
    program = r"""
const fs = require('node:fs');
const r = require('./.github/scripts/info-manual-route.cjs');
const m = JSON.parse(fs.readFileSync(r.MANIFEST));
const sources = Object.fromEntries(r.FILES.map(x=>[x,fs.readFileSync(x,'utf8')]));
if(!r.assess(m,sources).ready) process.exit(1);
const target = '.github/workflows/hoben-ha-manual.yml';
function refused(manifest,files) {
  try{r.assess(manifest,files);return false;}catch(e){
    return e.message==='manual_info_route_not_connected';
  }
}
if(!refused(m,{...sources,[target]:sources[target]+'\n# tamper\n'}))process.exit(2);
if(!refused(m,{...sources,[target]:
  sources[target].replace('secrets.HOBEN_USER_GUID','secrets.HOBEN_DEVICE_GUID')}))
  process.exit(3);
if(!refused({...m,files:{...m.files,[target]:'0'.repeat(64)}},sources))
  process.exit(4);
if(!refused({...m,files:{...m.files,
  '.github/scripts/info-manual-route.cjs':'0'.repeat(64)}},sources))process.exit(5);
"""
    done = subprocess.run(
        ["node", "-e", program],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
