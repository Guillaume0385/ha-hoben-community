"""Fixed session-300 collector; only an admitted, isolated launcher may run live.

No capture file or raw log is ever produced. This module schedules the shared
HA-independent lifecycle and projects fixed counters, never register values.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.hoben.exceptions import (  # noqa: E402
    HobenAuthorizationRequiredError,
    HobenClosedError,
    HobenError,
    HobenModbusError,
    HobenProtocolError,
    HobenTimeoutError,
    HobenTransportError,
)
from custom_components.hoben.v4_experiment import (  # noqa: E402
    Session300,
    Session300BudgetError,
)
from custom_components.hoben.v4_lifecycle import V4Lifecycle  # noqa: E402
from custom_components.hoben.v4_session import SessionState, V4Session  # noqa: E402

REPO = "Guillaume0385/ha-hoben-community"
WORKFLOW = f"{REPO}/.github/workflows/hoben-session-300.yml@refs/heads/experimental"
RESULTS = {"continuous_300s", "reconnected", "interrupted", "inconclusive", "not_run"}
STOPS = {
    "completed",
    "recovery_verified",
    "protocol",
    "budget",
    "transport",
    "timeout",
    "modbus",
    "closed",
    "cancelled",
    "internal",
    "context",
    "authorization",
}
KEYS = {
    "schema",
    "scenario",
    "merge_sha",
    "candidate_sha",
    "run_id",
    "run_attempt",
    "pr_number",
    "boundary_proven",
    "result",
    "terminal",
    "duration_ms",
    "opens",
    "reconnections",
    "pings",
    "pongs",
    "reads",
    "reads_ok",
    "reads_failed",
    "responses",
    "rx_bytes_total",
    "rx_chunks_total",
    "read_slot",
    "failure_phase",
    "failure_category",
    "message_category",
}


def require(ok):
    if not ok:
        raise ValueError("invalid_session_300_report")


def validate_report(report, proof):
    """Independent fixed projection: reject keys and values outside the schema."""
    require(type(report) is dict and set(report) == KEYS)
    require(
        type(report["schema"]) is int
        and report["schema"] == 1
        and report["scenario"] == "session-300"
    )
    require(report["boundary_proven"] is False)
    for key in ("merge_sha", "candidate_sha"):
        require(type(report[key]) is str and re.fullmatch(r"[0-9a-f]{40}", report[key]))
    for key in ("merge_sha", "candidate_sha", "run_id", "run_attempt", "pr_number"):
        require(report[key] == proof[key] and type(report[key]) is type(proof[key]))
    require(report["run_attempt"] == 1)
    for key in ("run_id", "pr_number"):
        require(type(report[key]) is int and report[key] > 0)
    for key, limit in {
        "duration_ms": 300000,
        "opens": 3,
        "reconnections": 2,
        "pings": 1048576,
        "pongs": 1048576,
        "reads": 6,
        "reads_ok": 6,
        "reads_failed": 6,
        "responses": 6,
        "rx_bytes_total": 1048576,
        "rx_chunks_total": 1048576,
        "read_slot": 6,
    }.items():
        require(type(report[key]) is int and 0 <= report[key] <= limit)
    require(report["result"] in RESULTS and report["terminal"] in STOPS)
    require(report["failure_phase"] in {"none", "opening", "scheduled_read", "lifecycle_transition", "teardown"})
    require(report["failure_category"] in STOPS)
    require(report["message_category"] == "unclassified")
    require(report["failure_category"] == report["terminal"])
    require(report["read_slot"] <= report["reads"])
    require(report["reconnections"] == max(0, report["opens"] - 1))
    require(report["pongs"] <= report["pings"])
    require(report["reads_ok"] + report["reads_failed"] == report["reads"])
    require(report["reads_ok"] <= report["responses"] <= report["reads"])
    if report["result"] in {"continuous_300s", "reconnected"}:
        require(report["duration_ms"] == 300000 and report["reads_ok"] > 0)
        require(report["pings"] == report["pongs"])
        if report["result"] == "continuous_300s":
            require(
                report["opens"] == 1
                and report["reads_failed"] == 0
                and report["terminal"] == "completed"
            )
        else:
            require(report["opens"] >= 2 and report["terminal"] == "recovery_verified")
    else:
        require(report["terminal"] not in {"completed", "recovery_verified"})
    return {key: report[key] for key in sorted(KEYS)}


async def observe(
    lifecycle, budget, proof, *, clock=time.monotonic, sleep=asyncio.sleep
):
    """Observe exactly one useful window; shared code owns TLS, RX and recovery."""
    start = None
    stop = None
    reads_ok = 0
    last_success_attempt = None
    result, terminal = "not_run", "context"
    phase = "opening"

    async def race(awaitable):
        operation = asyncio.create_task(awaitable)
        try:
            await asyncio.wait({operation, stop}, return_when=asyncio.FIRST_COMPLETED)
            if stop.done():
                stop.result()  # Only typed/fixed failures are classified below.
            return await operation
        finally:
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    try:
        # Reserve ten seconds for controlled teardown, within the 360 s parent
        # hard process deadline. Individual TLS operations retain their limits.
        async with asyncio.timeout(350):
            await lifecycle.connect()
            start = clock()
            phase = "lifecycle_transition"
            end = start + 300
            stop = asyncio.create_task(lifecycle.wait_stopped())
            while clock() < end and budget.requests < 6:
                due = max(clock(), budget.next_read_at)
                if due >= end:
                    break
                await race(sleep(max(0, due - clock())))
                await race(lifecycle.wait_connected())
                if clock() >= end:
                    break
                phase = "scheduled_read"
                try:
                    # Discard the returned registers; never put them in a report.
                    await race(
                        lifecycle.request_v4_data(timeout=min(30, end - clock()))
                    )
                    reads_ok += 1
                    last_success_attempt = lifecycle.snapshot.attempts
                    phase = "lifecycle_transition"
                except HobenTransportError:
                    # No replay: a subsequent scheduled slot may use a fresh
                    # session after the lifecycle has completed cleanup/backoff.
                    if stop.done():
                        stop.result()
            phase = "lifecycle_transition"
            await race(sleep(max(0, end - clock())))
            complete = (
                clock() >= end
                and lifecycle.state is SessionState.CONNECTED
                and budget.usable
                and reads_ok > 0
                and last_success_attempt == lifecycle.snapshot.attempts
                and budget.pings == budget.pongs
            )
            if complete:
                result = "reconnected" if budget.opens > 1 else "continuous_300s"
                terminal = "recovery_verified" if budget.opens > 1 else "completed"
            else:
                result, terminal = "inconclusive", "protocol"
    except asyncio.CancelledError:
        raise
    except (TimeoutError, HobenTimeoutError):
        result, terminal = "interrupted", "timeout"
    except Session300BudgetError:
        result, terminal = "inconclusive", "budget"
    except HobenModbusError:
        result, terminal = "inconclusive", "modbus"
    except HobenProtocolError:
        result, terminal = "inconclusive", "protocol"
    except HobenAuthorizationRequiredError:
        result, terminal = "inconclusive", "authorization"
    except HobenClosedError:
        result, terminal = "interrupted", "closed"
    except HobenError:
        result, terminal = "interrupted", "transport"
    except Exception:
        result, terminal = "interrupted", "internal"
    finally:
        failure_phase = "none" if terminal in {"completed", "recovery_verified"} else phase
        measured = 0 if start is None else max(0, int((clock() - start) * 1000))
        if stop is not None:
            stop.cancel()
            await asyncio.gather(stop, return_exceptions=True)
        try:
            async with asyncio.timeout(10):
                await lifecycle.close()
        except Exception:
            result, terminal = "interrupted", "closed"
            failure_phase = "teardown"
    duration = min(300000, measured)
    return validate_report(
        {
            "schema": 1,
            "scenario": "session-300",
            "boundary_proven": False,
            **proof,
            "result": result,
            "terminal": terminal,
            "duration_ms": duration,
            "opens": budget.opens,
            "reconnections": max(0, budget.opens - 1),
            "pings": budget.pings,
            "pongs": budget.pongs,
            "reads": budget.requests,
            "reads_ok": reads_ok,
            "reads_failed": budget.requests - reads_ok,
            "responses": budget.responses,
            "rx_bytes_total": budget.rx_bytes,
            "rx_chunks_total": budget.rx_chunks,
            "read_slot": budget.requests,
            "failure_phase": failure_phase,
            "failure_category": terminal,
            "message_category": "unclassified",
        },
        proof,
    )


def context_proof(env):
    """Refuse non-admitted execution before looking at any Hoben identity."""
    require(
        env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REPOSITORY") == REPO
    )
    require(
        env.get("GITHUB_EVENT_NAME") == "push"
        and env.get("GITHUB_REF") == "refs/heads/experimental"
    )
    require(
        env.get("GITHUB_ACTOR") == env.get("GITHUB_TRIGGERING_ACTOR") == "Guillaume0385"
    )
    require(
        env.get("GITHUB_RUN_ATTEMPT") == "1" and env.get("SESSION300_PHASE") == "live"
    )
    require(env.get("GITHUB_WORKFLOW_REF") == WORKFLOW)
    sha = env.get("GITHUB_SHA")
    require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha))
    require(sha == env.get("GITHUB_WORKFLOW_SHA") == env.get("SESSION300_APPROVED_SHA"))
    proof = {
        "merge_sha": sha,
        "candidate_sha": env.get("SESSION300_CANDIDATE_SHA"),
        "run_attempt": 1,
    }
    require(
        isinstance(proof["candidate_sha"], str)
        and re.fullmatch(r"[a-f0-9]{40}", proof["candidate_sha"])
    )
    for name, field in (
        ("GITHUB_RUN_ID", "run_id"),
        ("SESSION300_APPROVED_PR", "pr_number"),
    ):
        require(re.fullmatch(r"[1-9][0-9]*", env.get(name, "")))
        proof[field] = int(env[name])
    return proof


def write_report(file: Path, report):
    """Create a private report exclusively; leave no partial output on failure.

    The caller owns the newly created 0700 export directory. O_EXCL refuses
    existing files and links; fdopen owns the descriptor only after it succeeds.
    """
    descriptor = os.open(
        file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            descriptor = None
            json.dump(report, out)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        file.unlink()
        raise


def main():
    try:
        require(len(sys.argv) == 1)
        proof = context_proof(os.environ)
        actual = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"},
                timeout=5,
            )
            .decode()
            .strip()
        )
        require(actual == proof["merge_sha"])
        budget = Session300()
        lifecycle = V4Lifecycle(
            user_guid=os.environ.pop("HOBEN_USER_GUID"),
            device_guid=os.environ.pop("HOBEN_DEVICE_GUID", "") or "0" * 32,
            retry_delays=(1.0, 2.0),
            session_factory=partial(V4Session, session_300=budget),
        )
        report = asyncio.run(observe(lifecycle, budget, proof))
        directory = Path(os.environ["RUNNER_TEMP"]) / "hoben-session-300-exports"
        directory.mkdir(mode=0o700)
        write_report(directory / "report.json", report)
        return 0
    except (Exception, KeyboardInterrupt):
        return 1  # No arbitrary error, capture or stdout/stderr is published.


if __name__ == "__main__":
    raise SystemExit(main())
