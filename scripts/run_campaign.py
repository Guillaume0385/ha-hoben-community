"""Manual campaign parent: sequential workers, armed deadlines and closed reports.

No dispatch/rerun API exists here. Only the protected workflow step invokes main;
offline tests exercise the same orchestration with synthetic worker receipts.
"""

import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.campaign_runtime_contract import (  # noqa: E402
    SECONDS,
    empty_metrics,
    need,
    plan,
    stage,
    validate_context,
    validate_report,
    validate_stage,
)


def context(source, campaign):
    """Repeat only minimal native-context admission; reruns have no special gate."""
    need(source.get("GITHUB_REPOSITORY") == "Guillaume0385/ha-hoben-community")
    need(source.get("GITHUB_EVENT_NAME") == "workflow_dispatch")
    need(
        source.get("GITHUB_ACTOR")
        == source.get("GITHUB_TRIGGERING_ACTOR")
        == "Guillaume0385"
    )
    event = Path(source["GITHUB_EVENT_PATH"])
    need(
        event.is_file()
        and not event.is_symlink()
        and event.stat().st_size <= 256 * 1024
    )
    selection = json.loads(event.read_bytes())["inputs"]["scenario"]
    plan(campaign, selection)
    p = validate_context(
        {
            "ref": source["GITHUB_REF"],
            "sha": source["GITHUB_SHA"],
            "run_id": int(source["GITHUB_RUN_ID"]),
            "run_attempt": int(source["GITHUB_RUN_ATTEMPT"]),
        }
    )
    return selection, p


def identity(source, *, tls_only=False):
    """User secret only; start with the documented new-client identity (§4).

    INITIAL_DEVICE_GUID is the existing protocol default, not an assigned or
    invented identity. The shared client adopts only a validated OpenedClient's
    DeviceGuid. An authorization challenge never triggers association here.
    """
    from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, normalize_user_guid

    user = source.pop("HOBEN_USER_GUID", "")
    if tls_only:
        return {"user_guid": "", "device_guid": ""}
    user = normalize_user_guid(user)
    return {"user_guid": user, "device_guid": INITIAL_DEVICE_GUID}


def execute(
    campaign,
    scenario,
    payload,
    deadline,
    *,
    image=None,
    clock=time.monotonic,
    cancelled=lambda: False,
):
    """One private pipe/ACK protocol; stop and reap the group before returning."""
    started = False
    process = None
    descriptors = set()
    output = bytearray()
    reason = "worker_failure"
    began = clock()
    data = None
    private_directory = None
    try:
        # The parent owns the capture root, so SIGKILL of an H1/H2 worker cannot
        # bypass deletion of private RX/identity files in the worker's finally.
        private_directory = tempfile.mkdtemp(prefix="hoben-campaign-stage-")
        pairs = []
        for _ in range(4):
            pair = os.pipe()
            descriptors.update(pair)  # own each pair even if the next pipe fails
            pairs.append(pair)
        (
            (identity_r, identity_w),
            (ready_r, ready_w),
            (ack_r, ack_w),
            (report_r, report_w),
        ) = pairs
        need(os.write(identity_w, payload) == len(payload))
        os.close(identity_w)
        descriptors.remove(identity_w)
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "CAMPAIGN_IDENTITY_FD": str(identity_r),
            "CAMPAIGN_READY_FD": str(ready_w),
            "CAMPAIGN_ACK_FD": str(ack_r),
            "CAMPAIGN_REPORT_FD": str(report_w),
            "CAMPAIGN_DEADLINE_NS": str(int(deadline * 1e9)),
            "CAMPAIGN_PRIVATE_DIR": private_directory,
        }
        if campaign == "ha":
            need(type(image) is str and re.fullmatch("sha256:[a-f0-9]{64}", image))
            environment["CAMPAIGN_IMAGE"] = image
        if cancelled():
            return stage(campaign, scenario, reason="cancelled")
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(ROOT / "scripts/campaign_worker.py"),
                campaign,
                scenario,
            ],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(identity_r, ready_w, ack_r, report_w),
        )
        for fd in (identity_r, ready_w, ack_r, report_w):
            os.close(fd)
            descriptors.remove(fd)
        os.set_blocking(report_r, False)
        with selectors.DefaultSelector() as selector:
            selector.register(ready_r, selectors.EVENT_READ, "ready")
            selector.register(report_r, selectors.EVENT_READ, "report")
            while clock() < deadline - 2:
                if cancelled():
                    reason = "cancelled"
                    break
                for key, _ in selector.select(
                    min(0.05, max(0, deadline - 2 - clock()))
                ):
                    if key.data == "ready":
                        need(not started and os.read(ready_r, 2) == b"R")
                        need(clock() < deadline - 2 and not cancelled())
                        started = True
                        os.write(ack_w, b"A")
                        selector.unregister(ready_r)
                    else:
                        chunk = os.read(report_r, 16385 - len(output))
                        if not chunk:
                            selector.unregister(report_r)
                        output.extend(chunk)
                        need(len(output) <= 16384)
                if process.poll() is not None:
                    while len(output) <= 16384:
                        chunk = os.read(report_r, 16385 - len(output))
                        if not chunk:
                            break
                        output.extend(chunk)
                    need(process.returncode == 0 and started and output)
                    data = validate_stage(json.loads(output), campaign)
                    need(data["scenario"] == scenario)
                    reason = data["reason"]
                    break
            else:
                reason = "timeout"
    except (Exception, KeyboardInterrupt):
        reason = "report_refused" if output else "worker_failure"
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(
                            timeout=max(0.001, min(1, deadline - clock() - 0.5))
                        )
                    except subprocess.TimeoutExpired:
                        pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=max(0.001, min(0.5, deadline - clock())))
            except (OSError, subprocess.TimeoutExpired):
                data, reason = None, "cleanup_failed"
        for fd in descriptors:
            os.close(fd)
        if private_directory is not None:
            try:
                shutil.rmtree(private_directory)
            except OSError:
                data, reason = None, "cleanup_failed"
    elapsed = max(0, int((clock() - began) * 1000))
    if clock() > deadline:
        reason = "timeout"
    if not started:
        return stage(
            campaign,
            scenario,
            reason=reason,
            elapsed_ms=min(elapsed, SECONDS[campaign][scenario] * 1000),
        )
    if data is None:
        data = stage(
            campaign,
            scenario,
            started=True,
            metrics=empty_metrics(campaign, scenario),
            detail={"rx_bytes": 0, "rx_chunks": 0} if campaign == "protocol" else None,
        )
    data.update(
        elapsed_ms=min(elapsed, SECONDS[campaign][scenario] * 1000), reason=reason
    )
    if reason != "observed" and data["started"]:
        data["status"] = "FAILURE"
    return validate_stage(data, campaign)


def run(
    campaign,
    selection,
    provenance,
    payload,
    *,
    image=None,
    executor=execute,
    clock=time.monotonic,
    cancelled=lambda: False,
):
    names = plan(campaign, selection)
    validate_context(provenance)
    start = clock()
    deadline = start + SECONDS[campaign][selection]
    stages, stopped = [], False
    for name in names:
        if stopped or cancelled() or clock() >= deadline - 2:
            value = stage(
                campaign,
                name,
                reason="cancelled"
                if cancelled()
                else "previous_failure"
                if stopped
                else "timeout",
            )
        else:
            value = executor(
                campaign,
                name,
                payload,
                min(deadline, clock() + SECONDS[campaign][name]),
                image=image,
                clock=clock,
                cancelled=cancelled,
            )
            validate_stage(value, campaign)
            need(value["scenario"] == name)
            stopped = (
                value["status"] in {"FAILURE", "NOT RUN"}
                or not value["metrics"]["cleanup"]
            )
        stages.append(value)
    elapsed = max(0, int((clock() - start) * 1000))
    if elapsed > SECONDS[campaign][selection] * 1000:
        # A late return is never a successful attestation of the parent budget.
        for value in reversed(stages):
            if value["started"]:
                value.update(status="FAILURE", reason="timeout")
                break
    report = {
        "schema": 1,
        "campaign": campaign,
        "selection": selection,
        "provenance": provenance,
        "elapsed_ms": min(elapsed, SECONDS[campaign][selection] * 1000),
        "stages": stages,
        "collection_result": "pending",
        "actions_result": "FAILURE",
    }
    return validate_report(report)


def write_report(storage, report):
    """Write only a closed projection, exclusively in a directory we created."""
    validate_report(report)
    with (storage / "report.json").open("x") as stream:
        os.chmod(stream.fileno(), 0o600)
        json.dump(report, stream, separators=(",", ":"), allow_nan=False)


def diagnostic(reason):
    """Only a fixed phase/category; never inspect or stringify an exception."""
    need(
        reason
        in {"context_refused", "identity_refused", "worker_failure", "report_refused"}
    )
    try:
        os.write(2, ("::error::" + reason + "\n").encode("ascii"))
    except OSError:
        pass  # An unavailable diagnostic channel cannot permit collection.


def refusal_report(campaign, selection, provenance, reason):
    """No worker has been entered: no observation, counters or cleanup invented."""
    return validate_report(
        {
            "schema": 1,
            "campaign": campaign,
            "selection": selection,
            "provenance": provenance,
            "elapsed_ms": 0,
            "stages": [
                stage(campaign, name, reason=reason if i == 0 else "previous_failure")
                for i, name in enumerate(plan(campaign, selection))
            ],
            "collection_result": "failure",
            "actions_result": "FAILURE",
        }
    )


def main():
    reason, storage, admitted, before_worker = "context_refused", None, None, True
    try:
        need(len(sys.argv) == 2)
        campaign = sys.argv[1]
        selection, provenance = context(os.environ, campaign)
        admitted = campaign, selection, provenance
        reason = "report_refused"
        folder = Path(os.environ["RUNNER_TEMP"]) / "hoben-campaign-public"
        folder.mkdir(mode=0o700)
        storage = folder  # no reuse/overwrite after a failed exclusive mkdir
        reason = "worker_failure"
        image = None
        if campaign == "ha":
            file = Path(os.environ["RUNNER_TEMP"]) / "hoben-ha-runtime.id"
            need(file.is_file() and not file.is_symlink() and file.stat().st_size <= 72)
            image = file.read_text().strip()
            need(re.fullmatch("sha256:[a-f0-9]{64}", image))
        reason = "identity_refused"
        private = identity(
            os.environ, tls_only=campaign == "protocol" and selection == "tls-only"
        )
        reason = "worker_failure"
        payload = json.dumps(private, separators=(",", ":")).encode()
        stopped = False

        def stop(*_):
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        before_worker = False
        report = run(
            campaign,
            selection,
            provenance,
            payload,
            image=image,
            cancelled=lambda: stopped,
        )
        reason = "report_refused"
        write_report(storage, report)
        return 0  # The independent result job still evaluates collected evidence.
    except BaseException:
        diagnostic(reason)
        # Context must be fully admitted and storage exclusively ours. Once run()
        # has been entered, a missing/invalid report cannot attest a start state.
        if before_worker and admitted is not None and storage is not None:
            try:
                write_report(storage, refusal_report(*admitted, reason))
            except BaseException:
                diagnostic("report_refused")
        return 1


if __name__ == "__main__":
    try:
        os._exit(main())
    except BaseException:
        os._exit(1)
