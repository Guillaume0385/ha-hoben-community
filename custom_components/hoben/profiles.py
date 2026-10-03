"""Pure stove-profile selection from confirmed rules in protocol.md §4."""

from enum import Enum

from .myhoben import OpenedClient


class StoveProfile(Enum):
    """Profile identifiers only, without register maps or stove behavior."""

    V4 = "v4"
    V6 = "v6"
    V6V16 = "v6v16"
    BOILER_V6_230 = "boiler_v6_230"
    UNKNOWN = "unknown"


def select_stove_profile(opened: OpenedClient) -> StoveProfile:
    """Select only an unambiguous profile using product fields and software major.

    Unsupported or ambiguous combinations return UNKNOWN. In particular, the
    type 3 / revision 1 rule's "version" discriminator is unresolved, so neither
    software_minor nor application_version is used to infer V6 or V6V16.
    DeviceGuid is never read or logged. Raise TypeError for non-OpenedClient
    input without including its value; numeric ranges belong to the parser.
    """
    if not isinstance(opened, OpenedClient):
        raise TypeError("opened must be an OpenedClient instance")

    if opened.product_type == 5:
        return StoveProfile.V4

    if opened.product_type == 2 and opened.software_major == 0:
        if opened.product_revision in (0, 1):
            return StoveProfile.V6
        if opened.product_revision == 2:
            return StoveProfile.BOILER_V6_230

    if (
        opened.product_type == 3
        and opened.product_revision == 0
        and opened.software_major in (0, 1)
    ):
        return StoveProfile.V6

    return StoveProfile.UNKNOWN
