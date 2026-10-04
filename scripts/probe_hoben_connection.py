"""Opt-in TLS/OpenClient/V4 read validation; imports never open a socket.

Run from a checkout with Python 3.12+: python scripts/probe_hoben_connection.py
--tls-only, --session, --session-negative or --read-v4-state. A session uses the
Identifiant HOBEN and a normal initial zero DeviceGuid. Negative mode substitutes
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

# protocol.md §4 confirms the analyzed Android build.
DEFAULT_BUILD = 34
# Stable implementation/test-client descriptor, NOT official MyHOBEN metadata.
# Only the slash-separated shape is documented; infer no hidden field semantics.
DEFAULT_DEVICE_INFO = "ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
# Syntactically valid, synthetic/unassigned identity; never a real-mode default.
NEGATIVE_TEST_USER_GUID = "00000000000000000000000000000000"


class _SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo accidental identifier arguments in argparse error messages."""

    def error(self, message: str) -> None:
        self.exit(
            2, "Invalid arguments; use --help. Session inputs use HOBEN_* env vars.\n"
        )


async def _probe(
    session: bool, *, read_v4_state: bool = False
) -> dict[str, int | str | list[int]]:
    """Validate inputs before connecting and return only allowlisted fields."""
    if session or read_v4_state:
        try:
            user_guid = normalize_user_guid(os.environ["HOBEN_USER_GUID"])
            device_info = os.environ.get("HOBEN_DEVICE_INFO", DEFAULT_DEVICE_INFO)
            build = int(os.environ.get("HOBEN_BUILD", str(DEFAULT_BUILD)))
            if not device_info.strip() or not 0 <= build <= 65535:
                raise ValueError
        except (KeyError, ValueError):
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
    parser = _SafeArgumentParser(description=__doc__)
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
                else _probe(args.session, read_v4_state=args.read_v4_state)
            )
        )
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
    if args.read_v4_state:
        return 0 if report["state"] == "read" else 1
    if args.session_negative:
        return 0 if report["observation"] == "informative" else 1
    return 1 if report["state"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
