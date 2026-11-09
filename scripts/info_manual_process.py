"""Fixed D7 subprocess guardian, independent of asyncio and TLS scheduling.

Uses D5's ownership witness, a private channel and an adopting subreaper.
Never accepts a command, path, host, duration, fixture or shell from dispatch.
The private --guardian entry is invoked only by run_process, with FD scalars.
"""

import ctypes
import json
import logging
import math
import os
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.info_delivery_process_guard import owns_process_group  # noqa: E402
from scripts.info_manual_contract import (  # noqa: E402
    LIMITS,
    OBSERVATION,
    PROCESS,
    build_report,
    exact,
    need,
    validate_observation,
    validate_proof,
)

POLL = 0.02
PACKET_CAP = 6144
FINAL_RESERVE = 0.5
TERM_RESERVE = 8
KILL_RESERVE = 6
CANCEL_GRACE = 50


def packet(fd, value):
    data = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    need(len(data) <= 4096)
    need(os.write(fd, data) == len(data))


def _worker(identity_fd, result_fd, origin):
    """One fixed child. All parent/control/status FDs are closed before entry."""
    import asyncio

    from scripts.info_manual_worker import PassiveTlsPort, make_session, observe

    logging.disable(logging.CRITICAL)
    data = b""
    while len(data) <= 1024:
        chunk = os.read(identity_fd, 1025 - len(data))
        if not chunk:
            break
        data += chunk
    os.close(identity_fd)
    header = json.loads(data)
    exact(header, {"nonce", "user", "device"})
    need(type(header["nonce"]) is str and len(header["nonce"]) == 64)
    need(type(header["user"]) is str and type(header["device"]) is str)
    port = PassiveTlsPort()
    session = make_session(header.pop("user"), header.pop("device"), port)

    async def run():
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        main = asyncio.current_task()
        cancellation = False

        def cancel():
            nonlocal cancellation
            if not cancellation:
                cancellation = True
                main.cancel()

        loop.add_signal_handler(signal.SIGUSR1, stop.set)
        loop.add_signal_handler(signal.SIGTERM, cancel)
        loop.add_signal_handler(signal.SIGINT, cancel)
        return await observe(session, port, origin=origin, stop=stop)

    report = asyncio.run(run())
    packet(result_fd, {"nonce": header["nonce"], "observation": report})
    os.close(result_fd)
    os._exit(0)


def _children():
    # /proc/.../children requires kernel features absent on some isolated
    # runners. PPid/Tgid are the same kernel ownership witness without that
    # optional file. Refuse an incoherent PID view, never signal a guessed PID.
    def status(path):
        return dict(
            line.split(":", 1) for line in path.read_text().splitlines() if ":" in line
        )

    current = status(Path("/proc/self/status"))
    need(int(current["Tgid"]) == os.getpid())
    need(len(current.get("NSpid", str(os.getpid())).split()) == 1)
    children = []
    visible = list(Path("/proc").iterdir())
    need(len(visible) <= 4096)
    for entry in visible:
        if not entry.name.isdecimal():
            continue
        try:
            child = status(entry / "status")
        except FileNotFoundError:
            continue  # A non-child may exit during the bounded kernel scan.
        if int(child["PPid"]) == os.getpid():
            need(int(child["Tgid"]) == int(entry.name))
            children.append(int(child["Tgid"]))
    need(len(children) <= 16 and all(p > 1 and p != os.getpid() for p in children))
    return children


def _guardian(control, status, identity, origin, *, worker=_worker):
    """Adopt/reap all descendants; parent EOF has its own shutdown policy."""
    signal.pthread_sigmask(signal.SIG_SETMASK, [])
    need(math.isfinite(origin) and 0 <= time.monotonic() - origin < 30)
    need(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL)
    libc = ctypes.CDLL(None, use_errno=True)
    flag = ctypes.c_int()
    need(libc.prctl(36, 1, 0, 0, 0) == 0)
    need(libc.prctl(37, ctypes.byref(flag), 0, 0, 0) == 0 and flag.value == 1)
    need(not _children())  # Prove this kernel's ownership view before any child/TLS.
    results, result_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(control)
        os.close(status)
        os.close(results)
        os.setpgid(0, 0)
        try:
            worker(identity, result_write, origin)
        except BaseException:
            os._exit(2)  # No free exception/trace is printed or relayed.
        os._exit(2)
    os.close(identity)
    os.close(result_write)
    os.setpgid(pid, pid)
    error = False

    def emit(value):
        nonlocal error
        try:
            packet(status, value)
        except OSError:
            # Loss of the observer must not disable adoption/reaping.
            error = True

    emit({"kind": "isolated", "worker": pid})
    selector = selectors.DefaultSelector()
    selector.register(control, selectors.EVENT_READ)
    selector.register(results, selectors.EVENT_READ)
    acknowledged = False
    reaped = 0
    worker_exit = None
    report = b""
    report_closed = False
    term_at = kill_at = None
    cleaned_at = None
    observation_end = origin + LIMITS["observation_ms"] / 1000
    global_end = origin + LIMITS["total_ms"] / 1000

    def send(sig, token):
        nonlocal error
        try:
            os.killpg(pid, sig)
            if sig == signal.SIGKILL:
                for child in _children():
                    try:
                        os.kill(child, sig)
                    except ProcessLookupError:
                        pass
        except ProcessLookupError:
            pass
        except (OSError, ValueError):
            error = True
        emit({"kind": token})

    try:
        while time.monotonic() < global_end - FINAL_RESERVE:
            now = time.monotonic()
            for key, _ in selector.select(
                min(POLL, max(0, global_end - now - FINAL_RESERVE))
            ):
                if key.fd == control:
                    token = os.read(control, 1)
                    if token == b"A" and not acknowledged:
                        acknowledged = True
                    elif token in (b"Q", b"T", b""):
                        if token == b"":
                            selector.unregister(control)
                        if term_at is None:
                            term_at = now
                            send(signal.SIGTERM, "term")
                            error = True
                    else:
                        error = True
                        if term_at is None:
                            term_at = now
                            send(signal.SIGTERM, "term")
                else:
                    chunk = os.read(results, 4097 - len(report))
                    report += chunk
                    if not chunk:
                        report_closed = True
                        selector.unregister(results)
                    if len(report) > 4096:
                        raise ValueError()
            # Keep the group leader/zombie until the parent verifies ownership.
            if acknowledged:
                no_children = False
                while True:
                    try:
                        child, code = os.waitpid(-1, os.WNOHANG)
                    except ChildProcessError:
                        no_children = True
                        break
                    if child == 0:
                        break
                    reaped += 1
                    need(reaped <= 16)
                    if child == pid:
                        worker_exit = code
                if no_children:
                    if not report_closed:
                        continue
                    group_absent = False
                    try:
                        os.killpg(pid, 0)
                    except ProcessLookupError:
                        group_absent = True
                    need(group_absent and not _children())
                    if report_closed and report:
                        emit({"kind": "report", "value": json.loads(report)})
                    emit(
                        {
                            "kind": "reaped",
                            "count": reaped,
                            "worker_ok": worker_exit == 0,
                            "group_empty": True,
                        }
                    )
                    os._exit(2 if error else 0)
                if worker_exit is not None and term_at is None:
                    # A remaining descendant is not an innocuous worker exit.
                    term_at = now
                    send(signal.SIGTERM, "term")
                    error = True
            if now >= observation_end and cleaned_at is None:
                cleaned_at = now
                send(signal.SIGUSR1, "observe_end")
            # Leave independent time for TERM, KILL, adoption and wait/reap.
            if now >= global_end - TERM_RESERVE and term_at is None:
                term_at = now
                send(signal.SIGTERM, "term")
                error = True
            if term_at is not None and now >= min(
                term_at + CANCEL_GRACE, global_end - KILL_RESERVE
            ):
                if kill_at is None:
                    kill_at = now
                    send(signal.SIGKILL, "kill")
                else:
                    # Newly adopted escaped-group descendants are still owned.
                    for child in _children():
                        try:
                            os.kill(child, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
    except BaseException:
        if term_at is None:
            try:
                send(signal.SIGTERM, "term")
            except OSError:
                pass
        try:
            send(signal.SIGKILL, "kill")
        except OSError:
            pass
        reap_end = min(global_end - 0.25, time.monotonic() + 5)
        while time.monotonic() < reap_end:
            try:
                for child in _children():
                    try:
                        os.kill(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child, _ = os.waitpid(-1, os.WNOHANG)
                if child:
                    reaped += 1
                else:
                    time.sleep(POLL)
            except ChildProcessError:
                emit(
                    {
                        "kind": "reaped",
                        "count": reaped,
                        "worker_ok": False,
                        "group_empty": True,
                    }
                )
                break
            except (OSError, ValueError):
                break
    # Never emit a cleanup/reap receipt without the kernel witnesses above.
    os._exit(2)


def run_process(proof, identity, *, clock=time.monotonic, cancelled=lambda: False):
    """Synchronous controller. Fixed command, minimal env, no stdout/stderr."""
    need(sys.platform == "linux" and signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL)
    validate_proof(proof)
    origin = clock()
    need(type(origin) in (int, float) and math.isfinite(origin) and origin >= 0)
    exact(identity, {"user", "device"})
    end = origin + LIMITS["total_ms"] / 1000
    nonce = secrets.token_hex(32)
    p, o = dict(PROCESS), dict(OBSERVATION)
    if cancelled():
        p["first_error"] = "cancelled"
        return build_report(proof, o, p)
    cr, cw = os.pipe()
    sr, sw = os.pipe()
    ir, iw = os.pipe()
    selector = selectors.DefaultSelector()
    process = None
    buffer = b""
    count = 0
    waiting = False
    cancel_sent = False
    worker_group = None
    try:
        previous = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM}
        )
        try:
            p["launch_attempted"] = True
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(Path(__file__).resolve()),
                    "--guardian",
                    str(cr),
                    str(sw),
                    str(ir),
                    repr(origin),
                ],
                cwd=ROOT,
                env={"LANG": "C.UTF-8"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                pass_fds=(cr, sw, ir),
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        for fd in (cr, sw, ir):
            os.close(fd)
        cr = sw = ir = None
        selector.register(sr, selectors.EVENT_READ)
        while clock() < end - 0.25:
            if cancelled() and not cancel_sent:
                cancel_sent = True
                os.write(cw, b"Q")
                p["first_error"] = "cancelled"
            if selector.select(min(POLL, max(0, end - clock() - 0.25))):
                chunk = os.read(sr, PACKET_CAP - len(buffer) + 1)
                buffer += chunk
                need(len(buffer) <= PACKET_CAP)
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    value = json.loads(raw)
                    count += 1
                    need(count <= 8 and type(value) is dict)
                    kind = value.get("kind")
                    if kind == "isolated":
                        exact(value, {"kind", "worker"})
                        need(not p["spawned"])
                        need(owns_process_group(process.pid, value["worker"]))
                        worker_group = value["worker"]
                        p["spawned"] = p["isolated"] = True
                        os.write(cw, b"A")
                        if cancelled() or cancel_sent:
                            if not cancel_sent:
                                os.write(cw, b"Q")
                                cancel_sent = True
                                p["first_error"] = "cancelled"
                        else:
                            payload = json.dumps(
                                {"nonce": nonce, **identity}, separators=(",", ":")
                            ).encode()
                            need(len(payload) <= 1024)
                            need(os.write(iw, payload) == len(payload))
                        os.close(iw)
                        iw = None
                    elif kind in {"term", "kill", "observe_end"}:
                        exact(value, {"kind"})
                        if kind != "observe_end":
                            p[kind + "_requested"] = True
                    elif kind == "report":
                        exact(value, {"kind", "value"})
                        need(not p["child_report_bound"])
                        exact(value["value"], {"nonce", "observation"})
                        need(secrets.compare_digest(value["value"]["nonce"], nonce))
                        o = validate_observation(value["value"]["observation"])
                        p["child_report_bound"] = True
                    elif kind == "reaped":
                        exact(value, {"kind", "count", "worker_ok", "group_empty"})
                        need(not p["group_empty"] and value["group_empty"] is True)
                        need(type(value["count"]) is int and 1 <= value["count"] <= 16)
                        need(type(value["worker_ok"]) is bool)
                        p["children_reaped"] = value["count"]
                        p["group_empty"] = True
                        waiting = value["worker_ok"]
                    else:
                        raise ValueError()
                if not chunk:
                    need(not buffer)
                    selector.unregister(sr)
                    break
            if process.poll() is not None and not selector.get_map():
                break
        # Only a real wait return attests the guardian, not poll/signal/JSON.
        exit_code = process.wait(timeout=max(0, end - clock()))
        p["guardian_waited"] = True
        p["exit_ok"] = exit_code == 0 and waiting
        if worker_group is not None:
            try:
                os.killpg(worker_group, 0)
                p["group_empty"] = False
            except ProcessLookupError:
                pass
        if not p["exit_ok"] and p["first_error"] == "none":
            p["first_error"] = "process"
    except BaseException:
        if p["first_error"] == "none":
            p["first_error"] = "process"
    finally:
        # EOF independently triggers the adopting guardian's TERM/KILL/reap.
        for fd in (cr, cw, sr, sw, ir, iw):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        selector.close()
        p["control_closed"] = True
        if process is not None and not p["guardian_waited"]:
            try:
                process.wait(timeout=max(0, min(5, end - clock())))
                p["guardian_waited"] = True
            except subprocess.TimeoutExpired:
                pass
        elapsed = int((clock() - origin) * 1000)
        p["elapsed_ms"] = max(0, min(LIMITS["total_ms"], elapsed))
        p["deadline_exceeded"] = elapsed >= LIMITS["total_ms"]
        if not 0 <= elapsed < LIMITS["total_ms"]:
            p["first_error"] = "clock" if elapsed < 0 else "timeout"
        if o["started"] and o["elapsed_ms"] > p["elapsed_ms"]:
            if p["first_error"] == "none":
                p["first_error"] = "provenance"
            o = dict(OBSERVATION)
    return build_report(proof, o, p)


if __name__ == "__main__":
    try:
        need(len(sys.argv) == 6 and sys.argv[1] == "--guardian")
        descriptors = [int(v) for v in sys.argv[2:5]]
        need(len(set(descriptors)) == 3 and all(2 < v < 1048576 for v in descriptors))
        need(all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in descriptors))
        need(os.getsid(0) == os.getpid())
        parent = Path("/proc") / str(os.getppid())
        command = (parent / "cmdline").read_bytes().split(b"\0")
        command = [value.decode() for value in command if value]
        need(len(command) == 3 and command[1] == "-I")
        caller = Path(command[2])
        if not caller.is_absolute():
            caller = (parent / "cwd").resolve() / caller
        need(caller.resolve() == ROOT / "scripts/launch_info_manual.py")
        _guardian(*descriptors, float(sys.argv[5]))
    except BaseException:
        os._exit(2)
