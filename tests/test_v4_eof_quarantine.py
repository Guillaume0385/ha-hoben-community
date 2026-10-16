"""Pure policy tests only: no real cutoff, transport EOF or recovery exercised."""

import ast
import builtins
import itertools
import json
import sys
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from types import ModuleType

import pytest

from custom_components.hoben.v4_eof_quarantine import (
    MAX_TIME_MS,
    EofQuarantinePolicy,
    Event,
    Reason,
    Rejection,
    Scenario,
    State,
)

T0 = 1000


def policy(**changes):
    return EofQuarantinePolicy(
        **(
            {
                "accepted_generation": 1,
                "accepted_at_ms": T0,
                "observation_deadline_ms": T0 + 590000,
                "process_deadline_ms": T0 + 600000,
                "suite_deadline_ms": T0 + 1020000,
            }
            | changes
        )
    )


def request(p, **changes):
    return p.request(
        **(
            {
                "now_ms": T0 + 120000,
                "generation": 1,
                "scenario": Scenario.RECONNECT,
                "rejection": Rejection.CLOSE_CLIENT,
                "suppressed_pongs": 1,
                "tx_in_flight": False,
                "local_stop": False,
            }
            | changes
        )
    )


@pytest.mark.parametrize(
    "delta,state,reason",
    [
        (119999, State.REFUSED, Reason.INELIGIBLE),
        (120000, State.WAITING, Reason.NONE),
        (120001, State.WAITING, Reason.NONE),
        (299999, State.WAITING, Reason.NONE),
        (300000, State.REFUSED, Reason.EXPIRED),
        (300001, State.REFUSED, Reason.EXPIRED),
    ],
)
def test_fixed_eligibility_boundaries(delta, state, reason):
    p = policy()
    assert p.snapshot.state is State.READY and not p.snapshot.block_tx
    s = request(p, now_ms=T0 + delta)
    assert s.state is state and s.reason is reason and s.block_tx
    assert s.deadline_ms == T0 + 300000


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"scenario": Scenario.SESSION_300}, Reason.INELIGIBLE),
        *[
            ({"rejection": r}, Reason.INELIGIBLE)
            for r in Rejection
            if r is not Rejection.CLOSE_CLIENT
        ],
        ({"suppressed_pongs": 0}, Reason.INELIGIBLE),
        ({"tx_in_flight": True}, Reason.TX_IN_FLIGHT),
        ({"local_stop": True}, Reason.LOCAL_STOP),
        ({"generation": 2}, Reason.STALE),
        ({"generation": 0}, Reason.STALE),
        ({"generation": True}, Reason.STALE),
        ({"scenario": "session-reconnect-no-pong"}, Reason.INVALID),
        ({"rejection": "close_client"}, Reason.INVALID),
        ({"rejection": b"\x05"}, Reason.INVALID),
        ({"rejection": {"payload": "synthetic-private"}}, Reason.INVALID),
        ({"suppressed_pongs": True}, Reason.INVALID),
        ({"suppressed_pongs": -1}, Reason.INVALID),
        ({"suppressed_pongs": 1048577}, Reason.INVALID),
        ({"tx_in_flight": 1}, Reason.INVALID),
        ({"local_stop": None}, Reason.INVALID),
    ],
)
def test_ineligible_or_invalid_request_latches_and_never_rearms(change, reason):
    p = policy()
    s = request(p, **change)
    assert s.state is State.REFUSED and s.reason is reason and s.block_tx
    assert s.candidate_at_ms is None
    assert request(p) is s
    assert p.advance(Event.EOF, now_ms=T0 + 121000, generation=1) is s
    assert "synthetic-private" not in repr(s) + repr(p)


@pytest.mark.parametrize(
    "key",
    [
        "accepted_at_ms",
        "observation_deadline_ms",
        "process_deadline_ms",
        "suite_deadline_ms",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        -1,
        1.0,
        float("nan"),
        float("inf"),
        float("-inf"),
        MAX_TIME_MS + 1,
        b"private",
        "private",
        {},
    ],
)
def test_constructor_rejects_invalid_time_without_retaining_input(key, value):
    p = policy(**{key: value})
    s = p.snapshot
    assert (s.state, s.reason, s.block_tx) == (State.REFUSED, Reason.INVALID, True)
    assert s.generation is s.deadline_ms is s.candidate_at_ms is None
    assert "private" not in repr(p) + repr(s)


@pytest.mark.parametrize(
    "change",
    [{"accepted_generation": v} for v in (None, True, 0, 2, 3, "1", b"1")]
    + [
        {"accepted_at_ms": MAX_TIME_MS - 299999},
        {"observation_deadline_ms": T0},
        {"process_deadline_ms": T0 - 1},
    ],
)
def test_unknown_first_acceptance_or_unusable_deadline_fails_closed(change):
    assert policy(**change).snapshot.state is State.REFUSED


@pytest.mark.parametrize(
    "key", ["observation_deadline_ms", "process_deadline_ms", "suite_deadline_ms"]
)
def test_existing_deadlines_only_shorten_the_absolute_window(key):
    p = policy(**{key: T0 + 150000})
    initial = request(p)
    assert initial.deadline_ms == T0 + 150000
    assert request(p, now_ms=T0 + 140000) == initial
    s = p.advance(Event.TICK, now_ms=T0 + 150000, generation=1)
    assert s.state is State.REFUSED and s.reason is Reason.EXPIRED
    assert request(p, now_ms=T0 + 150001) is s


def test_request_and_declared_eof_are_idempotent_provisional_and_scalar():
    p = policy()
    waiting = request(p)
    assert request(p) == waiting
    assert request(p, now_ms=T0 + 120001) == waiting
    s = p.advance(Event.EOF, now_ms=T0 + 120002, generation=1)
    assert s.state is State.EOF_CANDIDATE and s.reason is Reason.EOF_CANDIDATE
    assert s.candidate_at_ms == T0 + 120002 and s.block_tx
    assert p.advance(Event.EOF, now_ms=T0 + 120002, generation=1) == s
    assert p.advance(Event.EOF, now_ms=T0 + 120003, generation=1) == s
    assert repr(p) == "EofQuarantinePolicy()"
    assert set(asdict(s)) == {
        "state",
        "reason",
        "block_tx",
        "generation",
        "deadline_ms",
        "candidate_at_ms",
    }
    assert all(
        v is None or type(v) in (bool, int, State, Reason) for v in asdict(s).values()
    )
    assert "recovered_120s" not in json.dumps(asdict(s))
    with pytest.raises(FrozenInstanceError):
        s.block_tx = False
    with pytest.raises(AttributeError):
        p.credentials = "synthetic-private"


@pytest.mark.parametrize(
    "order",
    list(
        itertools.permutations([Event.EOF, Event.TICK, Event.LOCAL_CLOSE, Event.CANCEL])
    ),
)
def test_all_eof_expiry_close_cancel_orders_end_without_candidate_or_rearm(order):
    p = policy(observation_deadline_ms=T0 + 130000)
    request(p)
    now = T0 + 120000
    sealed = None
    for event in order:
        now = max(now + 1, T0 + 130000) if event is Event.TICK else now + 1
        s = p.advance(event, now_ms=now, generation=1)
        assert s.block_tx
        if sealed is not None:
            assert s is sealed
        if s.state is State.REFUSED:
            sealed = s
    assert sealed is p.snapshot and sealed.candidate_at_ms is None
    assert request(p, now_ms=now + 1) is sealed


@pytest.mark.parametrize(
    "stop,reason",
    [
        (Event.LOCAL_CLOSE, Reason.LOCAL_STOP),
        (Event.CANCEL, Reason.CANCELLED),
        (Event.TX_IN_FLIGHT, Reason.TX_IN_FLIGHT),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_stop_wins_over_eof_even_at_equal_timestamp(stop, reason, reverse):
    p = policy()
    request(p)
    for event in [stop, Event.EOF] if reverse else [Event.EOF, stop]:
        s = p.advance(event, now_ms=T0 + 120001, generation=1)
    assert s.state is State.REFUSED and s.reason is reason
    assert s.candidate_at_ms is None and s.block_tx


@pytest.mark.parametrize("order", [(Event.EOF, Event.TICK), (Event.TICK, Event.EOF)])
@pytest.mark.parametrize(
    "delta,reason", [(120001, Reason.AMBIGUOUS), (300000, Reason.EXPIRED)]
)
def test_eof_timeout_ties_are_never_positive(order, delta, reason):
    p = policy()
    request(p)
    for event in order:
        s = p.advance(event, now_ms=T0 + delta, generation=1)
    assert s.state is State.REFUSED and s.reason is reason


@pytest.mark.parametrize(
    "event", [Event.LOCAL_CLOSE, Event.CANCEL, Event.TX_IN_FLIGHT, Event.TLS_FAILURE]
)
def test_prior_stop_or_non_eof_cannot_become_candidate(event):
    p = policy()
    s = p.advance(event, now_ms=T0 + 110000, generation=1)
    assert s.state is State.REFUSED and s.block_tx
    assert request(p) is s


@pytest.mark.parametrize(
    "now",
    [
        None,
        True,
        -1,
        T0 - 1,
        T0 + 119999,
        float("nan"),
        float("inf"),
        121000.0,
        MAX_TIME_MS + 1,
        "private",
        b"private",
    ],
)
def test_invalid_or_retrograde_event_time_revokes_candidate_without_echo(now):
    p = policy()
    request(p)
    assert (
        p.advance(Event.EOF, now_ms=T0 + 120001, generation=1).state
        is State.EOF_CANDIDATE
    )
    s = p.advance(Event.EOF, now_ms=now, generation=1)
    assert s.state is State.REFUSED and s.candidate_at_ms is None
    assert "private" not in repr(s)


def test_eof_at_request_timestamp_has_no_implied_order():
    p = policy()
    request(p)
    s = p.advance(Event.EOF, now_ms=T0 + 120000, generation=1)
    assert s.state is State.REFUSED and s.reason is Reason.AMBIGUOUS


@pytest.mark.parametrize("generation", [0, 2, 3, True, None, "1"])
def test_stale_generation_cannot_rearm_wait_or_candidate(generation):
    p = policy()
    request(p)
    p.advance(Event.EOF, now_ms=T0 + 120001, generation=1)
    s = p.advance(Event.EOF, now_ms=T0 + 120002, generation=generation)
    assert s.state is State.REFUSED and s.reason is Reason.STALE
    assert request(p, generation=1, now_ms=T0 + 120003) is s


@pytest.mark.parametrize("event", ["eof", b"eof", {}, None, Event.REQUEST])
def test_unknown_event_has_no_effectful_or_free_text_path(event):
    p = policy()
    request(p)
    s = p.advance(event, now_ms=T0 + 120001, generation=1)
    assert s.state is State.REFUSED and s.reason is Reason.INVALID


def test_time_domain_is_bounded_and_candidate_can_be_revoked_by_expiry():
    start = MAX_TIME_MS - 300000
    p = policy(
        accepted_at_ms=start,
        observation_deadline_ms=MAX_TIME_MS,
        process_deadline_ms=MAX_TIME_MS,
        suite_deadline_ms=MAX_TIME_MS,
    )
    request(p, now_ms=start + 120000)
    assert (
        p.advance(Event.EOF, now_ms=start + 120001, generation=1).state
        is State.EOF_CANDIDATE
    )
    s = p.advance(Event.TICK, now_ms=MAX_TIME_MS, generation=1)
    assert s.state is State.REFUSED and s.reason is Reason.EXPIRED


def test_foundation_imports_only_pure_stdlib_and_has_no_active_references():
    root = Path(__file__).resolve().parents[1]
    module = root / "custom_components/hoben/v4_eof_quarantine.py"
    tree = ast.parse(module.read_text())
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all(
        isinstance(n, ast.ImportFrom)
        and n.module in {"dataclasses", "enum"}
        and n.level == 0
        for n in imports
    )
    assert {n.module for n in imports} == {"dataclasses", "enum"}
    assert not any(
        isinstance(n, (ast.AsyncFunctionDef, ast.Await)) for n in ast.walk(tree)
    )
    for folder in ("custom_components", "scripts", ".github"):
        for file in (root / folder).rglob("*"):
            if file == module or file.suffix not in {
                ".py",
                ".js",
                ".cjs",
                ".yml",
                ".yaml",
            }:
                continue
            source = file.read_text()
            assert (
                "v4_eof_quarantine" not in source
                and "EofQuarantinePolicy" not in source
            ), file


def test_module_and_transitions_execute_without_io_capabilities(monkeypatch):
    file = (
        Path(__file__).resolve().parents[1]
        / "custom_components/hoben/v4_eof_quarantine.py"
    )
    code = compile(file.read_text(), "pure_policy", "exec")
    module = ModuleType("_pure_quarantine_policy")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    imported = []

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        assert level == 0 and name in {"dataclasses", "enum"}
        imported.append(name)
        return sys.modules[name]

    # No open, eval, exec, getattr, clock, filesystem, socket or environment API.
    module.__dict__["__builtins__"] = {
        name: getattr(builtins, name)
        for name in ("__build_class__", "property", "type", "int", "bool", "all", "min")
    } | {"__import__": importer}
    exec(code, module.__dict__)
    p = module.EofQuarantinePolicy(
        accepted_generation=1,
        accepted_at_ms=T0,
        observation_deadline_ms=T0 + 590000,
        process_deadline_ms=T0 + 600000,
        suite_deadline_ms=T0 + 1020000,
    )
    p.request(
        now_ms=T0 + 120000,
        generation=1,
        scenario=module.Scenario.RECONNECT,
        rejection=module.Rejection.CLOSE_CLIENT,
        suppressed_pongs=1,
        tx_in_flight=False,
        local_stop=False,
    )
    assert (
        p.advance(module.Event.EOF, now_ms=T0 + 120001, generation=1).state
        is module.State.EOF_CANDIDATE
    )
    assert (
        p.advance(module.Event.CANCEL, now_ms=T0 + 120001, generation=1).state
        is module.State.REFUSED
    )
    assert imported == ["dataclasses", "enum"]
