"""#219-S: synthetic-only shadow guard, privacy and unchanged RX ownership."""

import asyncio
import importlib
import logging
from dataclasses import FrozenInstanceError

import pytest

from custom_components.hoben import shadow_data_updated as shadow
from custom_components.hoben.data_updated_parser import parse_data_updated
from custom_components.hoben.transport import TransportEOF
from custom_components.hoben.v4_state import decode_v4_snapshot
from tests.test_data_updated_parser_219 import candidate
from tests.test_data_updated_silence import pump
from tests.test_v4_lifecycle import Backoff
from tests.test_v4_persistent import Factory
from tests.test_v4_state import snapshot

LOGGER = "custom_components.hoben.shadow_data_updated"


def notification(value=56026):
    """Twenty invented words, never a claim that word zero is register 1024."""
    return candidate(b"\x04\x28" + value.to_bytes(2, "big") * 20)


def events(caplog):
    return [
        r.hoben_shadow
        for r in caplog.records
        if r.name == LOGGER and hasattr(r, "hoben_shadow")
    ]


@pytest.mark.parametrize("value", range(20))
def test_twenty_valid_notifications_do_not_prove_a_mapping(value):
    result = parse_data_updated(notification(value))
    assert result.safe_report()["status"] == "parsed"
    assert result.safe_report()["value_count"] == 20
    plan = shadow.preview_data_updated(result)
    assert plan.reason == "shadow_mapping_unproven"
    assert plan.proposals == () and plan.simulated
    assert plan.mapping == "unverified"


def test_a_proven_v4_mapping_does_not_establish_notification_identity():
    raw = snapshot(**{"1031": 213, "1032": 190})
    assert decode_v4_snapshot(raw).ambient_temperature == 21.3
    body = b"".join(word.to_bytes(2, "big") for word in raw.registers)
    result = parse_data_updated(candidate(b"\x04\x28" + body))
    assert result.response.registers == raw.registers  # Synthetic equality only.
    assert shadow.preview_data_updated(result).proposals == ()
    with pytest.raises(FrozenInstanceError):
        shadow.preview_data_updated(result).proposals = (raw,)


@pytest.mark.parametrize(
    "delivery",
    [
        b"\x1b",
        notification()[:10],
        notification()[:-1],
        notification() + b"\x0a",
        b"\x1bSECR\xff\xff\x00\x00\xff\xff",
        candidate(b"\x06\x12\x34\xbe\xef"),
        candidate(b"\x84\x02"),
    ],
)
def test_invalid_unsupported_and_exception_pdus_do_not_propose_states(delivery):
    assert shadow.preview_data_updated(parse_data_updated(delivery)) is None


def test_root_debug_cannot_enable_shadow_or_expose_values(caplog):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.NOTSET, logger=LOGGER)
    for index in range(20):
        shadow.observe_data_updated(
            parse_data_updated(notification()), generation=1, index=index + 1
        )
    assert events(caplog) == []
    assert "SHADOW SIMULATION" not in caplog.text


def test_explicit_debug_emits_only_closed_unproven_decisions(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    for index in range(20):
        shadow.observe_data_updated(
            parse_data_updated(notification()), generation=2, index=index + 1
        )
    assert len(events(caplog)) == 20
    for event in events(caplog):
        assert set(event) == {
            "event",
            "simulated",
            "mapping",
            "source",
            "proposals",
            "generation",
            "index",
        }
        assert event["event"] == "shadow_mapping_unproven"
        assert event["proposals"] == 0 and event["mapping"] == "unverified"
    for private in ("SECR", "56026", "dada", "candidate_value", "actual_state"):
        assert private not in caplog.text
    assert all(
        r.exc_info is None and len(r.getMessage()) < 256
        for r in caplog.records
        if r.name == LOGGER
    )


def test_stop_reload_and_disabled_logger_do_not_leave_an_observer(caplog, monkeypatch):
    result = parse_data_updated(notification())
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    shadow.observe_data_updated(result, generation=1, index=1)
    assert len(events(caplog)) == 1
    caplog.set_level(logging.NOTSET, logger=LOGGER)
    importlib.reload(shadow)
    for _ in range(20):
        shadow.observe_data_updated(result, generation=2, index=1)
    assert len(events(caplog)) == 1
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setattr(shadow._LOGGER, "disabled", True)
    shadow.observe_data_updated(result, generation=2, index=2)
    assert len(events(caplog)) == 1


def test_logger_failure_and_private_context_cannot_affect_reception(
    caplog, monkeypatch
):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    class Private:
        def __str__(self):
            raise AssertionError("private text must never be inspected")

    result = parse_data_updated(notification())
    shadow.observe_data_updated(result, generation=Private(), index=Private())
    assert events(caplog)[0]["generation"] == "unknown"
    assert events(caplog)[0]["index"] == "unknown"

    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_SHADOW_HANDLER")

    monkeypatch.setattr(shadow._LOGGER, "debug", broken)
    shadow.observe_data_updated(result, generation=1, index=1)
    assert "PRIVATE_SHADOW_HANDLER" not in caplog.text
    assert shadow.preview_data_updated(object()) is None


def test_generations_keep_no_candidates_or_extra_readers_or_requests(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    async def run():
        factory, backoff = Factory(), Backoff()
        life = factory.lifecycle(
            recover_acquisition=True, ha_reconnect=True, sleep=backoff
        )
        try:
            await life.connect()
            old = factory.streams[0]
            for _ in range(20):
                old.queue.put_nowait(notification())
            await pump()
            assert len(events(caplog)) == 20
            assert all(e["generation"] == 1 for e in events(caplog))
            assert [p[0] for p in old.writes] == [3]
            old.queue.put_nowait(TransportEOF())
            await backoff.entered.get()
            old.queue.put_nowait(notification())
            backoff.release.put_nowait(None)
            await life.wait_connected()
            fresh = factory.streams[1]
            fresh.queue.put_nowait(notification())
            await pump()
            assert len(events(caplog)) == 21
            assert events(caplog)[-1]["generation"] == 2
            assert events(caplog)[-1]["index"] == 1
            assert old.queue.qsize() == 1 and old.close_count == 1
            assert [p[0] for p in fresh.writes] == [3]
            assert life.witness.verified_read_generation is None
            assert (await life.request_v4_data()).registers == (17,) * 20
            assert life.witness.verified_read_generation == 2
        finally:
            await life.close()
            factory.assert_clean()
        count = len(events(caplog))
        factory.streams[-1].queue.put_nowait(notification())
        await pump()
        assert len(events(caplog)) == count

    asyncio.run(run())
