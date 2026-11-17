"""#219-S shadow decisions without an invented DataUpdated register mapping.

V4 semantics are proven for solicited reads of 1024..1043, not for an arbitrary
twenty-word notification. Until its range/order is established, no entity ID,
candidate value, snapshot or numeric logging path may be manufactured here.
"""

import logging
from dataclasses import dataclass

from .data_updated_parser import DataUpdatedResult
from .modbus import ModbusReadResponse

_LOGGER = logging.getLogger(__name__)


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
    retained candidate or cross-generation state. Numeric logging is absent.
    """
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
