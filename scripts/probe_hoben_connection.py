"""Opt-in TLS/OpenClient validation. Importing this module never opens a socket.

Run from a checkout with Python 3.12+: python scripts/probe_hoben_connection.py
--tls-only or --session. DeviceGuid comes only from HOBEN_DEVICE_GUID, never from
arguments. Session opening stays blocked until a UserGuid source is confirmed.
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

# protocol.md §4 confirms the analyzed Android build, not a generic UserGuid.
DEFAULT_BUILD = 34
# Stable implementation/test-client descriptor, NOT official MyHOBEN metadata.
# Only the slash-separated shape is documented; infer no hidden field semantics.
DEFAULT_DEVICE_INFO = "ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0"
BLOCKED_EXIT_CODE = 3


def _resolve_user_guid() -> str | None:
    """Fail closed until repository evidence establishes a valid UserGuid source.

    protocol.md §4 and its history identify Stove.UserGuid as account/stove data;
    neither a generic default nor derivation from DeviceGuid is documented.
    An arbitrary HOBEN_USER_GUID environment value is not such evidence. There is
    deliberately no CLI/env bypass. Enabling this needs evidence, docs and tests
    in a future change; offline tests replace this resolver over fake streams.
    """
    return None


class _SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo accidental identifier arguments in argparse error messages."""

    def error(self, message: str) -> None:
        self.exit(
            2, "Invalid arguments; use --help. Session inputs use HOBEN_* env vars.\n"
        )


async def _probe(session: bool) -> dict[str, int | str]:
    """Validate inputs before connecting and return only allowlisted fields."""
    if session:
        try:
            device_guid = os.environ["HOBEN_DEVICE_GUID"]
            device_info = os.environ.get("HOBEN_DEVICE_INFO", DEFAULT_DEVICE_INFO)
            build = int(os.environ.get("HOBEN_BUILD", str(DEFAULT_BUILD)))
            if (
                not device_guid.strip()
                or not device_info.strip()
                or not 0 <= build <= 65535
            ):
                raise ValueError
        except (KeyError, ValueError):
            raise ValueError("Missing or invalid session inputs") from None

        user_guid = _resolve_user_guid()
        if not user_guid:
            # No transport construction, DNS lookup, TLS connect or network write.
            return {"state": "blocked", "error": "user_guid_unresolved"}
        result = await open_session_once(
            AsyncTlsTransport(),
            user_guid=user_guid,
            build=build,
            device_guid=device_guid,
            device_info=device_info,
        )
        return {"state": "opened", **result.safe_report()}

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


def main(argv: list[str] | None = None) -> int:
    """Run only after explicit mode selection; print sanitized JSON, no traceback."""
    parser = _SafeArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tls-only", action="store_true", help="Verify TLS, then close")
    mode.add_argument(
        "--session",
        action="store_true",
        help=(
            "Prepare one OpenClient using HOBEN_DEVICE_GUID; HOBEN_BUILD defaults "
            "to 34 and HOBEN_DEVICE_INFO to the documented test descriptor. "
            "BLOCKED before connect until a UserGuid source is confirmed."
        ),
    )
    args = parser.parse_args(argv)
    report: dict[str, int | str] = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "state": "error",
    }
    try:
        report.update(asyncio.run(_probe(args.session)))
    except UnexpectedMessageType as error:
        report.update(error="unexpected_message_type", message_type=error.message_type)
    except TransportTimeout as error:
        report.update(error="timeout", operation=error.operation)
    except SessionTimeout:
        report.update(error="timeout", operation="handshake")
    except TransportEOF:
        report.update(error="eof")
    except TransportTlsError:
        report.update(error="tls_verification_or_negotiation_failed")
    except TransportError:
        report.update(error="transport_failed")
    except SessionProtocolError:
        report.update(error="invalid_opened_client")
    except (TypeError, ValueError):
        report.update(error="invalid_session_inputs")
    except KeyboardInterrupt:
        report.update(error="cancelled")
    except Exception:
        # A manual diagnostic must never print arbitrary exception payloads.
        report.update(error="probe_failed")
    print(json.dumps(report, sort_keys=True))
    if report["state"] == "blocked":
        return BLOCKED_EXIT_CODE
    return 1 if report["state"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
