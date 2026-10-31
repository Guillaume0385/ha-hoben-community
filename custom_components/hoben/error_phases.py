"""Closed local failure provenance; never inspect text, frames, locals or chains."""

from .malformed import TEXT_FIELDS

PHASES = TEXT_FIELDS["phase"] | {
    "post_open",
    "tls_read",
    "message_type",
    "mbap_header",
    "pdu_decode",
    "model_decode",
    "identity_storage",
    "cleanup",
}


def phase_of(error):
    """Return one validated scalar, including at re-export; absent means unknown."""
    try:
        phase = getattr(error, "_hoben_error_phase", None)
    except Exception:
        return None
    return phase if type(phase) is str and phase in PHASES else None


def with_phase(error, phase):
    """Keep the exact exception/category; the innermost proven boundary wins."""
    if phase_of(error) in (None, "unknown"):
        phase = phase if type(phase) is str and phase in PHASES else "unknown"
        try:
            error._hoben_error_phase = phase
        except Exception:
            pass  # A broken metadata contract cannot change the original failure.
    return error


class error_boundary:
    """Annotate escaping failures without accessing/storing a traceback.

    Returning False preserves the original exception and cancellation exactly;
    unlike a generator context manager, no traceback property is read/assigned.
    """

    __slots__ = ("phase",)

    def __init__(self, phase):
        self.phase = phase

    def __enter__(self):
        return self

    def __exit__(self, _kind, error, _traceback):
        if isinstance(error, Exception):
            with_phase(error, self.phase)
        return False
