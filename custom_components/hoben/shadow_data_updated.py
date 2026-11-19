"""Local opt-in #219 DEBUG: current applied states and historical candidate FIFO.

The owner empirically accepted FFFF/04/20 index order on 2026-11-19 for the
reference equipment. observe_applied_data_updated audits that current HA path;
the legacy shadow/FIFO API retains its original candidate labels and opt-ins.
Nothing here defines a shared diagnostic export or sends data elsewhere.
"""

import asyncio
import json
import logging
import os
import stat
from dataclasses import asdict, dataclass

from .data_updated_parser import DataUpdatedResult
from .modbus import ModbusReadResponse

_LOGGER = logging.getLogger(__name__)

# Names of the solicited V4 reference map in protocol.md §8. Their association
# with a notification index was accepted empirically by the owner on 2026-11-19,
# without claiming an address in the response. Legacy candidate labels remain
# for compatibility; current HA snapshot publication uses the existing decoder.
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


def _candidate_words(result):
    """Exact shape admitted by the owner; legacy callers keep candidate labels."""
    if preview_data_updated(result) is None:
        return None
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
    ):
        return None
    return response.registers


def _private_register_journal(result, generation, index):
    """One nonblocking atomic batch, no retained writer, payload or replay.

    This optional DEBUG-labelled FIFO stream is independent of Python logging.
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
        words = _candidate_words(result)
        if (
            words is None
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
                zip(_V4_REFERENCE_NAMES, words, strict=True)
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

    Only an explicit DEBUG level on THIS logger enables the local HA event.
    An ancestor/root DEBUG setting cannot opt in. NOTSET or any other level
    stops it immediately, including after reload; there is no pending worker,
    retained candidate or cross-generation state. Eligible raw UInt16 words are
    candidate register labels, never physical measurements or entity proposals.
    The independent FIFO retains its original opt-in and nonblocking behavior.
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
        suffix = ""
        words = _candidate_words(result)
        if (
            words is not None
            and fields["generation"] != "unknown"
            and fields["index"] != "unknown"
        ):
            candidates = [
                {
                    "index": offset,
                    "register_candidate": 1024 + offset,
                    "name": name,
                    "raw_value": word,
                }
                for offset, (name, word) in enumerate(
                    zip(_V4_REFERENCE_NAMES, words, strict=True)
                )
            ]
            block = json.dumps(candidates, separators=(",", ":"))
            # ASCII constants + bounded integers: one record stays below 4096
            # bytes including its fixed prefix/context. Never split or retain it.
            if len(block) <= 3500:
                fields["candidate_registers"] = candidates
                suffix = f" candidate_registers={block}"
        _LOGGER.debug(
            "Hoben SHADOW SIMULATION event=shadow_mapping_unproven "
            "simulated=true mapping=unverified source=DataUpdated "
            "generation=%s index=%s proposals=0%s",
            fields["generation"],
            fields["index"],
            suffix,
            extra={"hoben_shadow": fields.copy()},
        )
    except Exception:
        pass  # A diagnostic failure cannot change RX, freshness, TX or cleanup.


def observe_applied_data_updated(snapshot, state, *, generation, index):
    """Private local opt-in only; mapping accepted by the owner on 2026-11-19.

    One bounded event, no identifier/metadata/frame or export projection. Values
    come from the same immutable snapshot and existing V4 decoder used by HA.
    """
    try:
        if _LOGGER.level != logging.DEBUG or not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        fields = {
            "source": "DataUpdated",
            "mapping": "owner_validated",
            "generation": _public_index(generation, 2147483647),
            "index": _public_index(index, 65535),
            "registers": [
                {
                    "index": i,
                    "register": 1024 + i,
                    "name": _V4_REFERENCE_NAMES[i],
                    "raw_value": word,
                }
                for i, word in enumerate(snapshot.registers)
            ],
            "decoded": asdict(state),
        }
        block = json.dumps(fields, separators=(",", ":"), ensure_ascii=True)
        if len(block) <= 8192:
            _LOGGER.debug(
                "Hoben DataUpdated local state=%s",
                block,
                extra={"hoben_data_updated_state": fields},
            )
    except (Exception, asyncio.CancelledError):
        pass
