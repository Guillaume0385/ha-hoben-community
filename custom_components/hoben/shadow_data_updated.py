"""Categorical shadow decisions and the owner's private #219 register journal.

V4 semantics are proven for solicited reads of 1024..1043, not for an arbitrary
twenty-word notification. The #219-DU-REGISTER-LOG-003 exception permits only a
labelled candidate range in a private ephemeral FIFO. No LogRecord ever carries
those numbers; general HA loggers, handlers and support exports cannot receive
them. The original public projection still refuses all entity proposals.
"""

import logging
import os
import stat
from dataclasses import dataclass

from .data_updated_parser import DataUpdatedResult
from .modbus import ModbusReadResponse

_LOGGER = logging.getLogger(__name__)

# Names of the solicited V4 reference map in protocol.md §8. Their association
# with a notification index is ONLY the owner's explicitly authorized hypothesis.
# Do not use these candidates as a RawStoveSnapshot or as an entity mapping.
_V4_REFERENCE_NAMES = (
    "erarMode_ConsigneMarchArret",
    "erarTemperatureDerogation",
    "erarTempoStartDerogation",
    "erarDureeDerogation",
    "erarModeVentilation",
    "erarDefautsCombustion",
    "erarPuissance_Etat",
    "erarTemperatureAmbianteOffseted",
    "erarConsigneTemperatureEC",
    "erarModeVentilEC_ConsignePMaxEC",
    "erarWarnings",
    "erarInformations",
    "erarAnnee_Mois",
    "erarJourSemaineJourMois_Heures",
    "erarMinutes_Secondes",
    "erarTemperatureAmbianteConv",
    "erarTemperatureComburantConv",
    "erarTemperatureFumeeConv",
    "erarPVIConv",
    "erarTemperatureRFConv",
)


def _private_register_journal(result, generation, index):
    """One nonblocking atomic batch, no retained writer, payload or replay.

    This is a DEBUG-labelled private stream, deliberately NOT Python logging:
    even a root handler or LogRecordFactory must never see household numbers.
    The owner must explicitly enable both environment settings in local HA and
    supply a reader on an owned 0600 FIFO. No file is created or truncated.
    O_PATH pins an inode without opening devices; /proc reopens that same FIFO,
    not a pathname an attacker could replace. Unsupported hosts fail closed.
    A disconnected/slow reader drops the whole batch; no fallback or exception
    text enters HA logs. CI is always denied, including with explicit settings.
    """
    anchor = writer = None
    try:
        if (
            os.environ.get("HOBEN_PRIVATE_DATAUPDATED_DEBUG") != "1"
            or "CI" in os.environ
            or "GITHUB_ACTIONS" in os.environ
        ):
            return
        path = os.environ.get("HOBEN_PRIVATE_DATAUPDATED_FIFO", "")
        if not path.startswith("/") or len(path) > 512:
            return
        if preview_data_updated(result) is None:
            return
        response = result.response
        if (
            type(response.transaction_id) is not int
            or response.transaction_id != 65535
            or type(response.function_code) is not int
            or response.function_code != 4
            or type(response.unit_id) is not int
            or response.unit_id != 1
            or type(response.registers) is not tuple
            or len(response.registers) != 20
            or any(
                type(word) is not int or not 0 <= word <= 65535
                for word in response.registers
            )
            or _public_index(generation, 2147483647) == "unknown"
            or _public_index(index, 65535) == "unknown"
        ):
            return
        anchor = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
        pinned = os.fstat(anchor)
        if (
            not stat.S_ISFIFO(pinned.st_mode)
            or stat.S_IMODE(pinned.st_mode) != 0o600
            or pinned.st_uid != os.geteuid()
            or pinned.st_nlink != 1
        ):
            return
        writer = os.open(
            f"/proc/self/fd/{anchor}", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC
        )
        current = os.fstat(writer)
        if (
            current.st_dev != pinned.st_dev
            or current.st_ino != pinned.st_ino
            or current.st_mode != pinned.st_mode
            or current.st_uid != pinned.st_uid
            or current.st_nlink != 1
        ):
            return
        payload = "".join(
            f"DEBUG source=DataUpdated mapping=unverified simulated=true "
            f"generation={generation} delivery={index} index={offset} "
            f"register_candidate={1024 + offset} raw_value={word} name={name}\n"
            for offset, (name, word) in enumerate(
                zip(_V4_REFERENCE_NAMES, response.registers, strict=True)
            )
        ).encode("ascii")
        if len(payload) > os.fpathconf(writer, "PC_PIPE_BUF"):
            return
        # <= PIPE_BUF + O_NONBLOCK means all-or-nothing for an actual FIFO.
        # Never retry a short/failed write or keep a copy for another generation.
        os.write(writer, payload)
    except Exception:
        pass  # No fallback, arbitrary error string, logger or exception export.
    finally:
        for descriptor in (writer, anchor):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


@dataclass(frozen=True, slots=True)
class ShadowPreview:
    """An immutable refusal to invent proposals; no received content is retained."""

    reason: str = "shadow_mapping_unproven"
    proposals: tuple[()] = ()
    simulated: bool = True
    mapping: str = "unverified"


def preview_data_updated(result):
    """A valid read PDU establishes structure, never its V4 address or identity."""
    if type(result) is not DataUpdatedResult:
        return None
    report = result.safe_report()
    if (
        report["status"] != "parsed"
        or report["reason"] != "ok"
        or type(result.response) is not ModbusReadResponse
    ):
        return None
    return ShadowPreview()


def _public_index(value, maximum):
    if type(value) is int and 0 < value <= maximum:
        return value
    return "unknown"


def observe_data_updated(result, *, generation, index):
    """Optional, synchronous, stateless observation owned by the original RX.

    Only an explicit DEBUG level on THIS logger enables the categorical event.
    An ancestor/root DEBUG setting cannot opt in. NOTSET or any other level
    stops it immediately, including after reload; there is no pending worker,
    retained candidate or cross-generation state. The separate owner-opted-in
    FIFO never sends numeric content through this or any other Python logger.
    """
    _private_register_journal(result, generation, index)
    try:
        if _LOGGER.level != logging.DEBUG or not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        if preview_data_updated(result) is None:
            return
        fields = {
            "event": "shadow_mapping_unproven",
            "simulated": True,
            "mapping": "unverified",
            "source": "DataUpdated",
            "proposals": 0,
            "generation": _public_index(generation, 2147483647),
            "index": _public_index(index, 65535),
        }
        _LOGGER.debug(
            "Hoben SHADOW SIMULATION event=shadow_mapping_unproven "
            "simulated=true mapping=unverified source=DataUpdated "
            "generation=%s index=%s proposals=0",
            fields["generation"],
            fields["index"],
            extra={"hoben_shadow": fields.copy()},
        )
    except Exception:
        pass  # A diagnostic failure cannot change RX, freshness, TX or cleanup.
