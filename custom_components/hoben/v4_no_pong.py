"""Offline foundation for the opt-in session-reconnect-no-pong experiment.

No transport, timer task, identity or payload is owned here. This policy only
decides whether an already-received Ping may produce a Pong on its session.
It neither forces a disconnect nor attributes a peer EOF to a Ping timeout.
"""

import time


class NoPongAfter120:
    """Suppress Pong after 120 s on the first accepted generation only.

    A replacement generation always restores normal Pong. The shared lifecycle
    continues to own recovery/backoff; a future collector must separately prove
    the stable post-recovery interval. No public report is introduced here.
    """

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._opened_at = None
        self._first = self._current = self._last_eof = None
        self.suppressed = self.peer_eofs = self.peer_eofs_after_suppression = 0
        self.first_eof_after_suppression_at = None
        self.first_close_after_suppression_at = None
        self._last_close = None

    @property
    def first_loss_after_suppression_at(self):
        """A framed experimental close or actual EOF; counters stay distinct."""
        observed = [
            v
            for v in (
                self.first_eof_after_suppression_at,
                self.first_close_after_suppression_at,
            )
            if v is not None
        ]
        return min(observed) if observed else None

    def client_closed(self, generation):
        """Called only for the two-byte post-open event, never a partial 05."""
        if generation != self._current or generation == self._last_close:
            return
        self._last_close = generation
        if generation == self._first and self.suppressed:
            self.first_close_after_suppression_at = self._clock()

    def __repr__(self):
        return "NoPongAfter120()"

    @property
    def first_opened_at(self):
        """Monotonic first acceptance, not TCP connect or collector start."""
        return self._opened_at

    @property
    def first_generation(self):
        """Opaque session generation to which the suppression applies."""
        return self._first

    def accepted(self, generation):
        if self._first is None:
            self._first = generation
            self._opened_at = self._clock()
        self._current = generation

    def suppress(self, generation):
        """Called only under the session TX lock, immediately before Pong TX."""
        if (
            self._opened_at is not None
            and generation == self._current == self._first
            and self._clock() - self._opened_at >= 120
        ):
            self.suppressed += 1
            return True
        return False

    def peer_closed(self, generation):
        """Count an observed read EOF once; local cleanup never calls this."""
        if generation != self._current or generation == self._last_eof:
            return
        self._last_eof = generation
        self.peer_eofs += 1
        if generation == self._first and self.suppressed:
            self.peer_eofs_after_suppression += 1
            self.first_eof_after_suppression_at = self._clock()
