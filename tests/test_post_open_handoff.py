"""Offline counterexamples to treating an accepted prefix as a complete opening.

These preserve the frozen one-shot operations; they do not implement a boundary
detector or prove any server behavior. In particular, a scripted later suffix
can remain unread while the opening report matches the public Osmose metadata.
"""

import asyncio
import json
from pathlib import Path

import pytest

from custom_components.hoben.myhoben import encode_open_client
from custom_components.hoben.profiles import StoveProfile
from custom_components.hoben.session import OpenSessionResult, open_session_once
from custom_components.hoben.transport import AsyncTlsTransport
from custom_components.hoben.v4_read import V4ReadBlockedResult, open_and_read_v4_once

# Entirely synthetic bytes. Only the public product/software fields match the
# reference fixture; the ASCII identity is independently invented for tests.
OPENED_PREFIX = (
    b"\x04\x00\x0a\x0b\x00\x00\x00\x00\x05\x02\x08\x00\x00\x00"
    b"ABCDabcdABCDabcdABCDabcdABCDabcd\x00\x02"
)
FIELDS = {
    "user_guid": "01234567-89AB-CDEF-0123-456789ABCDEF",
    "device_guid": "00000000000000000000000000000000",
    "build": 34,
    "device_info": "Synthetic/Handoff",
}
# A structurally valid synthetic 20-register response can also be an unknown
# opening suffix. Its resemblance cannot decide which interpretation is true.
RESPONSE_LIKE = bytes.fromhex("0E FF FF 00 00 00 2B 01 04 28") + b"\x00\x00" * 20
NOTIFICATION_LIKE = b"\x1b\x0a\x0b\x0e\x1b" + RESPONSE_LIKE[1:]
SUFFIXES = [b"\x0a", RESPONSE_LIKE, NOTIFICATION_LIKE, b"\xffSYNTHETIC-PRIVATE-SUFFIX"]
SUFFIX_IDS = ["ping-like", "response-like", "notification-like", "opaque"]


def assert_one_shot_closed_without_post_open_writes(streams) -> None:
    """No suffix may cause Pong, pairing, a Modbus request or a reconnect."""
    streams.connect.assert_awaited_once()
    streams.writer.write.assert_called_once_with(encode_open_client(**FIELDS))
    streams.writer.close.assert_called_once_with()
    streams.writer.wait_closed.assert_awaited_once_with()


def assert_report_private(result, suffix, caplog) -> None:
    """The diagnostic observation contains neither identities nor opaque bytes."""
    public = repr(result) + json.dumps(result.safe_report()) + caplog.text
    for sensitive in (
        FIELDS["user_guid"],
        FIELDS["user_guid"].replace("-", "").lower(),
        FIELDS["device_guid"],
        OPENED_PREFIX[14:46].decode("ascii"),
        FIELDS["device_info"],
        "SYNTHETIC-PRIVATE-SUFFIX",
        repr(suffix),
    ):
        assert sensitive not in public


@pytest.mark.parametrize("suffix", SUFFIXES, ids=SUFFIX_IDS)
def test_coalesced_lookalike_suffix_blocks_read_without_reframing(
    streams, suffix, caplog
) -> None:
    """The existing V4 gate refuses every already-read suffix, regardless of type."""
    script = iter([OPENED_PREFIX + suffix, RESPONSE_LIKE])
    streams.reader.read.side_effect = script
    with caplog.at_level("DEBUG"):
        result = asyncio.run(open_and_read_v4_once(AsyncTlsTransport(), **FIELDS))

    assert isinstance(result, V4ReadBlockedResult)
    assert result.session.profile is StoveProfile.V4
    assert result.safe_report()["error"] == "unclassified_opened_client_bytes"
    assert result.safe_report()["unclassified_bytes"] == len(suffix)
    streams.reader.read.assert_awaited_once()
    assert next(script) == RESPONSE_LIKE
    assert_one_shot_closed_without_post_open_writes(streams)
    assert_report_private(result, suffix, caplog)


@pytest.mark.parametrize("suffix", SUFFIXES, ids=SUFFIX_IDS)
@pytest.mark.parametrize("fragmented", [False, True], ids=["one-read", "fragmented"])
def test_zero_unclassified_report_cannot_exclude_a_delayed_suffix(
    streams, suffix, fragmented, caplog
) -> None:
    """Closing after the prefix leaves a later lookalike opaque and unobserved.

    Both chunkings produce the same public report as the sanitized production
    fixture despite the pending suffix. This is an offline ambiguity witness,
    never evidence that production OpenedClient actually contains such bytes.
    """
    chunks = (
        [OPENED_PREFIX[:13], OPENED_PREFIX[13:47], OPENED_PREFIX[47:]]
        if fragmented
        else [OPENED_PREFIX]
    )
    script = iter([*chunks, suffix, b""])
    streams.reader.read.side_effect = script
    with caplog.at_level("DEBUG"):
        result = asyncio.run(open_session_once(AsyncTlsTransport(), **FIELDS))

    assert isinstance(result, OpenSessionResult)
    assert result.profile is StoveProfile.V4
    fixture = (
        Path(__file__).parent / "fixtures/opened_client_v4_production_2026_10_04.json"
    )
    assert result.safe_report() == json.loads(fixture.read_text(encoding="utf-8"))
    assert streams.reader.read.await_count == len(chunks)
    assert next(script) == suffix
    assert_one_shot_closed_without_post_open_writes(streams)
    assert_report_private(result, suffix, caplog)
