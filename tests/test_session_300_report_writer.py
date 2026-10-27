"""Exercise the collector's actual private report writer, without live access."""

import errno
import json
import os
import stat

import pytest

from scripts import run_session_300 as collector
from tests.test_session_300_probe import PROOF, Clock, Lifecycle


@pytest.fixture
def report():
    clock = Clock()
    budget = collector.Session300(clock=clock)
    return collector.asyncio.run(
        collector.observe(
            Lifecycle(budget), budget, PROOF, clock=clock, sleep=clock.sleep
        )
    )


@pytest.fixture
def export_directory(tmp_path):
    directory = tmp_path / "exports"
    directory.mkdir(mode=0o700)
    return directory


def test_writer_creates_readable_json_with_exact_private_mode(export_directory, report):
    file = export_directory / "report.json"
    # Even a restrictive inherited umask must not leave an unreadable report.
    previous = os.umask(0o777)
    try:
        collector.write_report(file, report)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert stat.S_IMODE(export_directory.stat().st_mode) == 0o700
    assert json.loads(file.read_text(encoding="utf-8")) == report


@pytest.mark.parametrize("existing", ["file", "symlink", "dangling_symlink"])
def test_writer_refuses_existing_paths_without_modifying_them(
    export_directory, report, existing
):
    file = export_directory / "report.json"
    target = export_directory / "target"
    if existing == "file":
        file.write_text("existing", encoding="utf-8")
    else:
        if existing == "symlink":
            target.write_text("existing", encoding="utf-8")
        file.symlink_to(target)
    with pytest.raises(FileExistsError):
        collector.write_report(file, report)
    if existing == "file":
        assert file.read_text(encoding="utf-8") == "existing"
    else:
        assert file.is_symlink() and file.readlink() == target
        if existing == "symlink":
            assert target.read_text(encoding="utf-8") == "existing"
        else:
            assert not target.exists()


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_failed_serialization_closes_descriptor_and_removes_partial_file(
    export_directory, report, monkeypatch, error
):
    descriptors = []

    def fail_dump(value, out):
        assert value is report
        descriptors.append(out.fileno())
        out.write('{"partial":')
        out.flush()
        raise error()

    monkeypatch.setattr(collector.json, "dump", fail_dump)
    file = export_directory / "report.json"
    with pytest.raises(error):
        collector.write_report(file, report)
    assert not file.exists() and not list(export_directory.iterdir())
    with pytest.raises(OSError) as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF


def test_failed_stream_construction_closes_untransferred_descriptor(
    export_directory, report, monkeypatch
):
    descriptors = []

    def fail_fdopen(descriptor, *args, **kwargs):
        descriptors.append(descriptor)
        raise OSError()

    monkeypatch.setattr(collector.os, "fdopen", fail_fdopen)
    file = export_directory / "report.json"
    with pytest.raises(OSError):
        collector.write_report(file, report)
    assert not file.exists()
    with pytest.raises(OSError) as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF


def test_main_reaches_actual_writer_and_exports_report_offline(
    tmp_path, report, monkeypatch, capsys
):
    # Only admission and observation are doubles: main creates the real directory
    # and invokes the real writer, which catches unsupported file APIs as well.
    lifecycle = object()

    async def observe(actual, budget, proof):
        assert actual is lifecycle and proof == PROOF
        return report

    monkeypatch.setattr(collector, "context_proof", lambda env: PROOF)
    monkeypatch.setattr(
        collector.subprocess, "check_output", lambda *args, **kwargs: b"a" * 40
    )
    monkeypatch.setattr(collector, "V4Lifecycle", lambda **kwargs: lifecycle)
    monkeypatch.setattr(collector, "observe", observe)
    monkeypatch.setattr(collector.sys, "argv", ["run_session_300.py"])
    monkeypatch.setenv("HOBEN_USER_GUID", "synthetic-identity")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    assert collector.main() == 0
    directory = tmp_path / "hoben-session-300-exports"
    file = directory / "report.json"
    assert json.loads(file.read_text(encoding="utf-8")) == report
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert "HOBEN_USER_GUID" not in collector.os.environ
    assert capsys.readouterr() == ("", "")
