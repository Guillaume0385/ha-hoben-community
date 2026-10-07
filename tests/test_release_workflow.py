"""Offline security tests for the manual GitHub release publisher."""

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
  failed: [],
  logs: [],
  operations: [],
  releases: [],
  releaseUpdates: [],
  createdRefs: [],
  deletedRefs: [],
  deletedReleases: [],
  summary: []
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
const collision = () => {
  const error = new Error('PRIVATE-REF-COLLISION');
  error.status = 422;
  throw error;
};
let branchReads = 0;
let reserved = false;
let draft = null;
let published = null;
const nextMainSha = () => {
  const values = input.branch_shas;
  const index = Math.min(branchReads, values.length - 1);
  branchReads++;
  return values[index];
};
const github = {rest: {
  repos: {
    getBranch: async args => {
      output.operations.push(['branch', args.branch]);
      if (input.api_error === 'branch') throw new Error('PRIVATE-API-ERROR');
      return {data: {commit: {sha: nextMainSha()}}};
    },
    getContent: async args => {
      output.operations.push(['content', args.path, args.ref]);
      if (input.api_error === args.path) throw new Error('PRIVATE-API-ERROR');
      const text = input.files[args.path];
      if (text === undefined) return {data: []};
      return {data: {
        type: 'file',
        content: Buffer.from(text, 'utf8').toString('base64')
      }};
    },
    getReleaseByTag: async args => {
      output.operations.push(['release-read', args.tag]);
      if (input.api_error === 'release-read') {
        throw new Error('PRIVATE-API-ERROR');
      }
      if (published !== null) return {data: published};
      if (input.existing_release) {
        return {data: {
          id: 999,
          tag_name: args.tag,
          draft: false,
          prerelease: true,
          html_url: 'https://github.example/existing'
        }};
      }
      return missing();
    },
    createRelease: async args => {
      output.operations.push(['create-release', args.tag_name]);
      if (input.api_error === 'create-release') {
        throw new Error('PRIVATE-API-ERROR');
      }
      output.releases.push(args);
      draft = {
        id: 123,
        tag_name: args.tag_name,
        draft: args.draft,
        prerelease: args.prerelease,
        html_url: 'https://github.example/draft'
      };
      return {data: draft};
    },
    deleteRelease: async args => {
      output.operations.push(['delete-release', args.release_id]);
      output.deletedReleases.push(args.release_id);
      if (draft?.id === args.release_id) draft = null;
      return {status: 204};
    },
    updateRelease: async args => {
      output.operations.push(['update-release', args.release_id]);
      output.releaseUpdates.push(args);
      const value = {
        id: args.release_id,
        tag_name: input.expected_tag,
        draft: args.draft,
        prerelease: args.prerelease,
        html_url: 'https://github.example/published'
      };
      if (input.api_error === 'update-release') {
        if (input.update_applied_before_error) published = value;
        throw new Error('PRIVATE-API-ERROR');
      }
      published = value;
      return {data: published};
    }
  },
  git: {
    createRef: async args => {
      output.operations.push(['create-ref', args.ref, args.sha]);
      if (input.api_error === 'create-ref') {
        throw new Error('PRIVATE-API-ERROR');
      }
      if (input.existing_tag) return collision();
      reserved = true;
      output.createdRefs.push(args);
      return {data: {ref: args.ref, object: {type: 'commit', sha: args.sha}}};
    },
    getRef: async args => {
      output.operations.push(['get-ref', args.ref]);
      if (input.api_error === 'get-ref') throw new Error('PRIVATE-API-ERROR');
      if (!reserved) return missing();
      return {data: {object: {
        type: input.created_ref_type || 'commit',
        sha: input.created_ref_sha || input.context.sha
      }}};
    },
    deleteRef: async args => {
      output.operations.push(['delete-ref', args.ref]);
      output.deletedRefs.push(args.ref);
      reserved = false;
      return {status: 204};
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
    branch_shas=None,
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
        "branch_shas": branch_shas or [SHA, SHA, SHA, SHA],
        "files": files
        or {
            "custom_components/hoben/manifest.json": _manifest(version),
            "CHANGELOG.md": _changelog(version),
        },
        "existing_tag": existing_tag,
        "existing_release": existing_release,
        "expected_tag": f"v{version}",
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
    assert result["operations"] == []


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
    assert result["failed"]
    assert result["releases"] == []
    assert result["operations"] == []


def test_explicit_confirmation_is_required(workflow, context):
    result = execute_script(workflow, context, confirm="release")
    assert result["failed"]
    assert result["releases"] == []
    assert result["operations"] == []


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
    assert result["failed"]
    assert result["releases"] == []
    assert result["operations"] == []


@pytest.mark.parametrize(
    ("version", "prerelease"),
    [("0.1.0-beta1", "false"), ("0.1.0", "true")],
)
def test_prerelease_flag_must_match_version_suffix(
    workflow, context, version, prerelease
):
    result = execute_script(workflow, context, version=version, prerelease=prerelease)
    assert result["failed"]
    assert result["operations"] == []


def test_dispatch_sha_must_initially_be_current_main(workflow, context):
    result = execute_script(workflow, context, branch_shas=[NEW_SHA])
    assert result["failed"]
    assert result["releases"] == []
    assert result["createdRefs"] == []


def test_manifest_version_must_match_input(workflow, context):
    files = {
        "custom_components/hoben/manifest.json": _manifest("0.1.0-beta2"),
        "CHANGELOG.md": _changelog("0.1.0-beta1"),
    }
    result = execute_script(workflow, context, files=files)
    assert result["failed"]
    assert result["releases"] == []
    assert result["createdRefs"] == []


def test_matching_changelog_section_is_required(workflow, context):
    files = {
        "custom_components/hoben/manifest.json": _manifest("0.1.0-beta1"),
        "CHANGELOG.md": "# Changelog\n\n## v0.1.0-beta2\n\nOther release.\n",
    }
    result = execute_script(workflow, context, files=files)
    assert result["failed"]
    assert result["releases"] == []
    assert result["createdRefs"] == []


def test_existing_release_fails_before_any_tag_write(workflow, context):
    result = execute_script(workflow, context, existing_release=True)
    assert result["failed"]
    assert result["createdRefs"] == []
    assert result["releases"] == []


def test_tag_is_reserved_atomically_before_any_release(workflow, context):
    result = execute_script(workflow, context, existing_tag=True)
    assert result["failed"]
    assert result["releases"] == []
    assert result["deletedRefs"] == []
    operations = [item[0] for item in result["operations"]]
    assert "create-ref" in operations
    assert "create-release" not in operations


def test_main_is_rechecked_immediately_before_tag_reservation(workflow, context):
    result = execute_script(workflow, context, branch_shas=[SHA, NEW_SHA])
    assert result["failed"]
    assert result["createdRefs"] == []
    assert result["releases"] == []
    operations = [item[0] for item in result["operations"]]
    assert operations.count("branch") == 2
    assert "create-ref" not in operations


def test_main_change_after_tag_reservation_rolls_back_before_release(
    workflow, context
):
    result = execute_script(
        workflow,
        context,
        branch_shas=[SHA, SHA, NEW_SHA],
    )
    assert result["failed"]
    assert len(result["createdRefs"]) == 1
    assert result["deletedRefs"] == ["tags/v0.1.0-beta1"]
    assert result["releases"] == []
    operations = [item[0] for item in result["operations"]]
    assert operations.index("create-ref") < operations.index("delete-ref")
    assert "create-release" not in operations


def test_main_change_before_publication_removes_draft_and_reserved_tag(
    workflow, context
):
    result = execute_script(
        workflow,
        context,
        branch_shas=[SHA, SHA, SHA, NEW_SHA],
    )
    assert result["failed"]
    assert len(result["releases"]) == 1
    assert result["releases"][0]["draft"] is True
    assert result["deletedReleases"] == [123]
    assert result["deletedRefs"] == ["tags/v0.1.0-beta1"]
    assert result["releaseUpdates"] == []


def test_valid_beta_publishes_exact_tag_after_draft_verification(workflow, context):
    result = execute_script(workflow, context)
    assert result["failed"] == []
    assert len(result["createdRefs"]) == 1
    created_ref = result["createdRefs"][0]
    assert created_ref == {
        "owner": "Guillaume0385",
        "repo": "ha-hoben-community",
        "ref": "refs/tags/v0.1.0-beta1",
        "sha": SHA,
    }

    assert len(result["releases"]) == 1
    draft = result["releases"][0]
    assert draft["tag_name"] == "v0.1.0-beta1"
    assert draft["target_commitish"] == SHA
    assert draft["name"] == "v0.1.0-beta1"
    assert draft["draft"] is True
    assert draft["prerelease"] is True
    assert "Included release notes." in draft["body"]
    assert "Known limitations" in draft["body"]
    assert "Old notes must not be published." not in draft["body"]

    assert len(result["releaseUpdates"]) == 1
    publication = result["releaseUpdates"][0]
    assert publication["release_id"] == 123
    assert publication["draft"] is False
    assert publication["prerelease"] is True
    assert publication["make_latest"] == "false"

    operations = [item[0] for item in result["operations"]]
    assert operations.count("branch") == 4
    assert operations.index("create-ref") < operations.index("create-release")
    assert operations.index("create-release") < operations.index("update-release")
    assert result["deletedRefs"] == []
    assert result["deletedReleases"] == []
    assert SHA in " ".join(result["logs"])
    assert "v0.1.0-beta1" in " ".join(result["summary"])


def test_stable_release_path_marks_latest(workflow, context):
    result = execute_script(
        workflow,
        context,
        version="0.1.0",
        prerelease="false",
    )
    assert result["failed"] == []
    assert result["releaseUpdates"][0]["prerelease"] is False
    assert result["releaseUpdates"][0]["make_latest"] == "true"


@pytest.mark.parametrize(
    "api_error",
    ["create-ref", "create-release", "update-release"],
)
def test_write_api_failures_fail_closed_and_roll_back_when_possible(
    workflow, context, api_error
):
    result = execute_script(workflow, context, api_error=api_error)
    assert result["failed"]
    assert "PRIVATE" not in json.dumps(result)
    if api_error == "create-ref":
        assert result["createdRefs"] == []
        assert result["releases"] == []
    elif api_error == "create-release":
        assert result["deletedRefs"] == ["tags/v0.1.0-beta1"]
    else:
        assert result["deletedReleases"] == [123]
        assert result["deletedRefs"] == ["tags/v0.1.0-beta1"]


def test_lost_publish_response_recovers_only_the_exact_public_release(
    workflow, context
):
    result = execute_script(
        workflow,
        context,
        api_error="update-release",
        update_applied_before_error=True,
    )
    assert result["failed"] == []
    assert len(result["releaseUpdates"]) == 1
    assert result["deletedReleases"] == []
    assert result["deletedRefs"] == []
    assert any(item[0] == "release-read" for item in result["operations"])


def test_post_publication_ref_must_still_point_to_exact_sha(workflow, context):
    result = execute_script(workflow, context, created_ref_sha=NEW_SHA)
    assert result["failed"]
    assert len(result["releaseUpdates"]) == 0
    assert result["deletedReleases"] == [123]
    assert result["deletedRefs"] == []
