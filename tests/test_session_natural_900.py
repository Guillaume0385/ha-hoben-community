"""Synthetic unit tests for the natural 900-second scenario; no network."""

from copy import deepcopy

import pytest

from scripts.session_natural_900 import validate_natural


def report(**changes):
    base = {
        "scenario": "session-natural-900",
        "result": "not_run",
        "duration_ms": 0,
        "initial_continuous": False,
        "reconnect_attempts": 0,
        "correlated_recovery_reads": 0,
    }
    return base | changes


@pytest.mark.parametrize(
    "outcome",
    [
        report(),
        report(result="inconclusive", duration_ms=900000, initial_continuous=True),
        report(result="failed", duration_ms=60000, reconnect_attempts=1),
        report(
            result="reconnected",
            duration_ms=123000,
            reconnect_attempts=1,
            correlated_recovery_reads=1,
        ),
    ],
)
def test_allowlisted_outcomes(outcome):
    assert validate_natural(outcome) == outcome


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_ms": 900001},
        {"duration_ms": -1},
        {"reconnect_attempts": 2},
        {"reconnect_attempts": True},
        {"correlated_recovery_reads": 2},
        {"correlated_recovery_reads": True},
        {"result": "reconnected"},
        {"result": "not_run", "duration_ms": 1},
        {"result": "not_run", "reconnect_attempts": 1},
        {"result": "failed", "correlated_recovery_reads": 1},
        {
            "result": "reconnected",
            "reconnect_attempts": 0,
            "correlated_recovery_reads": 1,
        },
    ],
)
def test_invalid_evidence_fails_closed(changes):
    with pytest.raises(ValueError, match="invalid_natural_report"):
        validate_natural(report(**changes))


def test_public_schema_rejects_unallowlisted_private_values():
    private = deepcopy(report())
    private["device_guid"] = "synthetic-placeholder"
    with pytest.raises(ValueError, match="invalid_natural_report"):
        validate_natural(private)
