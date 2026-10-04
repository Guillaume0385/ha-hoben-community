"""Opt-in TLS/OpenClient/V4 read validation; imports never open a socket.

Run from a checkout with Python 3.12+: python scripts/probe_hoben_connection.py
--tls-only, --session, --session-negative, --read-v4-state or --live-premerge.
A session uses the Identifiant HOBEN and a normal initial zero DeviceGuid.
Negative mode substitutes
only a synthetic/unassigned UserGuid and never reads HOBEN_* inputs.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Support direct script execution from any directory, without installing HA.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.hoben.client import (  # noqa: E402
    DEFAULT_BUILD,
    DEFAULT_DEVICE_INFO,
    HobenClient,
)
from custom_components.hoben.exceptions import (  # noqa: E402
    HobenError,
    HobenProtocolError,
)
from custom_components.hoben.myhoben import (  # noqa: E402
    INITIAL_DEVICE_GUID,
    normalize_user_guid,
)
from custom_components.hoben.session import (  # noqa: E402
    SessionProtocolError,
    SessionTimeout,
    UnexpectedMessageType,
    open_session_once,
)
from custom_components.hoben.transport import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    AsyncTlsTransport,
    TransportEOF,
    TransportError,
    TransportTimeout,
    TransportTlsError,
)
from custom_components.hoben.v4_read import (  # noqa: E402
    V4ReadProtocolError,
    V4ReadTimeout,
    open_and_read_v4_once,
)
from custom_components.hoben.v4_state import decode_v4_snapshot  # noqa: E402

# Syntactically valid, synthetic/unassigned identity; never a real-mode default.
NEGATIVE_TEST_USER_GUID = "00000000000000000000000000000000"


class _SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo accidental identifier arguments in argparse error messages."""

    def error(self, message: str) -> None:
        self.exit(
            2, "Invalid arguments; use --help. Session inputs use HOBEN_* env vars.\n"
        )


async def _probe(
    session: bool, *, read_v4_state: bool = False, live_premerge: bool = False
) -> dict[str, int | str | list[int]]:
    """Validate inputs before connecting and return only allowlisted fields."""
    if session or read_v4_state or live_premerge:
        try:
            user_guid = normalize_user_guid(os.environ["HOBEN_USER_GUID"])
        except (KeyError, ValueError):
            raise ValueError("Missing or invalid session inputs") from None

        if live_premerge:
            # Exercise the public client, not a parallel handshake/read path.
            # Exactly two refreshes/transports: retries are tested offline and
            # disabled here so a transient failure cannot pass the fixed suite.
            # Exercise the same build/DeviceInfo defaults as the future HA caller.
            # Only the credential is read; no exploratory override is consulted.
            client = HobenClient(user_guid=user_guid, max_attempts=1)
            try:
                first_snapshot = await client.async_refresh()
                decode_v4_snapshot(first_snapshot)
                if not client.has_assigned_device_guid:
                    raise HobenProtocolError()
                snapshot = await client.async_refresh()
                decode_v4_snapshot(snapshot)
                if not client.has_assigned_device_guid:
                    raise HobenProtocolError()
                return snapshot.safe_report() | {
                    "state": "client_refresh_validated",
                    "device_guid_reuse": "validated",
                    "refresh_count": 2,
                    # Only completion metadata. Never print decoded household
                    # values, enum codes, raw registers or either identity.
                    "v4_decode_count": 2,
                }
            finally:
                await client.async_close()

        try:
            device_info = os.environ.get("HOBEN_DEVICE_INFO", DEFAULT_DEVICE_INFO)
            build = int(os.environ.get("HOBEN_BUILD", str(DEFAULT_BUILD)))
            if not device_info.strip() or not 0 <= build <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError("Missing or invalid session inputs") from None

        operation = open_and_read_v4_once if read_v4_state else open_session_once
        result = await operation(
            AsyncTlsTransport(),
            user_guid=user_guid,
            build=build,
            device_guid=INITIAL_DEVICE_GUID,
            device_info=device_info,
        )
        return result.safe_report()

    transport = AsyncTlsTransport()
    failed = True
    try:
        await transport.connect()
        failed = False
    finally:
        try:
            await transport.close()
        except TransportError:
            if not failed:
                raise
    return {"state": "tls_connected"}


async def _probe_negative() -> dict[str, int | str]:
    """Observe one synthetic OpenClient; no secret, env override or real pairing.

    Use the existing verified transport and one-shot session lifecycle unchanged.
    UnexpectedMessageType and TransportEOF can only originate from its receive
    path, after TLS connect and the OpenClient write/drain have completed.
    No response type or authentication outcome is assumed for these test values.
    """
    result = await open_session_once(
        AsyncTlsTransport(),
        user_guid=NEGATIVE_TEST_USER_GUID,
        build=DEFAULT_BUILD,
        device_guid=INITIAL_DEVICE_GUID,
        device_info=DEFAULT_DEVICE_INFO,
    )
    return result.safe_report()


def main(argv: list[str] | None = None) -> int:
    """Run only after explicit mode selection; print sanitized JSON, no traceback."""
    parser = _SafeArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tls-only", action="store_true", help="Verify TLS, then close")
    mode.add_argument(
        "--session",
        action="store_true",
        help=(
            "Observe one first-client OpenClient using HOBEN_USER_GUID (Identifiant "
            "HOBEN, with or without dashes) and an initial zero DeviceGuid; "
            "HOBEN_BUILD defaults to 34 and HOBEN_DEVICE_INFO to the documented "
            "test descriptor. "
            "No authentication code is requested or sent."
        ),
    )
    mode.add_argument(
        "--session-negative",
        action="store_true",
        help=(
            "Send one OpenClient with a synthetic/unassigned UserGuid and normal "
            "initial zero DeviceGuid, observe and close. "
            "No secrets or HOBEN_* inputs; does not validate real authentication."
        ),
    )
    mode.add_argument(
        "--live-premerge",
        action="store_true",
        help=(
            "Fixed MANAGER-approved suite: two refreshes on one HobenClient, "
            "each with fresh verified TLS, authenticated V4 opening, one function "
            "04 read (FFFF, unit 1, address 1024, quantity 20), then close. "
            "Require assigned DeviceGuid reuse. Uses only HOBEN_USER_GUID; "
            "no exploratory overrides, pairing or control."
        ),
    )
    mode.add_argument(
        "--read-v4-state",
        action="store_true",
        help=(
            "Open one first-client session using HOBEN_USER_GUID, require V4 "
            "without unclassified OpenedClient bytes, read exactly 20 raw UInt16 "
            "registers once, then close. No register semantics or control. "
            "Real validation is reserved for reviewed main."
        ),
    )
    args = parser.parse_args(argv)
    report: dict[str, int | str | list[int]] = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "state": "error",
    }
    try:
        report.update(
            asyncio.run(
                _probe_negative()
                if args.session_negative
                else _probe(
                    args.session,
                    read_v4_state=args.read_v4_state,
                    live_premerge=args.live_premerge,
                )
            )
        )
    except HobenError as error:
        report.update(error.safe_report())
    except UnexpectedMessageType as error:
        report.update(error="unexpected_message_type", message_type=error.message_type)
    except TransportTimeout as error:
        report.update(error="timeout", operation=error.operation)
    except SessionTimeout:
        report.update(error="timeout", operation="handshake")
    except V4ReadTimeout:
        report.update(error="timeout", operation="v4_read")
    except TransportEOF:
        report.update(error="eof")
    except TransportTlsError:
        report.update(error="tls_verification_or_negotiation_failed")
    except TransportError:
        report.update(error="transport_failed")
    except V4ReadProtocolError:
        report.update(error="invalid_v4_read_response")
    except SessionProtocolError:
        report.update(error="invalid_opened_client")
    except (TypeError, ValueError):
        report.update(error="invalid_session_inputs")
    except KeyboardInterrupt:
        report.update(error="cancelled")
    except Exception:
        # A manual diagnostic must never print arbitrary exception payloads.
        report.update(error="probe_failed")
    if args.read_v4_state:
        report["mode"] = "read-v4-state"
    if args.live_premerge:
        report["mode"] = "live-premerge"
    if args.session_negative:
        report["mode"] = "session-negative"
        # An observed reply/EOF is informative, not successful authentication.
        # Timeouts, TLS/transport errors and malformed prefixes stay inconclusive.
        informative = report["state"] in (
            "opened",
            "authorization_required",
            "closed",
        ) or report.get("error") in (
            "unexpected_message_type",
            "eof",
        )
        report["observation"] = "informative" if informative else "inconclusive"
    print(json.dumps(report, sort_keys=True))
    if args.live_premerge:
        # A classified rejection is useful for research but never passes this
        # authenticated gate. The protocol parser already checks correlation
        # and UInt16 values; explicitly require the entire fixed result here.
        required = {
            "state": "client_refresh_validated",
            "profile": "v4",
            "device_guid_reuse": "validated",
            "refresh_count": 2,
            "register_count": 20,
            "v4_decode_count": 2,
        }
        return 0 if all(report.get(k) == v for k, v in required.items()) else 1
    if args.read_v4_state:
        return 0 if report["state"] == "read" else 1
    if args.session_negative:
        return 0 if report["observation"] == "informative" else 1
    return 1 if report["state"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
