"""Actual HA owners, typed scalar logs; synthetic transports and failures only."""

import logging
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, PRIVATE_TEXT, assert_private_values_absent

from custom_components.hoben.transport import TransportEOF
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import session_state
from tests.test_data_updated_silence import pump
from tests.test_frame_logging import LOGGER, records


async def test_actual_ha_headers_use_one_generation_and_never_include_payloads(
    hass, entry, peers, caplog
):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    peers.wire(
        DEVICE_GUID,
        [
            [RESPONSE],
            [b"\x0a" + RESPONSE + b"\x07" + RESPONSE[1:] + b"\x1bSECR" + RESPONSE[1:]],
        ],
    )
    coordinator = await load(hass, entry)
    await coordinator.async_refresh()
    await pump()
    headers = records(caplog, "header")
    assert [h["message_type"] for h in headers] == [
        "opened_client",
        "data_response_client",
        "ping",
        "data_response_client",
        "data_response_server",
        "data_updated",
    ]
    assert all(h["generation"] == 1 for h in headers)
    assert (
        headers[0]["expected_total_bytes"] == "unknown"
        and headers[0]["received_bytes"] == 48
    )
    assert coordinator.last_update_success and len(peers.lifecycles) == 1
    assert not records(caplog, "error")
    assert "SECR" not in caplog.text
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
    assert not records(caplog, "error")  # local unload is not a remote error


@pytest.mark.parametrize(
    "target,phase,received",
    [
        ("ExperimentalV4Framer.feed", "frame_boundary", "unknown"),
        ("modbus_tcp_frame_size", "mbap_header", 7),
    ],
)
async def test_synthetic_framer_bug_stays_permanent_and_preserves_a1_a2_b1(
    hass, entry, peers, caplog, monkeypatch, target, phase, received
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    monkeypatch.setattr(
        "custom_components.hoben.v4_experiment." + target,
        Mock(side_effect=RuntimeError(PRIVATE_TEXT)),
    )
    await coordinator.async_refresh()
    await pump()
    (error,) = records(caplog, "error")
    assert error["category"] == "unexpected_error" and error["phase"] == phase
    assert (
        error["received_bytes"] == received
        and error["expected_total_bytes"] == "unknown"
    )
    assert error["generation"] == 1
    assert not coordinator.last_update_success and coordinator.data is previous
    assert coordinator.last_successful_read_at == stamp
    state = session_state(hass, entry)
    assert state.attributes["last_error_category"] == "internal_failure"
    assert state.attributes["last_error_phase"] == phase
    assert peers.backoff.delays == [] and peers.factory.call_count == 1
    assert_private_values_absent(caplog.text)
    assert all(
        r.exc_info is None and "Traceback" not in r.getMessage()
        for r in caplog.records
        if r.name == LOGGER
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_partial_eof_is_reported_even_with_debug_disabled(
    hass, entry, peers, caplog
):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE[:23], TransportEOF(PRIVATE_TEXT)]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    await coordinator.async_refresh()
    (error,) = records(caplog, "error")
    assert error["received_bytes"] == 23 and error["expected_total_bytes"] == 50
    assert error["status"] == "partial" and error["category"] == "protocol"
    assert error["generation"] == 1 and not records(caplog, "header")
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_coalesced_later_frames_do_not_overwrite_rejected_response_size(
    hass, entry, peers, caplog
):
    short = bytes.fromhex("0effff000000020104")
    peers.wire(DEVICE_GUID, [[RESPONSE], [short + b"\x0a\x07" + RESPONSE[1:]]])
    coordinator = await load(hass, entry)
    await coordinator.async_refresh()
    (error,) = records(caplog, "error")
    assert error["received_bytes"] == error["expected_total_bytes"] == 9
    assert (
        error["message_type"] == "data_response_client" and error["status"] == "invalid"
    )
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_generation_ordinals_follow_real_reopening_without_new_retry_policy(
    hass, entry, peers, caplog
):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    first = peers.wire(DEVICE_GUID, [[RESPONSE]])
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    first.queue.put_nowait(TransportEOF(PRIVATE_TEXT))
    assert await peers.backoff.entered.get() == 60
    peers.backoff.release.put_nowait(None)
    await coordinator.client._lifecycle.wait_connected()
    await coordinator.async_refresh()
    headers = records(caplog, "header")
    assert [
        h["generation"] for h in headers if h["message_type"] == "opened_client"
    ] == [1, 2]
    assert headers[-1]["generation"] == 2 and len(peers.lifecycles) == 1
    assert records(caplog, "error")[0]["generation"] == 1
    assert_private_values_absent(caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)
