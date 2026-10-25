"""Real namespace/cgroup tests. Image preparation is separate from offline runs."""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from scripts.ha_live_proof import encode_report
from scripts.ha_session_supervisor import ROOT, Engine, Limits, OfflineCase, supervise
from tests.test_ha_live_proof import PROVENANCE, node_accepts

LOCAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """Allow only the fixed local engine socket, retaining every Internet ban."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Network access is forbidden in automated tests")

    def local_only(sock, address):
        if sock.family != socket.AF_UNIX or address != "/var/run/docker.sock":
            return forbidden()
        return LOCAL_CONNECT(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def test_network_guard_does_not_allow_dns_or_network_sockets():
    with pytest.raises(AssertionError):
        socket.getaddrinfo("myhoben.fr", 465)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(AssertionError):
            sock.connect(("127.0.0.1", 465))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        with pytest.raises(AssertionError):
            sock.connect("/tmp/other.sock")


@pytest.fixture(scope="session")
def sandbox_image(tmp_path_factory):
    engine = Engine()
    try:
        info = engine.request("GET", "/info", timeout=3)
    except Exception:
        pytest.skip("No local delegated sandbox; fail-closed paths tested separately")
    if info.get("CgroupVersion") != "2" or not all(
        info.get(k) is True for k in ("MemoryLimit", "SwapLimit", "PidsLimit")
    ):
        pytest.skip("Required cgroup controls absent; runtime must remain NOT RUN")
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("No local runtime image preparation tool")
    folder = tmp_path_factory.mktemp("hoben-c2a-image")
    output = folder / "image.id"
    environment = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }
    }
    command = [
        docker,
        "--host=unix:///var/run/docker.sock",
        "build",
        "--secret",
        "id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt",
        "--iidfile",
        str(output),
        str(ROOT / "scripts/ha_session_runtime"),
    ]
    with (folder / "build.log").open("wb") as log:
        result = subprocess.run(
            command, env=environment, stdout=log, stderr=log, timeout=300, check=False
        )
    assert result.returncode == 0, "Pinned offline image preparation failed"
    return output.read_text().strip()


@pytest.mark.parametrize(
    "case",
    [
        OfflineCase.HEALTHY,
        OfflineCase.CLOSE_CLIENT,
        OfflineCase.EOF,
        OfflineCase.TLS,
        OfflineCase.READ_TIMEOUT,
    ],
)
def test_real_ha_path_inside_resource_bounded_namespace(sandbox_image, case):
    r = supervise(case, sandbox_image, PROVENANCE)
    assert r["supervisor"]["started"] and r["supervisor"]["reaped"]
    assert r["supervisor"]["reason"] == "completed"
    assert r["supervisor"]["elapsed_ms"] < 360000
    assert len(r["samples"]) == 6
    if case in {OfflineCase.CLOSE_CLIENT, OfflineCase.EOF, OfflineCase.TLS}:
        assert r["criteria"]["reconnection"] == "SUCCESS"
        assert r["samples"][3]["observation"]["read_generation"] == 2
    else:
        assert r["criteria"]["reconnection"] == "INCONCLUSIVE"
    if case is OfflineCase.READ_TIMEOUT:
        assert r["outcome"] == "FAILURE"
    elif case is OfflineCase.HEALTHY:
        assert r["outcome"] == "INCONCLUSIVE"
    else:
        assert r["outcome"] == "SUCCESS"
    encoded = encode_report(r)
    assert node_accepts(encoded)
    for value in ("D" * 32, "12345678123456781234567812345678", "synthetic-private"):
        assert value not in encoded


@pytest.mark.parametrize(
    "case,reason",
    [
        (OfflineCase.MEMORY, "memory"),
        (OfflineCase.PROCESSES, "processes"),
        (OfflineCase.FORGED, "worker_failure"),
    ],
)
def test_kernel_limits_and_forged_worker_never_validate_protocol(
    sandbox_image, case, reason
):
    r = supervise(
        case,
        sandbox_image,
        PROVENANCE,
        limits=Limits(
            memory_bytes=64 * 1024**2, pids=8, useful_ms=2000, process_ms=15000
        ),
    )
    assert r["supervisor"]["reason"] == reason and r["supervisor"]["reaped"]
    assert r["supervisor"]["elapsed_ms"] <= 15000
    assert r["outcome"] == "FAILURE"
    assert r["criteria"]["reconnection"] == "NOT RUN"
    assert node_accepts(encode_report(r))


class TrackingEngine(Engine):
    def __init__(self):
        self.name = None
        self.known_pids = []
        self.distinct_sessions = False
        self.started_at = None

    def request(self, method, path, body=None, **kwargs):
        result = super().request(method, path, body, **kwargs)
        if path.startswith("/containers/create?name="):
            self.name = path.split("name=")[1]
        if (
            path.endswith("/json")
            and "/containers/" in path
            and result["State"]["Running"]
        ):
            table = super().request(
                "GET", "/containers/" + self.name + "/top?ps_args=-eo%20pid,ppid,sid"
            )
            rows = [[int(v) for v in row] for row in table["Processes"]]
            if len(rows) >= 3:
                self.known_pids = [row[0] for row in rows]
                self.distinct_sessions = len({row[2] for row in rows}) >= 3
        if path.endswith("/start"):
            self.started_at = time.monotonic()
        return result


@pytest.mark.parametrize("cancel", [False, True])
def test_noncooperative_descendants_are_stopped_with_external_deadline(
    sandbox_image, cancel
):
    engine = TrackingEngine()
    r = supervise(
        OfflineCase.RESISTANT,
        sandbox_image,
        PROVENANCE,
        engine=engine,
        cancelled=lambda: cancel and engine.distinct_sessions,
        limits=Limits(
            memory_bytes=64 * 1024**2,
            pids=8,
            useful_ms=3000 if cancel else 700,
            process_ms=15000,
        ),
    )
    assert engine.distinct_sessions and len(engine.known_pids) >= 3
    assert all(not Path("/proc/" + str(pid)).exists() for pid in engine.known_pids)
    assert r["supervisor"]["reaped"]
    assert r["supervisor"]["elapsed_ms"] <= 15000
    assert r["supervisor"]["reason"] in (
        {"cancelled", "worker_failure"} if cancel else {"timeout"}
    )
    assert r["outcome"] == "FAILURE"
    assert r["criteria"]["reconnection"] == "NOT RUN"


def test_guardian_deadline_survives_loss_of_host_control(sandbox_image):
    class LostControl(TrackingEngine):
        def request(self, method, path, body=None, **kwargs):
            if self.distinct_sessions:
                raise OSError("synthetic unavailable control channel")
            return super().request(method, path, body, **kwargs)

    engine = LostControl()
    r = supervise(
        OfflineCase.RESISTANT,
        sandbox_image,
        PROVENANCE,
        engine=engine,
        limits=Limits(
            memory_bytes=64 * 1024**2, pids=8, useful_ms=700, process_ms=5000
        ),
    )
    assert engine.distinct_sessions
    assert not r["supervisor"]["reaped"] and r["outcome"] == "FAILURE"
    # A fresh independent observer sees the original PID-1 deadline take effect.
    observer = Engine()
    try:
        while time.monotonic() - engine.started_at < 5:
            state = observer.request("GET", "/containers/" + engine.name + "/json")[
                "State"
            ]
            if not state["Running"] and state["Pid"] == 0:
                break
            time.sleep(0.03)
        assert not state["Running"] and state["Pid"] == 0
        assert all(not Path("/proc/" + str(pid)).exists() for pid in engine.known_pids)
    finally:
        observer.request(
            "DELETE", "/containers/" + engine.name + "?force=true&v=true", timeout=10
        )
