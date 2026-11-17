"""Invented register words, ephemeral FIFO only; never print private payloads."""

import asyncio
import json
import logging
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from custom_components.hoben import shadow_data_updated as shadow
from custom_components.hoben.data_updated_parser import parse_data_updated
from custom_components.hoben.modbus import encode_mbap
from custom_components.hoben.transport import TransportEOF
from tests.test_data_updated_silence import pump
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory

FLAG = "HOBEN_PRIVATE_DATAUPDATED_DEBUG"
FIFO = "HOBEN_PRIVATE_DATAUPDATED_FIFO"
LOGGER = "custom_components.hoben.shadow_data_updated"


def notification(words=tuple(range(20)), *, tid=65535, function=4, unit=1):
    body = b"".join(word.to_bytes(2, "big") for word in words)
    return b"\x1bSECR" + encode_mbap(tid, unit, bytes([function, len(body)]) + body)


@pytest.fixture
def private_fifo(tmp_path, monkeypatch):
    if not hasattr(os, "mkfifo"):
        pytest.skip("Private FIFO requires a POSIX host")
    path = tmp_path / "private.pipe"
    os.mkfifo(path, 0o600)
    reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv(FIFO, str(path))
    # Only synthetic tests simulate a local owner; real CI must refuse opt-in.
    for key in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(key, raising=False)

    def read():
        try:
            return os.read(reader, 65536).decode("ascii").splitlines()
        except BlockingIOError:
            return []

    try:
        yield SimpleNamespace(path=path, reader=reader, read=read)
    finally:
        os.close(reader)


def fields(line):
    return dict(field.split("=", 1) for field in line.split()[1:])


def test_explicit_ha_debug_logs_twenty_pairs_without_env_or_fifo(caplog, monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv(FIFO, raising=False)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    for index in range(20):
        words = (0, 65535, *range(49123 + index, 49141 + index))
        shadow.observe_data_updated(
            parse_data_updated(notification(words)), generation=7, index=index + 1
        )
        records = [r for r in caplog.records if r.name == LOGGER]
        assert len(records) == index + 1  # One block per notification, not 20 records.
        record = records[-1]
        event = record.hoben_shadow
        assert "candidate_registers" in event, (
            "HA DEBUG lacks the candidate register block"
        )
        rows = event["candidate_registers"]
        assert len(rows) == 20
        assert [row["index"] for row in rows] == list(range(20))
        assert [row["register_candidate"] for row in rows] == list(range(1024, 1044))
        assert [row["raw_value"] for row in rows] == list(words)
        assert rows[0]["name"] == "erarMode_ConsigneMarchArret"
        assert rows[-1]["name"] == "erarTemperatureRFConv"
        assert event["generation"] == 7 and event["index"] == index + 1
        assert event["mapping"] == "unverified" and event["simulated"]
        assert event["source"] == "DataUpdated" and event["proposals"] == 0
        message = record.getMessage()
        assert message.startswith("Hoben SHADOW SIMULATION")
        assert "source=DataUpdated" in message
        assert "mapping=unverified" in message and "simulated=true" in message
        assert json.loads(message.split("candidate_registers=", 1)[1]) == rows
        assert record.levelno == logging.DEBUG and record.exc_info is None
        assert len(message.encode("utf8")) <= 4096
        assert "SECR" not in message and "entity_id" not in message


def test_twenty_notifications_emit_twenty_private_candidate_pairs_each(
    private_fifo, caplog
):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.NOTSET, logger=LOGGER)
    for number in range(20):
        words = (0, 65535, *range(49123 + number, 49141 + number))
        result = parse_data_updated(notification(words))
        shadow.observe_data_updated(result, generation=2, index=number + 1)
        lines = private_fifo.read()
        assert len(lines) == 20, "private candidate register journal is missing"
        rows = [fields(line) for line in lines]
        assert all(line.startswith("DEBUG ") for line in lines)
        assert [int(row["register_candidate"]) for row in rows] == list(
            range(1024, 1044)
        )
        assert [int(row["index"]) for row in rows] == list(range(20))
        assert [int(row["raw_value"]) for row in rows] == list(words)
        assert all(row["mapping"] == "unverified" for row in rows)
        assert all(row["simulated"] == "true" for row in rows)
        assert all(row["source"] == "DataUpdated" for row in rows)
        assert all(row["generation"] == "2" for row in rows)
        assert all(row["delivery"] == str(number + 1) for row in rows)
        assert rows[0]["name"] == "erarMode_ConsigneMarchArret"
        assert rows[-1]["name"] == "erarTemperatureRFConv"
        assert "raw_value" not in caplog.text
        assert "register_candidate" not in caplog.text
        assert "49123" not in caplog.text
        assert "SECR" not in "".join(lines) + caplog.text
        assert "49123" not in json.dumps(result.safe_report()) + repr(result)
        assert shadow.preview_data_updated(result).proposals == ()


@pytest.mark.parametrize("switch", [None, "0", "true", "DEBUG", ""])
def test_ha_debug_does_not_enable_the_independent_fifo(
    private_fifo, caplog, monkeypatch, switch
):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    if switch is None:
        monkeypatch.delenv(FLAG)
    else:
        monkeypatch.setenv(FLAG, switch)
    shadow.observe_data_updated(
        parse_data_updated(notification()), generation=1, index=1
    )
    assert private_fifo.read() == []
    assert "shadow_mapping_unproven" in caplog.text
    (record,) = [r for r in caplog.records if r.name == LOGGER]
    assert len(record.hoben_shadow["candidate_registers"]) == 20
    assert record.levelno == logging.DEBUG


@pytest.mark.parametrize("ci", ["CI", "GITHUB_ACTIONS"])
def test_ci_refuses_even_an_explicit_private_sink(private_fifo, monkeypatch, ci):
    monkeypatch.setenv(ci, "true")
    shadow.observe_data_updated(
        parse_data_updated(notification()), generation=1, index=1
    )
    assert private_fifo.read() == []


@pytest.mark.parametrize(
    "delivery",
    [
        notification(tid=0),
        notification(tid=65520),
        notification(function=3),
        notification(unit=2),
        notification(tuple(range(19))),
        notification(tuple(range(21))),
        notification()[:-1],
        notification() + b"\x0a",
        b"\x1b",
        b"\x1bSECR\xff\xff\x00\x00\x00\x03\x01\x84\x02",
    ],
)
def test_other_shapes_never_receive_a_candidate_address(private_fifo, delivery, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    shadow.observe_data_updated(parse_data_updated(delivery), generation=1, index=1)
    assert private_fifo.read() == []
    assert "raw_value" not in caplog.text
    assert "register_candidate" not in caplog.text
    assert all(
        "candidate_registers" not in r.hoben_shadow
        for r in caplog.records
        if r.name == LOGGER
    )


@pytest.mark.parametrize("word", [-1, 65536, True, "PRIVATE"])
def test_forged_invalid_words_are_not_formatted(private_fifo, word, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    parsed = parse_data_updated(notification())
    response = replace(parsed.response, registers=(word, *range(19)))
    shadow.observe_data_updated(
        replace(parsed, response=response), generation=1, index=1
    )
    assert private_fifo.read() == []
    assert "raw_value" not in caplog.text and "PRIVATE" not in caplog.text


@pytest.mark.parametrize(
    "kind", ["file", "directory", "symlink", "permissive", "linked"]
)
def test_unsafe_paths_are_never_written(private_fifo, monkeypatch, tmp_path, kind):
    path = tmp_path / "unsafe"
    if kind == "file":
        path.write_text("unchanged")
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        path.symlink_to(private_fifo.path)
    elif kind == "permissive":
        private_fifo.path.chmod(0o640)
        path = private_fifo.path
    else:
        os.link(private_fifo.path, path)
    monkeypatch.setenv(FIFO, str(path))
    shadow.observe_data_updated(
        parse_data_updated(notification()), generation=1, index=1
    )
    assert private_fifo.read() == []
    if kind == "file":
        assert path.read_text() == "unchanged"


def test_disable_and_new_generation_keep_no_old_candidates(private_fifo, monkeypatch):
    result = parse_data_updated(notification())
    shadow.observe_data_updated(result, generation=1, index=1)
    assert len(private_fifo.read()) == 20
    monkeypatch.delenv(FLAG)
    for _ in range(20):
        shadow.observe_data_updated(result, generation=1, index=2)
    assert private_fifo.read() == []
    monkeypatch.setenv(FLAG, "1")
    shadow.observe_data_updated(result, generation=2, index=1)
    rows = [fields(line) for line in private_fifo.read()]
    assert len(rows) == 20
    assert all(row["generation"] == "2" and row["delivery"] == "1" for row in rows)


def test_no_reader_and_full_pipe_do_not_block_or_leak(monkeypatch, tmp_path, caplog):
    path = tmp_path / "private.pipe"
    os.mkfifo(path, 0o600)
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv(FIFO, str(path))
    for key in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(key, raising=False)
    result = parse_data_updated(notification())
    # Opening a FIFO with no reader must return without waiting.
    shadow.observe_data_updated(result, generation=1, index=1)
    reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        # Fill the bounded kernel pipe. Further observations are dropped, not queued.
        for index in range(1000):
            shadow.observe_data_updated(result, generation=1, index=index + 1)
        data = os.read(reader, 65536)
        assert data, "private writer did not connect"
        assert data.count(b"\n") % 20 == 0  # Whole notifications, no partial batch.
        assert "raw_value" not in caplog.text
    finally:
        os.close(reader)
    shadow.observe_data_updated(result, generation=1, index=1001)


def test_private_os_failure_never_becomes_a_public_exception(
    private_fifo, caplog, monkeypatch
):
    def fail(*args):
        raise OSError("PRIVATE_JOURNAL_ERROR")

    monkeypatch.setattr(os, "write", fail)
    shadow.observe_data_updated(
        parse_data_updated(notification()), generation=1, index=1
    )
    assert private_fifo.read() == []
    assert "PRIVATE_JOURNAL_ERROR" not in caplog.text


def test_foreign_fifo_and_unknown_context_are_refused(private_fifo, monkeypatch):
    result = parse_data_updated(notification())
    owner = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    shadow.observe_data_updated(result, generation=1, index=1)
    assert private_fifo.read() == []
    monkeypatch.setattr(os, "geteuid", lambda: owner)
    shadow.observe_data_updated(result, generation=True, index=1)
    shadow.observe_data_updated(result, generation=1, index="PRIVATE")
    assert private_fifo.read() == []


def test_path_replacement_cannot_redirect_numeric_writes(private_fifo, monkeypatch):
    opening = os.open

    def replace_path(path, flags):
        if str(path).startswith("/proc/self/fd/"):
            private_fifo.path.unlink()
            private_fifo.path.write_text("untouched")
        return opening(path, flags)

    monkeypatch.setattr(os, "open", replace_path)
    shadow.observe_data_updated(
        parse_data_updated(notification()), generation=1, index=1
    )
    assert private_fifo.read() == []
    assert private_fifo.path.read_text() == "untouched"


def test_atomic_limit_failure_closes_every_descriptor(private_fifo, monkeypatch):
    opening, closing = os.open, os.close
    outstanding = set()

    def track_open(*args):
        descriptor = opening(*args)
        outstanding.add(descriptor)
        return descriptor

    def track_close(descriptor):
        outstanding.discard(descriptor)
        return closing(descriptor)

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", track_close)
    monkeypatch.setattr(os, "fpathconf", lambda *args: 1)
    shadow.observe_data_updated(
        parse_data_updated(notification()), generation=1, index=1
    )
    assert outstanding == set()
    assert private_fifo.read() == []


def test_maximum_context_still_fits_one_atomic_twenty_line_batch(private_fifo):
    shadow.observe_data_updated(
        parse_data_updated(notification((65535,) * 20)),
        generation=2147483647,
        index=65535,
    )
    assert len(private_fifo.read()) == 20


def test_real_rx_generations_and_cleanup_never_replay_private_candidates(private_fifo):
    async def run():
        factory, backoff = Factory(), Backoff()
        life = factory.lifecycle(
            recover_acquisition=True, ha_reconnect=True, sleep=backoff
        )
        try:
            await life.connect()
            old = factory.streams[0]
            old.queue.put_nowait(notification())
            await pump()
            assert {fields(line)["generation"] for line in private_fifo.read()} == {"1"}
            assert [payload[0] for payload in old.writes] == [3]
            old.queue.put_nowait(TransportEOF())
            await backoff.entered.get()
            old.queue.put_nowait(notification())
            backoff.release.put_nowait(None)
            await life.wait_connected()
            fresh = factory.streams[1]
            fresh.queue.put_nowait(notification())
            await pump()
            lines = private_fifo.read()
            assert len(lines) == 20
            assert all(fields(line)["generation"] == "2" for line in lines)
            assert old.queue.qsize() == 1 and old.close_count == 1
            assert [payload[0] for payload in fresh.writes] == [3]
            assert life.witness.verified_read_generation is None
        finally:
            await life.close()
            factory.assert_clean()
        fresh.queue.put_nowait(notification())
        await pump()
        assert private_fifo.read() == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "level",
    [logging.NOTSET, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL, 5],
)
def test_only_explicit_debug_enables_ha_numbers(caplog, monkeypatch, level):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv(FIFO, raising=False)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(level, logger=LOGGER)
    for index in range(20):
        shadow.observe_data_updated(
            parse_data_updated(notification()), generation=1, index=index + 1
        )
    assert not [r for r in caplog.records if r.name == LOGGER]
    assert "raw_value" not in caplog.text and "register_candidate" not in caplog.text


def test_info_disable_and_new_generation_keep_no_debug_backlog(caplog, monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv(FIFO, raising=False)
    result = parse_data_updated(notification())
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    shadow.observe_data_updated(result, generation=1, index=1)
    caplog.set_level(logging.INFO, logger=LOGGER)
    for index in range(20):
        shadow.observe_data_updated(result, generation=1, index=index + 2)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    shadow.observe_data_updated(result, generation=2, index=1)
    records = [r for r in caplog.records if r.name == LOGGER]
    assert len(records) == 2
    assert [r.hoben_shadow["generation"] for r in records] == [1, 2]
    assert [r.hoben_shadow["index"] for r in records] == [1, 1]
    assert all(len(r.hoben_shadow["candidate_registers"]) == 20 for r in records)
    assert records[0].hoben_shadow is not records[1].hoben_shadow
    monkeypatch.setattr(shadow._LOGGER, "disabled", True)
    shadow.observe_data_updated(result, generation=2, index=2)
    assert len([r for r in caplog.records if r.name == LOGGER]) == 2


def test_debug_maximum_context_is_bounded_and_unknown_context_is_categorical(
    caplog, monkeypatch
):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv(FIFO, raising=False)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    result = parse_data_updated(notification((65535,) * 20))
    shadow.observe_data_updated(result, generation=2147483647, index=65535)
    (record,) = [r for r in caplog.records if r.name == LOGGER]
    assert len(record.hoben_shadow["candidate_registers"]) == 20
    assert len(record.getMessage().encode("ascii")) <= 4096
    caplog.clear()
    shadow.observe_data_updated(result, generation=True, index=1)
    (record,) = [r for r in caplog.records if r.name == LOGGER]
    assert "candidate_registers" not in record.hoben_shadow
    assert "raw_value" not in record.getMessage()
