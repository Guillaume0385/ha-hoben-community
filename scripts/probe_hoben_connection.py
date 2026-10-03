"""Opt-in TLS/OpenClient validation. Importing this module never opens a socket.

Run from a checkout with Python 3.12+: python scripts/probe_hoben_connection.py
--tls-only or --session. Session fields come only from HOBEN_* environment values,
so identifiers need not appear in command-line arguments or shell history.
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


class _SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo accidental identifier arguments in argparse error messages."""

    def error(self, message: str) -> None:
        self.exit(
            2, "Invalid arguments; use --help. Session inputs use HOBEN_* env vars.\n"
        )


async def _probe(session: bool) -> dict[str, int | str]:
    """Validate inputs before connecting and return only allowlisted fields."""
    transport = AsyncTlsTransport()
    if session:
        try:
            user_guid = os.environ["HOBEN_USER_GUID"]
            device_guid = os.environ["HOBEN_DEVICE_GUID"]
            device_info = os.environ["HOBEN_DEVICE_INFO"]
            build = int(os.environ["HOBEN_BUILD"])
        except (KeyError, ValueError):
            raise ValueError("Missing or invalid session inputs") from None
        result = await open_session_once(
            transport,
            user_guid=user_guid,
            build=build,
            device_guid=device_guid,
            device_info=device_info,
        )
        return {"state": "opened", **result.safe_report()}

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
            "Send one OpenClient using HOBEN_USER_GUID, HOBEN_DEVICE_GUID, "
            "HOBEN_DEVICE_INFO and HOBEN_BUILD (all required; no build default)"
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
    return 1 if report["state"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
