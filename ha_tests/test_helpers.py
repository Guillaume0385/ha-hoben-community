"""Cold-cache error logging must stay private and perform no synchronous I/O."""

import asyncio
import linecache
import logging
from unittest.mock import Mock, patch

from conftest import PRIVATE_TEXT, assert_private_values_absent

from custom_components.hoben.helpers import log_unexpected_error


def _raise_private_error():
    """Keep sensitive locals, message, cause and note in the synthetic exception."""
    private_local = PRIVATE_TEXT
    error = RuntimeError(private_local)
    error.__cause__ = ValueError(private_local)
    error.add_note(private_local)
    raise error


async def test_error_logging_with_empty_source_cache_never_reads_disk(
    hass, monkeypatch, caplog
):
    """Run the helper on HA's loop with all source/file access guarded.

    extract_tb() implicitly fills linecache and opens source files on a cold
    cache. Track source lookups as well as direct file opens so a warm cache or
    a loader-specific path cannot hide a regression.
    """
    assert asyncio.get_running_loop() is hass.loop
    logger = logging.getLogger("custom_components.hoben.helpers")
    forbidden = Mock(side_effect=AssertionError("Synchronous file access is forbidden"))

    # Isolate the empty cache without discarding other tests' cached source lines.
    with (
        monkeypatch.context() as context,
        patch("builtins.open", forbidden),
        patch("io.open", forbidden),
        patch("tokenize.open", forbidden),
        patch("os.stat", forbidden),
        patch.object(linecache, "getlines", wraps=linecache.getlines) as source_lines,
    ):
        context.setattr(linecache, "cache", {})
        try:
            _raise_private_error()
        except RuntimeError as error:
            log_unexpected_error(logger, error)

        forbidden.assert_not_called()
        source_lines.assert_not_called()
        assert linecache.cache == {}

    assert "stack locations" in caplog.text
    assert __file__ in caplog.text
    assert "in _raise_private_error" in caplog.text
    assert_private_values_absent(caplog.text)
