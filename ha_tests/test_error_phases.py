"""Proven local boundaries on actual HA/client/session owners, offline only."""

import asyncio
from unittest.mock import Mock

import pytest
from conftest import DEVICE_GUID, PRIVATE_TEXT, assert_private_values_absent

from custom_components.hoben.coordinator import HobenDataUpdateCoordinator
from custom_components.hoben.diagnostics import async_get_config_entry_diagnostics
from custom_components.hoben.safe_reports import safe_error_report
from custom_components.hoben.transport import (
    TransportCertificateError,
    TransportEOF,
    TransportTlsError,
)
from custom_components.hoben.v4_state import V4DecodeError
from ha_tests.test_persistent_client import RESPONSE, assert_stopped, load
from ha_tests.test_persistent_client import peers as peers  # noqa: F401
from ha_tests.test_session_sensor import measures, session_state
from tests.test_data_updated_silence import pump
from tests.tls_script import script_transport


@pytest.mark.parametrize(
    "boundary,category",
    [
        ("tls_read", "internal_failure"),
        ("frame_boundary", "internal_failure"),
        ("mbap_header", "internal_failure"),
        ("message_type", "internal_failure"),
        ("pdu_decode", "internal_failure"),
        ("model_decode", "unexpected_error"),
        ("identity_storage", "unexpected_error"),
        ("cleanup", "cleanup_failed"),
    ],
)
async def test_proven_phase_survives_real_owners_wrappers_diagnostics_and_sensor(
    hass, entry, peers, monkeypatch, caplog, boundary, category
):
    wire = peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    failure = RuntimeError(PRIVATE_TEXT)
    failure.__cause__ = ValueError(PRIVATE_TEXT)
    failure.add_note(PRIVATE_TEXT)
    broken = Mock(side_effect=failure)
    if boundary in {"tls_read", "cleanup"}:
        if boundary == "cleanup":
            wire.close.side_effect = failure
            wire.queue.put_nowait(TransportEOF("PRIVATE_PAYLOAD"))
        else:
            wire.queue.put_nowait(failure)
        await pump()
    else:
        targets = {
            "frame_boundary": "v4_experiment.ExperimentalV4Framer.feed",
            "mbap_header": "v4_experiment.modbus_tcp_frame_size",
            "message_type": "v4_session.DelimitedV4DataResponse",
            "pdu_decode": "v4_session.decode_read_response",
            "model_decode": "coordinator.decode_v4_snapshot",
            "identity_storage": None,
        }
        if boundary == "identity_storage":
            monkeypatch.setattr(coordinator, "_persist_identity", broken)
        else:
            monkeypatch.setattr("custom_components.hoben." + targets[boundary], broken)
    await coordinator.async_refresh()
    await pump()
    assert not coordinator.last_update_success and coordinator.data is previous
    assert coordinator.last_successful_read_at == stamp
    report = await async_get_config_entry_diagnostics(hass, entry)
    error = report["coordinator"]["last_error"]
    assert error["error"] == category
    assert error.get("phase") == boundary
    state = session_state(hass, entry)
    assert state.attributes["last_error_category"] == category
    assert state.attributes["last_error_phase"] == boundary
    assert peers.factory.call_count == 1 and peers.backoff.delays == []
    assert_private_values_absent(str(report) + str(state.attributes) + caplog.text)
    assert "_raise_private_error" not in caplog.text
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_unproven_client_failure_stays_unknown_without_guessing_a_phase(
    hass, entry, peers, monkeypatch, caplog
):
    peers.wire(DEVICE_GUID, [[RESPONSE]])
    coordinator = await load(hass, entry)
    stamp = coordinator.last_successful_read_at

    async def unproven():
        raise RuntimeError(PRIVATE_TEXT)

    monkeypatch.setattr(coordinator.client, "_refresh_once", unproven)
    await coordinator.async_refresh()
    await pump()
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["coordinator"]["last_error"] == {
        "error": "unexpected_error",
        "phase": "unknown",
    }
    assert session_state(hass, entry).attributes["last_error_phase"] == "unknown"
    assert coordinator.last_successful_read_at == stamp
    assert_private_values_absent(str(report) + caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize(
    "delivery,category,phase,retry,reason",
    [
        (
            b"\x05\x03",
            "experimental_close_client",
            "post_open",
            True,
            "stove_connection_required",
        ),
        (
            b"\x05\x02",
            "experimental_close_client",
            "post_open",
            False,
            "invalid_identifier",
        ),
        (
            TransportEOF("PRIVATE_PAYLOAD"),
            "transport_unavailable",
            "tls_read",
            True,
            None,
        ),
        (b"", "transport_unavailable", "tls_read", True, None),
        (
            TransportTlsError("PRIVATE_PAYLOAD"),
            "transport_unavailable",
            "tls_read",
            True,
            None,
        ),
        (
            TransportCertificateError("PRIVATE_PAYLOAD"),
            "tls_verification_failed",
            "tls_read",
            False,
            None,
        ),
        (b"\xff", "malformed_response", "message_classification", True, None),
        (
            bytes.fromhex("0effff0001002b"),
            "malformed_response",
            "frame_boundary",
            True,
            None,
        ),
    ],
)
async def test_wire_categories_and_retries_stay_distinct(
    hass, entry, peers, delivery, category, phase, retry, reason, caplog
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [delivery]])
    coordinator = await load(hass, entry)
    previous, stamp = coordinator.data, coordinator.last_successful_read_at
    await coordinator.async_refresh()
    if retry:
        assert await peers.backoff.entered.get() == 60
    await pump()
    report = await async_get_config_entry_diagnostics(hass, entry)
    error = report["coordinator"]["last_error"]
    assert error["error"] == category and error["phase"] == phase
    if reason:
        assert error["reason"] == reason
    state = session_state(hass, entry)
    assert state.attributes["last_error_category"] == category
    assert state.attributes["last_error_phase"] == phase
    assert state.state == ("reconnecting" if retry else "disconnected")
    assert peers.backoff.delays == ([60] if retry else [])
    assert peers.factory.call_count == 1
    assert coordinator.data is previous and coordinator.last_successful_read_at == stamp
    assert not coordinator.last_update_success
    assert_private_values_absent(str(report) + str(state.attributes) + caplog.text)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


async def test_informative_model_error_preserves_a1_without_a_false_refresh(
    hass, entry, peers, monkeypatch
):
    peers.wire(DEVICE_GUID, [[RESPONSE], [RESPONSE]])
    coordinator = await load(hass, entry)
    before, stamp = measures(hass, entry), coordinator.last_successful_read_at
    monkeypatch.setattr(
        "custom_components.hoben.coordinator.decode_v4_snapshot",
        Mock(side_effect=V4DecodeError()),
    )
    await coordinator.async_refresh()
    await pump()
    state = session_state(hass, entry)
    assert state.state == "recovering"
    assert state.attributes["last_error_category"] == "invalid_v4_snapshot"
    assert state.attributes["last_error_phase"] == "model_decode"
    assert state.attributes["recovery_count"] == 1
    assert all(measures(hass, entry)[k] is v for k, v in before.items())
    assert coordinator.last_successful_read_at == stamp
    assert not coordinator.last_update_success
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert_stopped(peers)


@pytest.mark.parametrize("failure", ["read", "auth", "certificate", "maintenance"])
async def test_setup_phase_survives_failed_or_cancelled_setup_without_an_entity(
    hass, entry, peers, monkeypatch, failure, caplog
):
    owners = []

    def coordinator_factory(*args):
        owner = HobenDataUpdateCoordinator(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr(
        "custom_components.hoben.coordinator.HobenDataUpdateCoordinator",
        coordinator_factory,
    )
    wire = peers.wire(DEVICE_GUID, [[RuntimeError(PRIVATE_TEXT)]])
    if failure == "certificate":
        wire.connect.side_effect = TransportCertificateError(PRIVATE_TEXT)
    elif failure in {"auth", "maintenance"}:
        wire.queue = script_transport(
            wire, openings=[[b"\x05\x02" if failure == "auth" else b"\x05\x06"]]
        )
    setup = asyncio.create_task(hass.config_entries.async_setup(entry.entry_id))
    if failure == "maintenance":
        assert await peers.backoff.entered.get() == 60
        assert not setup.done()
        monitor = owners[0].client.session_monitor
        assert monitor.last_error_category == "server_closed"
        assert monitor.last_error_phase == "opening"
        assert owners[0].client.session_state == "reconnecting"
        setup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await setup
    else:
        assert not await setup
        error = safe_error_report(owners[0].last_exception)
        assert (
            error["error"]
            == {
                "read": "internal_failure",
                "auth": "invalid_credentials",
                "certificate": "tls_verification_failed",
            }[failure]
        )
        assert error["phase"] == ("tls_read" if failure == "read" else "opening")
        assert peers.backoff.delays == []
    assert not hasattr(entry, "runtime_data")
    assert not measures(hass, entry)
    assert owners[0].last_successful_read_at is None
    monitor = owners[0].client.session_monitor
    stamp = monitor.last_error_at
    monitor.emit()
    assert not monitor._listeners and monitor.last_error_at == stamp
    assert_private_values_absent(caplog.text)
    assert_stopped(peers)
