"""D7 actual session/verified local TLS; never dispatch or Hoben network."""

import asyncio
import json

import pytest

from scripts.info_delivery_memory import OfflineClock
from scripts.info_manual_worker import PassiveTlsPort, make_session, observe
from tests.info_manual_tls_fixture_186 import certificate_files, install_tls
from tests.test_data_updated_silence import pump
from tests.tls_read_candidate_186 import RESPONSE


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    return certificate_files(tmp_path_factory.mktemp("info-local-tls"))


async def scenario(monkeypatch, certs, *, plan=(), close_ack=True, cancel=None):
    loop = asyncio.get_running_loop()
    clock = OfflineClock(origin=0)
    monkeypatch.setattr(loop, "time", clock.loop_time)
    state, user, device = install_tls(monkeypatch, certs, close_ack=close_ack)
    port = PassiveTlsPort(clock=clock.loop_time)
    session = make_session(user, device, port)
    task = asyncio.create_task(observe(session, port, origin=0, clock=clock.loop_time))
    pending, cancelled = list(plan), False
    for _ in range(2048):
        await pump()
        if task.done():
            report = task.result()
            assert state.connections == port._factory_calls == 1
            assert session._rx_task.done()
            assert not session._operations and not session._tx_operations
            assert len(json.dumps(report).encode()) < 8192
            return report, port, state.peer
        times = [h.when() + 0.001 for h in loop._scheduled if not h.cancelled()]
        if pending:
            times.append(pending[0][0] / 1000)
        if cancel is not None and not cancelled:
            times.append(cancel / 1000)
        assert times
        at = max(clock.now_ms, int(min(times) * 1000))
        assert at <= 3600000
        clock.advance_to(at)
        while pending and pending[0][0] <= at:
            _, data = pending.pop(0)
            if data is None:
                state.peer.reader.feed_eof()
            elif isinstance(data, Exception):
                state.peer.reader.set_exception(data)
            else:
                state.peer.deliver(data)
        if cancel is not None and at >= cancel and not cancelled:
            cancelled = True
            task.cancel()
    pytest.fail("passive_worker_stalled")


@pytest.mark.parametrize(
    "candidate",
    [b"\x0c", b"\x0c\x00", b"\x0c\x07", b"\x0c\xff", b"\x0c\x0a", b"\x0c" + RESPONSE],
)
def test_opaque_candidate_needs_no_length_and_never_forces_continuation(
    monkeypatch, certs, candidate
):
    report, port, peer = asyncio.run(
        scenario(
            monkeypatch,
            certs,
            plan=((1000, b"\x0a"), (1100, candidate)),
        )
    )
    assert report["candidate_observed"]
    assert report["candidate_delivery_bytes"] == len(candidate)
    assert report["discarded_deliveries"] == 1
    assert report["continuation"] == "not_proven"
    assert report["post_candidate_reads"] == report["read_requests"] == 0
    assert report["pongs_written"] == report["pings_validated"] == 1
    assert report["cleanup_attested"] and report["tls_verified"]
    assert report["first_error"] == "none"
    assert peer.closed and port._active_read == port._active_write == 0


def test_absent_info_observes_full_window_and_attests_tls_shutdown(monkeypatch, certs):
    report, _, _ = asyncio.run(scenario(monkeypatch, certs))
    assert not report["candidate_observed"] and report["observation_complete"]
    assert report["cleanup_started_ms"] >= 3540000
    assert report["cleanup_attested"] and report["elapsed_ms"] < 3600000


@pytest.mark.parametrize("close_ack", [False, True])
def test_cancellation_and_missing_close_ack_are_never_success(
    monkeypatch, certs, close_ack
):
    report, _, _ = asyncio.run(
        scenario(
            monkeypatch,
            certs,
            close_ack=close_ack,
            cancel=1000,
        )
    )
    assert report["first_error"] == "cancelled"
    if not close_ack:
        assert not report["cleanup_attested"]


@pytest.mark.parametrize("cut", range(1, len(RESPONSE)))
def test_partial_known_response_never_relabels_its_suffix_as_info(
    monkeypatch, certs, cut
):
    report, _, peer = asyncio.run(
        scenario(
            monkeypatch,
            certs,
            plan=((1000, RESPONSE[:cut]), (1100, b"\x0c" + RESPONSE[cut:])),
        )
    )
    assert not report["candidate_observed"]
    assert report["first_error"] != "none"
    assert not peer.read_requests


@pytest.mark.parametrize("suffix", [b"\x00", b"\x07", b"\xff", b"\x0a", RESPONSE])
def test_fragment_after_candidate_is_never_consumed_or_scanned(
    monkeypatch, certs, suffix
):
    report, _, peer = asyncio.run(
        scenario(
            monkeypatch,
            certs,
            plan=((1000, b"\x0c"), (1001, suffix)),
        )
    )
    assert report["candidate_delivery_bytes"] == report["received_bytes"] == 1
    assert report["discarded_deliveries"] == 1
    assert not peer.read_requests and report["cleanup_attested"]


@pytest.mark.parametrize("fault", [None, OSError("synthetic"), b"\x05\x03", b"\xff"])
def test_eof_tls_closeclient_unknown_do_not_invent_info_or_retry(
    monkeypatch, certs, fault
):
    report, _, _ = asyncio.run(scenario(monkeypatch, certs, plan=((1000, fault),)))
    assert not report["candidate_observed"]
    assert report["first_error"] != "none" and report["connections"] == 1
    assert report["post_candidate_reads"] == 0


def test_delivery_at_observation_deadline_is_not_a_candidate(monkeypatch, certs):
    report, _, _ = asyncio.run(scenario(monkeypatch, certs, plan=((3540000, b"\x0c"),)))
    assert not report["candidate_observed"] and report["observation_complete"]
    assert report["cleanup_attested"]


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ("opened", None),
        ("authorization", "HobenAuthorizationRequiredError"),
        ("invalid_device", "HobenProtocolError"),
        ("unknown_profile", "HobenUnsupportedProfileError"),
    ],
)
def test_single_secret_info_session_adopts_device_only_after_valid_opened(
    monkeypatch, certs, answer, error
):
    """Real V4Session and verified offline MemoryBIO TLS; never authorize pairing."""
    import time

    from custom_components.hoben.exceptions import (
        HobenAuthorizationRequiredError,
        HobenProtocolError,
        HobenUnsupportedProfileError,
    )
    from custom_components.hoben.myhoben import INITIAL_DEVICE_GUID, encode_open_client
    from tests import info_manual_tls_fixture_186 as tls_fixture
    from tests.test_v4_session import opened_prefix

    if answer != "opened":
        replies = {
            "authorization": b"\\x2f",
            "invalid_device": opened_prefix(identity=b"\\xff" * 32),
            "unknown_profile": opened_prefix(profile=99),
        }
        monkeypatch.setattr(tls_fixture, "opened_prefix", lambda: replies[answer])

    async def scenario():
        state, user, _ = install_tls(monkeypatch, certs)
        port = PassiveTlsPort()
        session = make_session(user, INITIAL_DEVICE_GUID, port)
        assert session.device_guid_for_persistence == INITIAL_DEVICE_GUID
        port.bind(session, time.monotonic())
        try:
            if error is not None:
                errors = {
                    "HobenAuthorizationRequiredError": HobenAuthorizationRequiredError,
                    "HobenProtocolError": HobenProtocolError,
                    "HobenUnsupportedProfileError": HobenUnsupportedProfileError,
                }
                with pytest.raises(errors[error]):
                    await session.connect()
                assert session.device_guid_for_persistence == INITIAL_DEVICE_GUID
            else:
                await session.connect()
                assert session.device_guid_for_persistence == "a" * 32
            assert state.connections == 1
            assert state.peer.transmissions[0] == encode_open_client(
                user, session._opening_options.build,
                INITIAL_DEVICE_GUID, session._opening_options.device_info,
            )
            assert all(message[:1] != b"\\x30" for message in state.peer.transmissions)
            assert port.facts["tls_verified"]
        finally:
            await session.close()

    asyncio.run(scenario())
