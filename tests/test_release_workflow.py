"""Offline security tests for the manual GitHub release publisher."""

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/publish-release.yml"
REPOSITORY = "Guillaume0385/ha-hoben-community"
SHA = "a" * 40
NEW_SHA = "b" * 40

NODE_DRIVER = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const output = {
  failed: [], logs: [], releases: [], reads: [], summary: [], created: false
};
const core = {
  setFailed: value => output.failed.push(value),
  info: value => output.logs.push(value),
  summary: {
    addHeading(value) { output.summary.push(value); return this; },
    addRaw(value) { output.summary.push(value); return this; },
    addLink(label, url) { output.summary.push(label + ':' + url); return this; },
    async write() { return this; }
  }
};
const missing = () => {
  const error = new Error('PRIVATE-NOT-FOUND');
  error.status = 404;
  throw error;
};
let releaseCreated = false;
const github = {rest: {
  repos: {
    getBranch: async args => {
      output.reads.push(['branch', args]);
      if (input.api_error === 'branch') throw new Error('PRIVATE-API-ERROR');
      return {data: {commit: {sha: input.current_main_sha}}};
    },
    getContent: async args => {
      output.reads.push(['content', args.path, args.ref]);
      if (input.api_error === args.path) throw new Error('PRIVATE-API-ERROR');
      const text = input.files[args.path];
      if (text === undefined) return {data: []};
      return {data: {
        type: 'file',
        content: Buffer.from(text, 'utf8').toString('base64')
      }};
    },
    getReleaseByTag: async args => {
      output.reads.push(['release', args.tag]);
      if (input.api_error === 'release-read') throw new Error('PRIVATE-API-ERROR');
      if (!input.existing_release) return missing();
      return {data: {tag_name: args.tag}};
    },
    createRelease: async args => {
      if (input.api_error === 'release-create') throw new Error('PRIVATE-API-ERROR');
      output.releases.push(args);
      releaseCreated = true;
      output.created = true;
      return {data: {
        tag_name: args.tag_name,
        prerelease: args.prerelease,
        html_url: 'https://github.example/release'
      }};
    }
  },
  git: {
    getRef: async args => {
      output.reads.push(['ref', args.ref]);
      if (input.api_error === 'ref') throw new Error('PRIVATE-API-ERROR');
      if (!releaseCreated && !input.existing_tag) return missing();
      return {data: {object: {
        type: input.created_ref_type || 'commit',
        sha: input.created_ref_sha || input.context.sha
      }}};
    }
  }
}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const run = new AsyncFunction('github', 'context', 'core', input.script);
run(github, input.context, core)
  .then(() => process.stdout.write(JSON.stringify(output)))
  .catch(() => {
    process.stderr.write('Unhandled workflow script failure');
    process.exit(1);
  });
"""


@pytest.fixture
def workflow():
    """BaseLoader keeps GitHub's on/boolean syntax as strings."""
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.fixture
def context():
    return {
        "eventName": "workflow_dispatch",
        "actor": "Guillaume0385",
        "ref": "refs/heads/main",
        "sha": SHA,
        "repo": {"owner": "Guillaume0385", "repo": "ha-hoben-community"},
        "payload": {"sender": {"login": "Guillaume0385"}},
    }


def _manifest(version: str) -> str:
    return json.dumps({"domain": "hoben", "version": version})


def _changelog(version: str) -> str:
    return (
        "# Changelog\n\n"
        f"## v{version} — Test release\n\n"
        "Included release notes.\n\n"
        "### Known limitations\n\n"
        "Still a test.\n\n"
        "## v0.0.1 — Older\n\n"
        "Old notes must not be published.\n"
    )


def execute_script(
    workflow,
    context,
    *,
    version="0.1.0-beta1",
    prerelease="true",
    confirm="RELEASE",
    current_main_sha=SHA,
    files=None,
    existing_tag=False,
    existing_release=False,
    env=None,
    **extra,
):
    """Run the actual workflow JavaScript with synthetic GitHub API doubles."""
    node = shutil.which("node")
    assert node is not None
    step = workflow["jobs"]["publish"]["steps"][0]
    payload = {
        "script": step["with"]["script"],
        "context": context,
        "current_main_sha": current_main_sha,
        "files": files
        or {
            "custom_components/hoben/manifest.json": _manifest(version),
            "CHANGELOG.md": _changelog(version),
        },
        "existing_tag": existing_tag,
        "existing_release": existing_release,
        **extra,
    }
    result = subprocess.run(
        [node, "-e", NODE_DRIVER],
        input=json.dumps(payload),
        env={
            **os.environ,
            "EXPECTED_VERSION": version,
            "PRE_RELEASE": prerelease,
            "CONFIRM_RELEASE": confirm,
            "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
            "GITHUB_RUN_ATTEMPT": "1",
            **(env or {}),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "PRIVATE" not in result.stdout + result.stderr
    return json.loads(result.stdout)


def test_workflow_is_manual_owner_main_only_with_minimal_permissions(workflow):
    assert set(workflow["on"]) == {"workflow_dispatch"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"expected_version", "prerelease", "confirm"}
    assert inputs["prerelease"]["type"] == "boolean"
    assert inputs["prerelease"]["default"] == "true"
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "publish-release",
        "cancel-in-progress": "false",
    }

    job = workflow["jobs"]["publish"]
    assert " ".join(job["if"].split()) == (
        "github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/main' && "
        "github.actor == 'Guillaume0385'"
    )
    assert job["permissions"] == {"contents": "write"}
    assert "environment" not in job
    assert "secrets." not in json.dumps(job)
    assert len(job["steps"]) == 1
    step = job["steps"][0]
    assert step["uses"] == (
        "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd"
    )
    assert "run" not in step
    assert "checkout@" not in json.dumps(job)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        ("eventName", "push"),
        ("eventName", "schedule"),
        ("ref", "refs/heads/release"),
        ("ref", "refs/tags/main"),
        ("actor", "someone-else"),
        ("actor", "guillaume0385"),
        ("payload.sender.login", "someone-else"),
        ("repo.owner", "fork"),
    ],
)
def test_script_rejects_non_owner_or_non_main_dispatch(
    workflow, context, path, replacement
):
    target = context
    parts = path.split(".")
    for key in parts[:-1]:
        target = target[key]
    target[parts[-1]] = replacement
    result = execute_script(workflow, context)
    assert result["failed"]
    assert result["releases"] == []
    assert result["reads"] == []


@pytest.mark.parametrize(
    "env",
    [
        {"GITHUB_TRIGGERING_ACTOR": "other"},
        {"GITHUB_TRIGGERING_ACTOR": "guillaume0385"},
        {"GITHUB_RUN_ATTEMPT": "2"},
    ],
)
def test_rerun_or_other_triggering_actor_cannot_publish(workflow, context, env):
    result = execute_script(workflow, context, env=env)
    assert result["failed"] and result["releases"] == [] and result["reads"] == []


def test_explicit_confirmation_is_required(workflow, context):
    result = execute_script(workflow, context, confirm="release")
    assert result["failed"] and result["releases"] == [] and result["reads"] == []


@pytest.mark.parametrize(
    "version",
    [
        "v0.1.0-beta1",
        "0.1",
        "0.1.0 beta1",
        "0.1.0/beta1",
        "../0.1.0",
        "0.1.0-",
    ],
)
def test_version_input_cannot_be_an_arbitrary_tag(workflow, context, version):
    result = execute_script(workflow, context, version=version)
    assert result["failed"] and result["releases"] == [] and result["reads"] == []


def test_current_main_must_still_equal_dispatch_sha(workflow, context):
    result = execute_script(workflow, context, current_main_sha=NEW_SHA)
    assert result["failed"] and result["releases"] == []
    assert result["reads"][0][0] == "branch"


def test_manifest_version_must_match_input(workflow, context):
    files = {
        "custom_components/hoben/manifest.json": _manifest("0.1.0-beta2"),
        "CHANGELOG.md": _changelog("0.1.0-beta1"),
    }
    result = execute_script(workflow, context, files=files)
    assert result["failed"] and result["releases"] == []


@pytest.mark.parametrize(
    ("version", "prerelease"),
    [("0.1.0-beta1", "false"), ("0.1.0", "true")],
)
def test_prerelease_flag_must_match_version_suffix(
    workflow, context, version, prerelease
):
    result = execute_script(workflow, context, version=version, prerelease=prerelease)
    assert result["failed"] and result["releases"] == [] and result["reads"] == []


def test_matching_changelog_section_is_required_and_scoped(workflow, context):
    result = execute_script(workflow, context)
    assert result["failed"] == []
    assert len(result["releases"]) == 1
    release = result["releases"][0]
    assert release["tag_name"] == "v0.1.0-beta1"
    assert release["target_commitish"] == SHA
    assert release["name"] == "v0.1.0-beta1"
    assert release["draft"] is False
    assert release["prerelease"] is True
    assert "Included release notes." in release["body"]
    assert "Known limitations" in release["body"]
    assert "Old notes must not be published." not in release["body"]
    assert "v0.0.1" not in release["body"]
    assert result["created"]
    assert SHA in " ".join(result["logs"])
    assert "v0.1.0-beta1" in " ".join(result["summary"])


def test_stable_release_path_is_supported_without_prerelease(workflow, context):
    result = execute_script(
        workflow, context, version="0.1.0", prerelease="false"
    )
    assert result["failed"] == []
    release = result["releases"][0]
    assert release["tag_name"] == "v0.1.0"
    assert release["prerelease"] is False


@pytest.mark.parametrize(
    ("existing_tag", "existing_release"),
    [(True, False), (False, True)],
)
def test_existing_tag_or_release_fails_closed(
    workflow, context, existing_tag, existing_release
):
    result = execute_script(
        workflow,
        context,
        existing_tag=existing_tag,
        existing_release=existing_release,
    )
    assert result["failed"] and result["releases"] == []


def test_missing_or_empty_changelog_section_fails_closed(workflow, context):
    files = {
        "custom_components/hoben/manifest.json": _manifest("0.1.0-beta1"),
        "CHANGELOG.md": "# Changelog\n\n## v0.1.0-beta2\n\nOther release.\n",
    }
    result = execute_script(workflow, context, files=files)
    assert result["failed"] and result["releases"] == []


@pytest.mark.parametrize(
    "api_error",
    ["branch", "custom_components/hoben/manifest.json", "CHANGELOG.md", "ref", "release-read", "release-create"],
)
def test_api_failures_are_sanitized_and_never_reported_as_success(
    workflow, context, api_error
):
    result = execute_script(workflow, context, api_error=api_error)
    assert result["failed"]
    assert "PRIVATE" not in json.dumps(result)
    if api_error != "release-create":
        assert result["releases"] == []


def test_post_creation_ref_must_point_to_exact_dispatched_main(workflow, context):
    result = execute_script(workflow, context, created_ref_sha=NEW_SHA)
    assert result["failed"]
    assert len(result["releases"]) == 1
    assert not any("published" in log.lower() for log in result["logs"])
