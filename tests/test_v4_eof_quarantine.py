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
    RecoveryTiming,
    Rejection,
    Scenario,
    State,
    TimingCheck,
    check_recovery_timing,
)

T0 = 1000


def timing(**changes):
    return RecoveryTiming(
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


def calculation(t=None, **changes):
    return check_recovery_timing(
        timing() if t is None else t,
        **(
            {
                "suppressed_at_ms": T0 + 120000,
                "eof_at_ms": T0 + 180000,
                "reopened_at_ms": T0 + 200000,
                "pong_at_ms": T0 + 201000,
                "read_at_ms": T0 + 260000,
                "stable_until_ms": T0 + 320000,
                "reopened_generation": 2,
                "stable_generation": 2,
                "loss_or_stop": False,
                "ambiguous_order": False,
            }
            | changes
        ),
    )


def test_immutable_contract_has_fixed_relative_milestones_and_no_success():
    t = timing()
    assert t.suppress_at_ms == T0 + 120000
    assert t.diagnostic_at_ms == T0 + 150000
    assert t.recovery_deadline_ms == T0 + 240000
    assert t.functional_deadline_ms == T0 + 360000
    assert all(type(v) is int for v in asdict(t).values())
    with pytest.raises(FrozenInstanceError):
        t.accepted_at_ms = 0
    assert calculation(t) is TimingCheck.COMPATIBLE_CALCULATION_ONLY
    assert "recovered_120s" not in json.dumps(asdict(t))


@pytest.mark.parametrize("milestone", [120000, 150000, 240000, 360000])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_calculations_at_every_milestone(milestone, offset):
    t = timing()
    now = T0 + milestone + offset
    # A threshold is arithmetic only: before 150 diagnostics would not yet
    # be due. At/after 150 they would be due, without starting instrumentation.
    assert (now >= t.diagnostic_at_ms) == (milestone + offset >= 150000)
    result = calculation(
        t,
        suppressed_at_ms=now,
        eof_at_ms=now + 1,
        reopened_at_ms=now + 2,
        pong_at_ms=now + 3,
        read_at_ms=now + 4,
        stable_until_ms=now + 120002,
    )
    expected = (
        TimingCheck.COMPATIBLE_CALCULATION_ONLY
        if 120000 <= milestone + offset < 239998
        else TimingCheck.INCOMPATIBLE
    )
    assert result is expected


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_reopening_must_precede_240_even_with_early_eof(offset):
    opened = T0 + 240000 + offset
    result = calculation(
        reopened_at_ms=opened,
        pong_at_ms=opened + 1,
        read_at_ms=opened + 2,
        stable_until_ms=opened + 120000,
    )
    assert result is (
        TimingCheck.COMPATIBLE_CALCULATION_ONLY
        if offset < 0
        else TimingCheck.INCOMPATIBLE
    )


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_functional_end_before_360_and_full_stability_required(offset):
    assert calculation(stable_until_ms=T0 + 360000 + offset) is (
        TimingCheck.COMPATIBLE_CALCULATION_ONLY
        if offset < 0
        else TimingCheck.INCOMPATIBLE
    )
    assert calculation(stable_until_ms=T0 + 320000 + offset) is (
        TimingCheck.INCOMPATIBLE
        if offset < 0
        else TimingCheck.COMPATIBLE_CALCULATION_ONLY
    )


@pytest.mark.parametrize(
    "key", ["observation_deadline_ms", "process_deadline_ms", "suite_deadline_ms"]
)
def test_each_budget_can_shorten_recovery_and_prevent_full_stability(key):
    t = timing(**{key: T0 + 220000})
    assert t.recovery_deadline_ms == t.functional_deadline_ms == T0 + 220000
    assert calculation(t) is TimingCheck.INCOMPATIBLE
    t = timing(**{key: T0 + 320000})
    assert calculation(t) is TimingCheck.INCOMPATIBLE  # Deadline tie.
    assert calculation(timing(**{key: T0 + 320001})) is (
        TimingCheck.COMPATIBLE_CALCULATION_ONLY
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"suppressed_at_ms": T0 + 119999},
        {"eof_at_ms": T0 + 120000},  # No known suppression/EOF order.
        {"eof_at_ms": T0 + 119999},
        {"eof_at_ms": T0 + 240000},
        {"reopened_at_ms": T0 + 179999},  # Retrograde sequence.
        {"reopened_at_ms": T0 + 180000},  # EOF/open tie.
        {"pong_at_ms": T0 + 199999},
        {"read_at_ms": T0 + 320001},
        {"stable_until_ms": T0 + 319999},
        {"reopened_generation": 1},
        {"reopened_generation": 4},
        {"stable_generation": 1},
        {"stable_generation": 3},
        {"loss_or_stop": True},
        {"ambiguous_order": True},
    ],
)
def test_missing_order_generation_stability_or_second_loss_never_compatible(changes):
    assert calculation(**changes) is TimingCheck.INCOMPATIBLE


@pytest.mark.parametrize(
    "key",
    [
        "suppressed_at_ms",
        "eof_at_ms",
        "reopened_at_ms",
        "pong_at_ms",
        "read_at_ms",
        "stable_until_ms",
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
        MAX_TIME_MS + 1,
        "private",
        b"private",
        {},
    ],
)
def test_calculation_rejects_invalid_or_missing_event_times(key, value):
    result = calculation(**{key: value})
    assert result is TimingCheck.INVALID
    assert "private" not in repr(result)


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
        MAX_TIME_MS + 1,
        "private",
        b"private",
        {},
    ],
)
def test_contract_rejects_invalid_time_without_echo(key, value):
    with pytest.raises(ValueError, match="^Invalid recovery timing$"):
        timing(**{key: value})


@pytest.mark.parametrize(
    "changes",
    [{"accepted_generation": v} for v in (True, 0, 2, None, "1")]
    + [
        {"accepted_at_ms": MAX_TIME_MS - 359999},
        {"observation_deadline_ms": T0},
        {"process_deadline_ms": T0 - 1},
        {"suite_deadline_ms": T0},
    ],
)
def test_contract_rejects_unknown_first_generation_or_overflow(changes):
    with pytest.raises(ValueError, match="^Invalid recovery timing$"):
        timing(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"reopened_generation": True},
        {"stable_generation": 2.0},
        {"loss_or_stop": 0},
        {"ambiguous_order": None},
    ],
)
def test_closed_declarations_require_exact_types(changes):
    assert calculation(**changes) is TimingCheck.INVALID
    assert calculation("private") is TimingCheck.INVALID


def test_contract_at_largest_safe_t0_keeps_calculation_bounded():
    start = MAX_TIME_MS - 360000
    t = timing(
        accepted_at_ms=start,
        observation_deadline_ms=MAX_TIME_MS,
        process_deadline_ms=MAX_TIME_MS,
        suite_deadline_ms=MAX_TIME_MS,
    )
    assert t.functional_deadline_ms == MAX_TIME_MS
    assert (
        check_recovery_timing(
            t,
            suppressed_at_ms=start + 120000,
            eof_at_ms=start + 150000,
            reopened_at_ms=start + 239999,
            pong_at_ms=start + 240000,
            read_at_ms=start + 300000,
            stable_until_ms=MAX_TIME_MS - 1,
            reopened_generation=2,
            stable_generation=2,
            loss_or_stop=False,
            ambiguous_order=False,
        )
        is TimingCheck.COMPATIBLE_CALCULATION_ONLY
    )


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
        (239999, State.WAITING, Reason.NONE),
        (240000, State.REFUSED, Reason.EXPIRED),
        (240001, State.REFUSED, Reason.EXPIRED),
    ],
)
def test_fixed_eligibility_boundaries(delta, state, reason):
    p = policy()
    assert p.snapshot.state is State.READY and not p.snapshot.block_tx
    s = request(p, now_ms=T0 + delta)
    assert s.state is state and s.reason is reason and s.block_tx
    assert s.deadline_ms == T0 + 240000


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
        {"accepted_at_ms": MAX_TIME_MS - 239999},
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
    "delta,reason", [(120001, Reason.AMBIGUOUS), (240000, Reason.EXPIRED)]
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
    start = MAX_TIME_MS - 240000
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
                and "RecoveryTiming" not in source
                and "check_recovery_timing" not in source
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
        for name in (
            "__build_class__",
            "property",
            "type",
            "int",
            "bool",
            "all",
            "min",
            "ValueError",
        )
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
    t = module.RecoveryTiming(
        accepted_generation=1,
        accepted_at_ms=T0,
        observation_deadline_ms=T0 + 590000,
        process_deadline_ms=T0 + 600000,
        suite_deadline_ms=T0 + 1020000,
    )
    assert (
        module.check_recovery_timing(
            t,
            suppressed_at_ms=T0 + 120000,
            eof_at_ms=T0 + 180000,
            reopened_at_ms=T0 + 200000,
            pong_at_ms=T0 + 201000,
            read_at_ms=T0 + 260000,
            stable_until_ms=T0 + 320000,
            reopened_generation=2,
            stable_generation=2,
            loss_or_stop=False,
            ambiguous_order=False,
        )
        is module.TimingCheck.COMPATIBLE_CALCULATION_ONLY
    )
    assert imported == ["dataclasses", "enum"]
