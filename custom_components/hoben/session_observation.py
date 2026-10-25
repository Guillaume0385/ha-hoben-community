"""Read-only local evidence, independent of HA, identities and protocol payloads."""

from dataclasses import dataclass
from enum import StrEnum


class SessionLossKind(StrEnum):
    """An owner-observed loss; transport does not assert a TLS EOF or its cause."""

    TRANSPORT = "transport"
    CLOSE_CLIENT = "close_client"


@dataclass(frozen=True, slots=True)
class SessionObservation:
    """Constant-space evidence scoped to one client lifetime, never a wire proof.

    Generations are opaque local ordinals, unrelated to GUIDs. Read sequence is
    scoped to its generation. Loss and successful cleanup remain visible after
    recovery/close. A local stop, timeout or protocol rejection is not a loss.
    Active means the local owner/session can still operate, not fresh remote
    data, a wire boundary or an inference that silence proves connectivity.
    No resource limit is enforced by reading this immutable projection.
    """

    attempts: int = 0
    generation: int | None = None
    read_generation: int | None = None
    read_sequence: int | None = None
    loss_generation: int | None = None
    loss_kind: SessionLossKind | None = None
    close_client_subcode: int | None = None
    cleaned_generation: int | None = None
    cleanup_failed: bool = False
    stopped: bool = False
    active: bool = False
