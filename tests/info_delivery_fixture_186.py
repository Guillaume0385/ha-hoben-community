"""Explicit memory/clock injection; only this fixture drives the real session."""

import asyncio
from types import SimpleNamespace

from custom_components.hoben.v4_session import SessionState
from scripts.info_delivery_scenario import (
    InfoDeliveryScenario,
    InvalidInfoEvidence,
    OfflineTransportLedger,
    error_category,
)
from tests.test_data_updated_silence import Clock, pump
from tests.test_info_delivery_drop_186 import owner
from tests.tls_read_candidate_186 import PING, RESPONSE


async def run_case(
    monkeypatch,
    *,
    deliveries=(b"\x0c", PING),
    replies=(RESPONSE,),
    enabled=True,
    limit=3,
    suffix=b"",
    close_error=None,
    cancel=False,
    duplicate_open=False,
    before_drop_read=False,
    close_delay=0,
    delivery_delay=0,
):
    """No wall-clock waits; existing owner() injects Stream and private opt-in."""
    clock = Clock(monkeypatch)
    session, wire, factory = owner(
        list(replies), enabled=enabled, limit=limit, suffix=suffix
    )
    ledger = OfflineTransportLedger(wire)
    scenario = InfoDeliveryScenario(session, ledger, clock=lambda: clock.now)
    original_connect, original_read = wire.connect, wire.read
    original_write, original_close = wire.write, wire.close

    async def connect():
        ledger.note("connect")
        await original_connect()

    async def read(*args, **kwargs):
        data = await original_read(*args, **kwargs)
        if kwargs.get("bounded", True):
            kind = "opening"
        elif data[:1] == b"\x0c":
            kind = "info_candidate"
        else:
            kind = "ping" if data == PING else "other"
        ledger.note(kind, len(data))
        return data

    async def write(data):
        # Independent read-only vector; never retain or export the packet.
        assert data[:1] == b"\x03" or data in (
            b"\x0b",
            bytes.fromhex("0dffff00000006010404000014"),
        )
        if data[0] == 13:
            ledger.note("request")
        await original_write(data)
        if data[0] == 13:
            ledger.note("request_completed")
        elif data == b"\x0b":
            ledger.note("pong")

    async def close():
        if close_delay:
            await asyncio.sleep(close_delay)
        if close_error is not None:
            wire.close_count += 1
            raise close_error
        await original_close()
        ledger.note("close_completed")

    wire.connect, wire.read, wire.write, wire.close = connect, read, write, close

    async def drive():
        try:
            async with asyncio.timeout(30):
                await session.connect()
                await pump()
                scenario.sample()
                if before_drop_read:
                    await session.request_v4_data(timeout=5)
                    await pump()
                    scenario.sample()
                if duplicate_open:
                    # A fixture-supplied second connection event must be refused;
                    # the scenario never opens a second transport to exercise it.
                    ledger.note("connect")
                for item in deliveries:
                    if delivery_delay:
                        await asyncio.sleep(delivery_delay)
                    wire.queue.put_nowait(item)
                    await pump()
                    scenario.sample()
                    if session._rx_error is not None:
                        break
                if session.state is SessionState.CONNECTED and not before_drop_read:
                    request = asyncio.create_task(session.request_v4_data(timeout=5))
                    if cancel:
                        await pump()
                        request.cancel()
                    await request
                    await pump()
                    scenario.sample()
        except asyncio.CancelledError:
            scenario.fail("cancelled")
        except Exception as error:
            scenario.fail(error_category(error))
        finally:
            try:
                scenario.sample()
            except InvalidInfoEvidence:
                scenario.fail("evidence_gap")
            scenario.begin_cleanup()
            try:
                async with asyncio.timeout(5):
                    await session.abort()
            except asyncio.CancelledError:
                scenario.fail("cancelled")
            except Exception:
                scenario.fail("cleanup_unproven")
        return scenario.finish()

    task = asyncio.create_task(drive())
    try:
        for _ in range(702):  # Absolute 35.1 s fixture guard, never a resettable retry.
            await clock.advance(0.05)
            if task.done():
                return SimpleNamespace(
                    report=task.result(),
                    session=session,
                    wire=wire,
                    factory=factory,
                    ledger=ledger,
                )
        raise AssertionError("offline_fixture_global_budget")
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
