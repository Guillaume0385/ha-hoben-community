"""External C2a supervisor. Fixed local engine, no CLI, secrets or live network.

Only reviewed offline fixtures are selectable. Image preparation is separate;
this API never downloads/installs dependencies or falls back to host execution.
The namespace guardian remains armed if this host observer disappears.
"""

import http.client
import io
import json
import re
import shutil
import socket
import tarfile
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from scripts.ha_live_proof import (
    MEMORY_BYTES,
    PIDS,
    PROCESS_MS,
    USEFUL_MS,
    build_report,
    empty_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


class OfflineCase(StrEnum):
    HEALTHY = "healthy"
    CLOSE_CLIENT = "close_client"
    EOF = "eof"
    TLS = "tls"
    READ_TIMEOUT = "read_timeout"
    MEMORY = "memory"
    PROCESSES = "processes"
    RESISTANT = "resistant"
    FORGED = "forged"


@dataclass(frozen=True)
class Limits:
    """Tests may tighten ceilings; neither API nor input can enlarge them."""

    memory_bytes: int = MEMORY_BYTES
    pids: int = PIDS
    useful_ms: int = USEFUL_MS
    process_ms: int = PROCESS_MS

    def __post_init__(self):
        for name, ceiling in (
            ("memory_bytes", MEMORY_BYTES),
            ("pids", PIDS),
            ("useful_ms", USEFUL_MS),
            ("process_ms", PROCESS_MS),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError("invalid sandbox limit")
        if self.useful_ms >= self.process_ms:
            raise ValueError("cleanup reserve required")


class Unavailable(Exception):
    """Never include engine errors, logs, mounts, env or untrusted response data."""


class CancelledBeforeStart(Exception):
    """No worker may start after an already observed cancellation."""


class SourceBundle:
    """Public code snapshot only; never relax checkout permissions or mount .git."""

    def __init__(self):
        self.folder = Path(tempfile.mkdtemp(prefix="hoben-c2a-source-"))
        try:
            paths = list((ROOT / "custom_components/hoben").glob("*.py"))
            paths += [ROOT / "custom_components/hoben/manifest.json"]
            paths += [
                ROOT / "scripts" / name
                for name in (
                    "ha_session_guard.py",
                    "ha_live_proof.py",
                    "ha_session_evidence.py",
                    "ha_session_observer.py",
                )
            ]
            paths += [ROOT / "tests/fixtures/ha_session_worker.py"]
            for path in paths:
                if (
                    any(parent.is_symlink() for parent in path.parents)
                    or path.is_symlink()
                    or not path.is_file()
                ):
                    raise Unavailable()
                target = self.folder / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
                target.chmod(0o444)
            for directory in sorted(self.folder.rglob("*"), reverse=True):
                if directory.is_dir():
                    directory.chmod(0o555)
            self.folder.chmod(0o555)
        except Exception:
            self.close()
            raise

    def close(self):
        for directory in [self.folder, *self.folder.rglob("*")]:
            if directory.is_dir():
                directory.chmod(0o700)
        shutil.rmtree(self.folder)


class LocalConnection(http.client.HTTPConnection):
    def __init__(self, timeout):
        super().__init__("localhost", timeout=timeout)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


class Engine:
    def request(self, method, path, body=None, *, binary=False, timeout=1):
        connection = LocalConnection(timeout)
        try:
            payload = (
                body
                if isinstance(body, bytes)
                else None
                if body is None
                else json.dumps(body).encode()
            )
            connection.request(
                method,
                "/v1.41" + path,
                body=payload,
                headers={
                    "Content-Type": "application/x-tar"
                    if isinstance(body, bytes)
                    else "application/json"
                },
            )
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise Unavailable("http_" + str(response.status))
            data = response.read(65537)
            if len(data) > 65536:
                raise Unavailable()
            return data if binary else json.loads(data) if data else None
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise Unavailable(type(error).__name__) from None
        finally:
            connection.close()


class DeadlineEngine:
    """Every engine operation consumes the original external deadline."""

    def __init__(self, engine, deadline, clock):
        self.engine, self.deadline, self.clock = engine, deadline, clock

    def request(self, method, path, body=None, **kwargs):
        remaining = self.deadline - self.clock()
        if remaining <= 0.01:
            raise Unavailable()
        return self.engine.request(
            method,
            path,
            body,
            timeout=min(
                10 if path.startswith("/containers/create") else 2, remaining / 2
            ),
            **kwargs,
        )


def verified_config(container, limits, image_id):
    """Check effective configuration before start, including privilege isolation."""
    h = container["HostConfig"]
    return (
        container["Image"] == image_id
        and not container["State"]["Running"]
        and h["NetworkMode"] == "none"
        and h["ReadonlyRootfs"] is True
        and h["Privileged"] is False
        and h["PidMode"] == ""
        and h["CgroupnsMode"] == "private"
        and h["Memory"] == limits.memory_bytes
        and h["MemorySwap"] == limits.memory_bytes
        and h["PidsLimit"] == limits.pids
        and h["CapDrop"] == ["ALL"]
        and set(h["CapAdd"]) == {"SETUID", "SETGID", "KILL"}
        and h["SecurityOpt"] == ["no-new-privileges"]
        and h["LogConfig"]["Type"] == "none"
    )


def read_receipt(engine, name):
    blob = engine.request(
        "GET",
        "/containers/" + name + "/archive?path=/run/hoben/receipt.json",
        binary=True,
    )
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
        members = archive.getmembers()
        if (
            len(members) != 1
            or not members[0].isfile()
            or members[0].name != "receipt.json"
            or members[0].size > 8192
        ):
            raise Unavailable()
        raw = archive.extractfile(members[0]).read(8193)
    data = json.loads(raw)
    if json.dumps(data, separators=(",", ":"), allow_nan=False).encode() != raw:
        raise Unavailable()
    if type(data) is not dict or set(data) != {
        "started",
        "reason",
        "oom_killed",
        "pids_limited",
        "evidence",
    }:
        raise Unavailable()
    return data


def supervise(
    case,
    image_id,
    provenance,
    *,
    limits=Limits(),
    cancelled=lambda: False,
    engine=None,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """Run one fixed offline fixture and return validated, unadmitted evidence.

    No environment is inherited by the worker. A missing engine, image, cgroup
    metric or configuration proof refuses before the HA worker starts.
    """
    if (
        type(case) is not OfflineCase
        or type(limits) is not Limits
        or type(image_id) is not str
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
    ):
        raise ValueError("invalid offline sandbox request")
    engine = Engine() if engine is None else engine
    start = deadline = None
    reserve = min(10, limits.process_ms / 3000)
    name = "hoben-c2a-offline-" + uuid.uuid4().hex
    receipt = {
        "started": False,
        "reason": "unavailable",
        **asdict(limits),
        "elapsed_ms": 0,
        "oom_killed": False,
        "pids_limited": False,
        "reaped": False,
        "network": "none",
    }
    evidence = empty_evidence()
    provenance = dict(provenance)
    build_report(provenance, receipt, evidence)
    created, attempted_start, stopped = False, False, False
    cancel_sent = False
    bundle = None
    try:
        info = engine.request("GET", "/info")
        if not (
            info.get("CgroupVersion") == "2"
            and info.get("MemoryLimit") is True
            and info.get("SwapLimit") is True
            and info.get("PidsLimit") is True
        ):
            raise Unavailable()
        image = engine.request("GET", "/images/" + quote(image_id, safe=":") + "/json")
        if image.get("Id") != image_id:
            raise Unavailable()
        bundle = SourceBundle()
        mounts = [
            {
                "Type": "bind",
                "Source": str(bundle.folder),
                "Target": "/source",
                "ReadOnly": True,
            }
        ]
        mounts.append(
            {
                "Type": "volume",
                "Target": "/run/hoben",
                "ReadOnly": False,
                "VolumeOptions": {"NoCopy": True},
            }
        )
        config = {
            "Image": image_id,
            "Entrypoint": ["python", "-I", "/source/scripts/ha_session_guard.py"],
            "Cmd": [
                case.value,
                json.dumps(asdict(limits), separators=(",", ":")),
            ],
            "Env": [],
            "WorkingDir": "/source",
            "NetworkDisabled": True,
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "PidMode": "",
                "CgroupnsMode": "private",
                "Memory": limits.memory_bytes,
                "MemorySwap": limits.memory_bytes,
                "PidsLimit": limits.pids,
                "CapDrop": ["ALL"],
                "CapAdd": ["SETUID", "SETGID", "KILL"],
                "SecurityOpt": ["no-new-privileges"],
                "LogConfig": {"Type": "none"},
                "Mounts": mounts,
                "Tmpfs": {
                    "/tmp": "rw,noexec,nosuid,size=32m,mode=1777",
                },
            },
        }
        engine.request("POST", "/containers/create?name=" + name, config, timeout=45)
        created = True
        current = engine.request("GET", "/containers/" + name + "/json")
        if not verified_config(current, limits, image_id):
            raise Unavailable()
        if cancelled():
            raise CancelledBeforeStart()
        # Prepare a stopped, secret-free container first. Arm before start.
        start = clock()
        deadline = start + limits.process_ms / 1000
        engine = DeadlineEngine(engine, deadline, clock)
        payload = str(int(deadline * 1e9)).encode()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as stream:
            item = tarfile.TarInfo("deadline")
            item.mode, item.size = 0o600, len(payload)
            stream.addfile(item, io.BytesIO(payload))
        engine.request(
            "PUT",
            "/containers/" + name + "/archive?path=/run/hoben",
            archive.getvalue(),
        )
        attempted_start = True
        engine.request("POST", "/containers/" + name + "/start")
        receipt["reason"] = "worker_failure"
        ready_data = None
        while clock() < deadline - reserve:
            current = engine.request("GET", "/containers/" + name + "/json")
            if not current["State"]["Running"] and current["State"]["Pid"] == 0:
                stopped = True
                break
            if ready_data is None:
                try:
                    ready_data = read_receipt(engine, name)
                except Unavailable as error:
                    if str(error) != "http_404":
                        raise
                if ready_data is not None:
                    engine.request(
                        "POST", "/containers/" + name + "/kill?signal=SIGUSR2"
                    )
            if cancelled() and not cancel_sent:
                cancel_sent = True
                engine.request("POST", "/containers/" + name + "/kill?signal=SIGUSR1")
            sleep(min(0.05, max(0, deadline - reserve - clock())))
        if not stopped:
            receipt["reason"] = "cancelled" if cancel_sent else "timeout"
        else:
            state = current["State"]
            if state.get("OOMKilled") is True:
                receipt["oom_killed"], receipt["reason"] = True, "memory"
            else:
                data = (
                    ready_data if ready_data is not None else read_receipt(engine, name)
                )
                for key in ("started", "reason", "oom_killed", "pids_limited"):
                    receipt[key] = data[key]
                evidence = data["evidence"]
                if (
                    cancel_sent
                    and not receipt["oom_killed"]
                    and not receipt["pids_limited"]
                ):
                    receipt["reason"] = "cancelled"
    except (Exception, KeyboardInterrupt) as error:
        evidence = empty_evidence()
        receipt["reason"] = (
            "cancelled"
            if cancel_sent or isinstance(error, CancelledBeforeStart)
            else "worker_failure"
            if attempted_start
            else "unavailable"
        )
    finally:
        if created:
            try:
                if attempted_start and not stopped:
                    engine.request(
                        "POST", "/containers/" + name + "/kill?signal=SIGKILL"
                    )
                current = engine.request("GET", "/containers/" + name + "/json")
                stopped = (
                    not current["State"]["Running"] and current["State"]["Pid"] == 0
                )
                receipt["reaped"] = stopped
            except Exception:
                receipt["reaped"] = False
            try:
                engine.request("DELETE", "/containers/" + name + "?force=true&v=true")
            except Exception:
                receipt["reaped"] = False
        if bundle is not None:
            bundle.close()
        receipt["elapsed_ms"] = (
            0 if start is None else max(0, int((clock() - start) * 1000))
        )
        if (
            deadline is not None
            and clock() > deadline
            and not receipt["oom_killed"]
            and not receipt["pids_limited"]
        ):
            receipt["reason"] = "timeout"
    try:
        return build_report(provenance, receipt, evidence)
    except Exception:
        receipt.update(reason="worker_failure", oom_killed=False, pids_limited=False)
        return build_report(provenance, receipt, empty_evidence())
