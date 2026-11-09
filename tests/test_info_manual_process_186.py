"""Real short OS guardians; probes never represent a Hoben observation."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import info_manual_process as guard
from scripts.info_manual_contract import (
    OBSERVATION,
    PROCESS,
    build_report,
    validate_report,
)

ROOT = Path(__file__).resolve().parents[1]
PROOF = {
    "merge_sha": "a" * 40,
    "candidate_sha": "b" * 40,
    "claim_sha": "c" * 40,
    "environment_digest": "d" * 64,
    "contract_digest": "e" * 64,
    "launch_tag_sha": "f" * 40,
    "pr_number": 1,
    "ci_run_id": 2,
    "run_id": 3,
    "run_attempt": 1,
    "environment_id": 4,
}

# Only the test substitutes this fixed benign source for the fixed guardian
# command. There is no fixture/path/command selector in the production CLI.
PROBE = r"""
import os, sys, json, signal, time
sys.path.insert(0,sys.argv[1])
from scripts import info_manual_process as g
from scripts.info_manual_contract import OBSERVATION
mode=sys.argv[2]
assert mode in {'cooperate','ignore-term','orphan','escaped','wrong-nonce','missing'}
g.LIMITS={'observation_ms':100,'cleanup_ms':500,'total_ms':600}
g.FINAL_RESERVE=.005;g.TERM_RESERVE=.2;g.KILL_RESERVE=.1;g.CANCEL_GRACE=.05;g.POLL=.002
def worker(identity,result,origin):
    signal.alarm(3)  # Independent lifetime cap even if the guardian is faulty.
    raw=b''
    while True:
        chunk=os.read(identity,1024)
        if not chunk:break
        raw+=chunk
    h=json.loads(raw)
    if mode in {'ignore-term','orphan','escaped'}:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        signal.signal(signal.SIGUSR1,signal.SIG_IGN)
    if mode in {'orphan','escaped'}:
        child=os.fork()
        if child==0:
            signal.alarm(3)
            if mode=='escaped':os.setpgid(0,0)
            while True:signal.pause()
        os._exit(0)
    if mode=='ignore-term':
        while True:signal.pause()
    if mode!='missing':
        g.packet(result,{'nonce':h['nonce'] if mode!='wrong-nonce' else 'invalid',
                         'observation':dict(OBSERVATION)})
    os.close(result);os._exit(0)
g._guardian(int(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5]),time.monotonic(),worker=worker)
"""


def run_probe(monkeypatch, mode, *, cancel=False):
    original = subprocess.Popen
    processes = []

    def spawn(command, **kwargs):
        assert command[:5] == [
            sys.executable,
            "-I",
            "-S",
            str(guard.__file__),
            "--guardian",
        ]
        assert kwargs["env"] == {"LANG": "C.UTF-8"}
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        command = [
            sys.executable,
            "-I",
            "-S",
            "-c",
            PROBE,
            str(ROOT),
            mode,
            *command[5:],
        ]
        process = original(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(guard.subprocess, "Popen", spawn)
    report = guard.run_process(
        PROOF,
        {"user": "offline-probe", "device": "offline-probe"},
        cancelled=lambda: cancel,
    )
    if cancel:
        assert not processes and report["result"] == "NOT RUN"
        return report
    assert len(processes) == 1 and processes[0].poll() is not None
    assert report["result"] != "SUCCESS"
    assert report["process"]["guardian_waited"] and report["process"]["control_closed"]
    assert report == validate_report(report, PROOF)
    return report


def test_actual_kernel_reap_and_private_report_binding(monkeypatch):
    report = run_probe(monkeypatch, "cooperate")
    p = report["process"]
    assert all(
        p[k]
        for k in ("spawned", "isolated", "child_report_bound", "group_empty", "exit_ok")
    )
    assert p["children_reaped"] == 1
    assert not report["observation"]["started"]  # A dummy is never TLS evidence.


@pytest.mark.parametrize("mode", ["ignore-term", "orphan", "escaped"])
def test_noncooperative_or_escaped_descendants_are_killed_adopted_reaped(
    monkeypatch, mode
):
    report = run_probe(monkeypatch, mode)
    p = report["process"]
    assert p["term_requested"] and p["kill_requested"] and p["group_empty"]
    assert p["children_reaped"] == (1 if mode == "ignore-term" else 2)
    assert report["result"] == "FAILURE"


@pytest.mark.parametrize("mode", ["wrong-nonce", "missing"])
def test_missing_or_forged_child_report_does_not_attest_observation(monkeypatch, mode):
    report = run_probe(monkeypatch, mode)
    assert not report["process"]["child_report_bound"]
    assert report["result"] == "FAILURE"


def test_cancel_before_identity_transfer_is_fail_closed(monkeypatch):
    report = run_probe(monkeypatch, "ignore-term", cancel=True)
    assert report["result"] in {"FAILURE", "NOT RUN"}
    assert not report["process"]["exit_ok"]


@pytest.mark.parametrize(
    "field", ["cleanup_attested", "tls_verified", "opening_accepted"]
)
def test_consistent_json_is_not_an_authenticated_live_proof(field):
    observation, process = dict(OBSERVATION), dict(PROCESS)
    process.update(
        launch_attempted=True,
        spawned=True,
        isolated=True,
        child_report_bound=True,
        children_reaped=1,
        group_empty=True,
        guardian_waited=True,
        control_closed=True,
        exit_ok=True,
        elapsed_ms=1000,
    )
    observation.update(
        started=True,
        opening_accepted=True,
        tls_verified=True,
        connections=1,
        candidate_observed=True,
        candidate_delivery_bytes=1,
        candidate_at_ms=100,
        discarded_deliveries=1,
        deliveries=1,
        received_bytes=1,
        cleanup_started_ms=110,
        transport_close_requested=True,
        transport_close_completed=True,
        rx_stopped=True,
        operations_stopped=True,
        cleanup_attested=True,
        elapsed_ms=200,
    )
    report = build_report(PROOF, observation, process)
    assert report["result"] == "INCONCLUSIVE"
    tampered = copy.deepcopy(report)
    tampered["observation"][field] = False
    if field == "cleanup_attested":
        with pytest.raises(ValueError):
            validate_report(tampered, PROOF)
    else:
        with pytest.raises(ValueError):
            build_report(PROOF, tampered["observation"], process)
    # Python structure alone deliberately supplies no publication API/receipt.
    assert len(json.dumps(report).encode()) <= 8192


def test_private_guardian_entry_refuses_arbitrary_parent_before_fork():
    import os
    import time

    pipes = [os.pipe() for _ in range(3)]
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(guard.__file__),
                "--guardian",
                str(pipes[0][0]),
                str(pipes[1][1]),
                str(pipes[2][0]),
                str(time.monotonic()),
            ],
            pass_fds=(pipes[0][0], pipes[1][1], pipes[2][0]),
            capture_output=True,
            timeout=5,
        )
        assert result.returncode != 0 and result.stdout == result.stderr == b""
    finally:
        for pair in pipes:
            for fd in pair:
                os.close(fd)


# Test-only private callback: production CLI has no selector for this source.
# The real worker is invoked only after open_connection is replaced by BIO TLS.
TLS_PROBE = r"""
import site;site.main()
import os,sys,time,signal,asyncio
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from pytest import MonkeyPatch
from scripts import info_manual_process as g
from tests.info_manual_tls_fixture_186 import install_tls,MemoryTlsPeer
files=(Path(sys.argv[2]),Path(sys.argv[3]))
def worker(identity,result,origin):
    signal.alarm(5)
    patch=MonkeyPatch()
    install_tls(patch,files)
    original=MemoryTlsPeer.write
    def write(self,data):
        original(self,data)
        if data[:1]==b'\x03':
            asyncio.get_running_loop().call_later(.05,self.deliver,b'\x0c\x0a')
    patch.setattr(MemoryTlsPeer,'write',write)
    g._worker(identity,result,origin)
g._guardian(int(sys.argv[4]),int(sys.argv[5]),int(sys.argv[6]),time.monotonic(),worker=worker)
"""


def test_real_worker_memory_tls_and_os_guardian_share_actual_cleanup(
    monkeypatch, tmp_path
):
    from tests.info_manual_tls_fixture_186 import certificate_files
    from tests.test_association import DEVICE_GUID, USER_GUID

    key, cert = certificate_files(tmp_path)
    original = subprocess.Popen

    def spawn(command, **kwargs):
        assert command[4] == "--guardian"
        return original(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                TLS_PROBE,
                str(ROOT),
                str(key),
                str(cert),
                *command[5:],
            ],
            **kwargs,
        )

    monkeypatch.setattr(guard.subprocess, "Popen", spawn)
    report = guard.run_process(PROOF, {"user": USER_GUID, "device": DEVICE_GUID})
    assert report["result"] == "INCONCLUSIVE"
    assert report["reason"] == "candidate_observed_continuation_not_proven"
    assert report["observation"]["cleanup_attested"]
    assert report["observation"]["discarded_deliveries"] == 1
    assert report["observation"]["read_requests"] == 0
    assert report["process"]["children_reaped"] == 1
    assert report["process"]["child_report_bound"] and report["process"]["group_empty"]
    assert report["process"]["guardian_waited"] and report["process"]["exit_ok"]
    # This is a test fixture, not a GitHub protected-worker publication receipt.
    assert report == validate_report(report, PROOF)
