"""#207 D4-D: deterministically exercise the inert read-only HA observation port."""

import asyncio
import json

from scripts.ha_live_d4_observer import observe


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        assert 0 <= seconds <= 5
        self.now += seconds
        await asyncio.sleep(0)


def diagnostics(generation=1):
    return {
        "schema": 1,
        "scope": "tls_attempt",
        "length_scope": "tls_delivery",
        "info_framing": "INCONCLUSIVE",
        "counters_capped": False,
        "tls_generation": generation,
        "boundary_proven": False,
        "unsupported_deliveries": 0,
        "info_candidate_deliveries": 0,
        "v4_responses_correlated": 0,
        "responses_after_drop": 0,
        "responses_after_info_candidate": 0,
        "pings": 0,
        "pongs": 0,
        "tls_connected": True,
        "v4_accepted": True,
        "acquisition_uncertain": False,
        "eof_received": False,
        "terminal_error": False,
        "transport_close_requested": False,
        "transport_close_failed": False,
        "cleanup_failed": False,
        "cleanup_succeeded": False,
        "private_marker": "NEVER_EXPORT_PRIVATE_VALUE",
    }


class Client:
    def __init__(self):
        self.session_diagnostics = diagnostics()
        self.closed = 0
        self.fail_close = False

    async def async_close(self):
        self.closed += 1
        if self.fail_close:
            raise OSError("private exception")
        self.session_diagnostics["cleanup_succeeded"] = True


class Coordinator:
    def __init__(self, client, actions=(), repeat=False):
        self.client = client
        self.actions = list(actions)
        self.repeat = repeat
        self.reads = 0

    async def async_refresh(self):
        self.reads += 1
        if self.actions:
            action = self.actions.pop(0)
            action(self.client.session_diagnostics)
        elif self.repeat and self.reads % 6 == 0:
            correlation(self.client.session_diagnostics)
        return None


def drop(report):
    report["unsupported_deliveries"] += 1
    report["info_candidate_deliveries"] += 1


def correlation(report):
    report["v4_responses_correlated"] += 1
    report["responses_after_drop"] += 1
    report["responses_after_info_candidate"] += 1


def both(report):
    drop(report)
    correlation(report)


def eof(report):
    report["eof_received"] = True


def change_generation(report):
    report["tls_generation"] = 2


def run(*actions, fail_close=False, repeat=False):
    clock = Clock()
    client = Client()
    client.fail_close = fail_close
    coordinator = Coordinator(client, actions, repeat=repeat)
    report = asyncio.run(observe(coordinator, clock=clock, sleep=clock.sleep))
    assert client.closed == 1
    assert report["admission"] == "NOT RUN"
    assert report["execution"] == "component_only"
    assert report["secrets_allowed"] is False
    assert report["live_ready"] is False
    assert report["boundary_proven"] is False
    assert "NEVER_EXPORT_PRIVATE_VALUE" not in json.dumps(report)
    return report


def test_unknown_drop_then_new_read_and_300_real_monotonic_seconds_simulated():
    report = run(drop, correlation, repeat=True)
    assert report["observation"] == "SUCCESS"
    assert report["correlated_at_ms"] > report["drop_at_ms"] >= 0
    assert report["elapsed_ms"] >= report["correlated_at_ms"] + 300_000
    assert report["info_candidates"] == 1
    assert report["correlated_after_drop"] == 1
    assert report["cleanup_attested"] is True


def test_no_candidate_no_response_same_interval_or_generation_change():
    for actions in [
        (),
        (drop,),
        (both,),
        (drop, correlation),
        (drop, change_generation),
        (correlation,),
    ]:
        report = run(*actions)
        assert report["observation"] == "INCONCLUSIVE"
        assert report["cleanup_attested"] is True


def test_actual_eof_and_cleanup_failure_are_failed_not_passed():
    assert run(drop, correlation, eof)["observation"] == "FAILED"
    assert run(drop, correlation, fail_close=True)["observation"] == "FAILED"


def test_secret_data_and_forged_session_diagnostics_never_escape():
    def break_fields(report):
        report["unsupported_deliveries"] = "fake"

    report = run(break_fields)
    # A corrupt D3 schema prevents cleanup attestation too: fail closed.
    assert report["observation"] == "FAILED"
    assert report["unknown_drops"] == 0


def test_saturated_diagnostics_do_not_establish_fresh_correlation():
    def capped(report):
        report["counters_capped"] = True
        report["unsupported_deliveries"] = 65535

    report = run(capped)
    assert report["observation"] == "INCONCLUSIVE"


def test_an_invalid_observer_never_starts_network_or_session():
    try:
        asyncio.run(observe(object()))
    except ValueError as exc:
        assert str(exc) == "ha_live_d4_observer_refused"
    else:
        raise AssertionError("expected refusal")
