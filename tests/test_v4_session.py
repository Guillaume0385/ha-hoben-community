"""Pure Python, offline acceptance tests for the V4 session skeleton."""

import asyncio
from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from custom_components.hoben.v4_session import (
    SessionNotImplementedError,
    SessionSnapshot,
    SessionState,
    SessionStateError,
    V4Session,
)


def session_in(state):
    """Reach internal test states through legal lifecycle edges, without I/O."""
    factory = Mock(side_effect=AssertionError("factory must stay unused"))
    session = V4Session(transport_factory=factory)
    if state in (
        SessionState.CONNECTING,
        SessionState.CONNECTED,
        SessionState.RECONNECTING,
    ):
        session._transition(SessionState.CONNECTING)
    if state in (SessionState.CONNECTED, SessionState.RECONNECTING):
        session._transition(SessionState.CONNECTED)
    if state is SessionState.RECONNECTING:
        session._transition(SessionState.RECONNECTING)
    if state is SessionState.CLOSED:
        asyncio.run(session.close())
    return session, factory


@pytest.mark.parametrize("state", list(SessionState))
def test_close_is_terminal_idempotent_and_does_not_acquire_transport(state):
    session, factory = session_in(state)
    previous = session.snapshot

    async def close_twice():
        await session.close()
        closed = session.snapshot
        await session.close()
        assert session.snapshot is closed

    asyncio.run(close_twice())
    assert session.state is SessionState.CLOSED
    assert previous.state is state
    factory.assert_not_called()


@pytest.mark.parametrize("source", list(SessionState))
@pytest.mark.parametrize("target", list(SessionState))
def test_transition_guard(source, target):
    session, factory = session_in(source)
    previous = session.snapshot
    allowed = (
        source is SessionState.DISCONNECTED
        and target is SessionState.CONNECTING
        or source in (SessionState.CONNECTING, SessionState.RECONNECTING)
        and target in (SessionState.CONNECTED, SessionState.DISCONNECTED)
        or source is SessionState.CONNECTED
        and target in (SessionState.RECONNECTING, SessionState.DISCONNECTED)
        or source is not SessionState.CLOSED
        and target is SessionState.CLOSED
    )
    if allowed:
        session._transition(target)
        assert session.state is target
        assert previous.state is source
    else:
        with pytest.raises(SessionStateError, match="^invalid_session_state$"):
            session._transition(target)
        assert session.snapshot is previous
    factory.assert_not_called()


@pytest.mark.parametrize("state", list(SessionState))
def test_unimplemented_operations_never_succeed_or_change_state(state):
    session, factory = session_in(state)
    previous = session.snapshot

    async def operations():
        connect_error = (
            SessionNotImplementedError
            if state is SessionState.DISCONNECTED
            else SessionStateError
        )
        read_error = (
            SessionNotImplementedError
            if state is SessionState.CONNECTED
            else SessionStateError
        )
        with pytest.raises(connect_error):
            await session.connect()
        with pytest.raises(read_error):
            await session.request_v4_data()

    asyncio.run(operations())
    assert session.snapshot is previous
    factory.assert_not_called()


def test_snapshot_and_public_state_cannot_be_mutated():
    session, _ = session_in(SessionState.DISCONNECTED)
    assert session.snapshot == SessionSnapshot(SessionState.DISCONNECTED)
    with pytest.raises(FrozenInstanceError):
        session.snapshot.state = SessionState.CONNECTED
    with pytest.raises(AttributeError):
        session.state = SessionState.CONNECTED
    with pytest.raises(AttributeError):
        session.snapshot = SessionSnapshot(SessionState.CONNECTED)
    with pytest.raises(SessionStateError):
        session._transition("connecting")


def test_private_dependency_never_appears_in_repr_errors_or_logs(caplog):
    sentinel = "synthetic-private-dependency-marker"
    factory = Mock(name=sentinel)
    session = V4Session(transport_factory=factory)
    assert session._transport_factory is factory
    assert repr(session) == "V4Session(state=disconnected)"
    with pytest.raises(SessionNotImplementedError) as error:
        asyncio.run(session.connect())
    assert sentinel not in repr(session.snapshot) + repr(error.value) + caplog.text
    assert not caplog.records
    factory.assert_not_called()


def test_invalid_factory_is_rejected_without_echoing_input():
    with pytest.raises(TypeError, match="^transport_factory_must_be_callable$"):
        V4Session(transport_factory="synthetic-private-input")
