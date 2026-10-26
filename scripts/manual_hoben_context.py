"""Local manual provenance only; no identity read, Hoben I/O or API token."""

import json
import re
import subprocess
from pathlib import Path

REPOSITORY = "Guillaume0385/ha-hoben-community"
WORKFLOW = f"{REPOSITORY}/.github/workflows/hoben-manual.yml@refs/heads/experimental"
PLANS = {
    "h1h2": ("h1h2",),
    "session-300": ("session-300",),
    "session-reconnect": ("session-reconnect",),
    "all": ("h1h2", "session-300", "session-reconnect"),
}


def require(fact):
    if not fact:
        raise ValueError("invalid_manual_context")


def proof(source, root, *, plans=PLANS):
    """Verify before any identity access; never manufacture a push event."""
    expected = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/experimental",
        "GITHUB_ACTOR": "Guillaume0385",
        "GITHUB_TRIGGERING_ACTOR": "Guillaume0385",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
    }
    require(all(source.get(k) == v for k, v in expected.items()))
    selection = source.get("MANUAL_HOBEN_SCENARIO")
    require(selection in plans)
    sha = source.get("GITHUB_SHA", "")
    require(re.fullmatch(r"[a-f0-9]{40}", sha) is not None)
    require(sha == source.get("GITHUB_WORKFLOW_SHA") == source.get("MANUAL_HOBEN_SHA"))
    candidate = source.get("MANUAL_HOBEN_CANDIDATE", "")
    require(re.fullmatch(r"[a-f0-9]{40}", candidate) is not None)
    result = {"merge_sha": sha, "candidate_sha": candidate, "run_attempt": 1}
    for key, target in (("GITHUB_RUN_ID", "run_id"), ("MANUAL_HOBEN_PR", "pr_number")):
        require(re.fullmatch(r"[1-9][0-9]{0,19}", source.get(key, "")) is not None)
        result[target] = int(source[key])
    event_path = Path(source["GITHUB_EVENT_PATH"])
    require(event_path.stat().st_size <= 1048576)
    event = json.loads(event_path.read_text())
    require(event["inputs"] == {"scenario": selection})
    require(
        event["repository"]["full_name"] == REPOSITORY
        and event["repository"]["id"] == 1401398724
    )
    require(
        event["sender"]["login"] == "Guillaume0385"
        and event["sender"]["id"] == 18246624
        and event["sender"]["type"] == "User"
    )
    storage = Path(source["RUNNER_TEMP"]).resolve(strict=True)
    require(storage.is_dir())
    for checkout in (Path(root), Path(root).parent / "trusted"):
        require(checkout.is_dir() and not checkout.is_symlink())
        require(
            storage != checkout.resolve()
            and not storage.is_relative_to(checkout.resolve())
        )
        actual = (
            subprocess.check_output(
                ["/usr/bin/git", "rev-parse", "HEAD"],
                cwd=checkout,
                stderr=subprocess.DEVNULL,
                timeout=5,
                env={"PATH": "/usr/bin:/bin"},
            )
            .decode()
            .strip()
        )
        require(actual == sha)
    return selection, result
