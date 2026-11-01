"""Logical frame sizes, synthetic payloads only; never TLS-chunk diagnostics."""

import logging

import pytest

from custom_components.hoben.exceptions import HobenProtocolError
from custom_components.hoben.v4_experiment import ExperimentalV4Framer
from tests.test_session_300_runtime import response

LOGGER = "custom_components.hoben.frame_diagnostic"
FRAMES = [
    b"\x0a",
    response(),
    b"\x07" + response()[1:],
    b"\x1bSECR" + response()[1:],
    b"\x05\x03",
]
NAMES = [
    "ping",
    "data_response_client",
    "data_response_server",
    "data_updated",
    "close_client",
]


def records(caplog, event):
    return [
        r.hoben_frame
        for r in caplog.records
        if r.name == LOGGER and r.hoben_frame["event"] == event
    ]


@pytest.mark.parametrize("split", range(1, len(b"".join(FRAMES))))
def test_headers_follow_messages_not_fragmentation_or_coalesced_delivery(caplog, split):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    framer = ExperimentalV4Framer()
    data = b"".join(FRAMES)
    framer.feed(data[:split], None)
    framer.feed(data[split:], None)
    headers = records(caplog, "header")
    assert [r["message_type"] for r in headers] == NAMES
    assert [r["expected_total_bytes"] for r in headers] == [1, 50, 50, 54, 2]
    assert [r["received_bytes"] for r in headers] == [1, 7, 7, 11, 1]
    assert not records(caplog, "error")


@pytest.mark.parametrize("index", [1, 2, 3])
@pytest.mark.parametrize("received", [1, 3, 6, 7, 12, 23])
def test_partial_eof_reports_current_frame_only(caplog, index, received):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    frame = FRAMES[index]
    framer = ExperimentalV4Framer()
    for byte in b"\x0a" + frame[:received]:
        framer.feed(bytes([byte]), None)
    assert isinstance(framer.incomplete_error(), HobenProtocolError)
    (error,) = records(caplog, "error")
    header_size = 11 if index == 3 else 7
    assert error["received_bytes"] == received
    assert error["expected_total_bytes"] == (
        len(frame) if received >= header_size else "unknown"
    )
    assert error["status"] == "partial" and error["category"] == "protocol"
    assert error["length_scope"] == ("frame" if received >= header_size else "unproven")


@pytest.mark.parametrize("head", [b"\xff", b"\x04" + b"S" * 47])
def test_unknown_and_opened_prefix_cannot_claim_a_message_total(caplog, head):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    framer = ExperimentalV4Framer()
    with pytest.raises(HobenProtocolError):
        framer.feed(head + b"\x0a" + response(), None)
    (error,) = records(caplog, "error")
    assert error["received_bytes"] == 1
    assert error["expected_total_bytes"] == "unknown"
    assert error["length_scope"] == "unproven"
    assert len(records(caplog, "header")) == 1


@pytest.mark.parametrize("prefix", [b"\x0e", b"\x07", b"\x1bSECR"])
@pytest.mark.parametrize(
    "protocol,length", [(1, 43), (0, 0), (0, 1), (0, 255), (0, 65535)]
)
def test_invalid_mbap_never_credits_declared_length_or_unexamined_suffix(
    caplog, prefix, protocol, length
):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    framer = ExperimentalV4Framer(recover_data_updated=True)
    header = (
        prefix + b"\xff\xff" + protocol.to_bytes(2, "big") + length.to_bytes(2, "big")
    )
    try:
        framer.feed(b"\x0a" + header + b"PRIVATE_PAYLOAD" + response(), None)
    except HobenProtocolError:
        pass
    (error,) = records(caplog, "error")
    assert error["received_bytes"] == len(header)
    assert error["expected_total_bytes"] == "unknown" and error["status"] == "invalid"
    assert error["length_scope"] == "unproven"
    assert "PRIVATE_PAYLOAD" not in caplog.text and "SECR" not in caplog.text


def test_local_framer_exception_is_typed_without_text_or_fictitious_server_cause(
    caplog, monkeypatch
):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    def fail(_header):
        raise RuntimeError("PRIVATE_PAYLOAD")

    monkeypatch.setattr(
        "custom_components.hoben.v4_experiment.modbus_tcp_frame_size", fail
    )
    framer = ExperimentalV4Framer()
    with pytest.raises(RuntimeError):
        framer.feed(response(), None)
    (error,) = records(caplog, "error")
    assert error["received_bytes"] == 7 and error["expected_total_bytes"] == "unknown"
    assert error["category"] == "unexpected_error" and error["phase"] == "mbap_header"
    assert "PRIVATE_PAYLOAD" not in caplog.text and "Traceback" not in caplog.text


def test_bytewise_complete_stream_has_no_duplicate_header_or_warning(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    framer = ExperimentalV4Framer()
    for byte in b"".join(FRAMES):
        framer.feed(bytes([byte]), None)
    assert len(records(caplog, "header")) == len(FRAMES)
    assert not records(caplog, "error")


def test_unknown_tail_never_becomes_an_opened_client_total_or_next_boundary(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    framer = ExperimentalV4Framer()
    framer.feed(b"\x05\x03PRIVATE_PAYLOAD", None)
    with pytest.raises(HobenProtocolError):
        framer.feed(b"\x0a", None)
    (error,) = records(caplog, "error")
    assert error["expected_total_bytes"] == error["received_bytes"] == "unknown"
    assert "PRIVATE_PAYLOAD" not in caplog.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", "PRIVATE_PAYLOAD"),
        ("message_type", "PRIVATE_PAYLOAD"),
        ("received_bytes", "PRIVATE_PAYLOAD"),
        ("expected_total_bytes", 65535),
        ("length_scope", "PRIVATE_PAYLOAD"),
        ("provenance", "PRIVATE_PAYLOAD"),
        ("generation", True),
        ("received_bytes", {}),
    ],
)
def test_log_boundary_revalidates_all_scalars_without_coercion(caplog, field, value):
    from custom_components.hoben.frame_diagnostic import FrameEvidence

    values = dict(
        generation=1,
        message_type="data_response_client",
        received_bytes=7,
        expected_total_bytes=50,
        length_scope="frame",
        provenance="validated_header",
    )
    values[field] = value
    FrameEvidence(**values).emit("error")
    (error,) = records(caplog, "error")
    assert error[field] in {"unknown", "unproven"}
    assert "PRIVATE_PAYLOAD" not in caplog.text


def test_even_forged_opened_evidence_cannot_publish_a_total(caplog):
    from custom_components.hoben.frame_diagnostic import FrameEvidence

    FrameEvidence(
        message_type="opened_client",
        received_bytes=48,
        expected_total_bytes=48,
        length_scope="frame",
        provenance="validated_header",
    ).emit("error")
    (error,) = records(caplog, "error")
    assert (
        error["expected_total_bytes"] == "unknown"
        and error["length_scope"] == "unproven"
    )


def test_partial_close_length_is_an_explicit_post_open_hypothesis(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    framer = ExperimentalV4Framer()
    framer.feed(b"\x05", None)
    framer.incomplete_error()
    (error,) = records(caplog, "error")
    assert error["received_bytes"] == 1 and error["expected_total_bytes"] == 2
    assert error["length_scope"] == "post_open_hypothesis"
    assert error["provenance"] == "fixed_contract" and error["status"] == "partial"


def test_broken_log_handler_cannot_change_framing_or_publish_its_exception(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_PAYLOAD")

    monkeypatch.setattr("custom_components.hoben.frame_diagnostic._LOGGER.log", fail)
    frames = ExperimentalV4Framer().feed(response(), None)
    assert len(frames) == 1 and frames[0].payload == response()


@pytest.mark.parametrize(
    "reply,category,status",
    [
        (response().replace(b"\xff\xff", b"\xff\xfe", 1), "protocol", "invalid"),
        (bytes.fromhex("0effff00000003010400"), "protocol", "invalid"),
        (bytes.fromhex("0effff00000003018402"), "modbus_exception", "complete"),
    ],
)
def test_rejected_recovery_probe_retains_its_own_frame_size(
    monkeypatch, caplog, reply, category, status
):
    import asyncio

    from tests.test_data_updated_silence import BAD, Clock, make_owner, pump
    from tests.test_v4_persistent import Factory

    async def scenario():
        clock, factory = Clock(monkeypatch), Factory()
        life = make_owner(factory)
        try:
            await life.connect()
            stream = factory.streams[0]
            stream.chunks = [reply]
            stream.queue.put_nowait(BAD)
            await pump()
            await clock.advance(30)
            errors = [
                r
                for r in records(caplog, "error")
                if r["message_type"] == "data_response_client"
            ]
            (error,) = errors
            assert (
                error["received_bytes"] == error["expected_total_bytes"] == len(reply)
            )
            assert error["category"] == category and error["status"] == status
            assert life.data_updated_recovering and len(factory.streams) == 1
        finally:
            await life.close()
            factory.assert_clean()

    asyncio.run(scenario())
