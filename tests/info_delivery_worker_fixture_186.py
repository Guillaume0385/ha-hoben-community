"""Only fixtures provide private capability, synthetic identity and loop clock."""

import asyncio
import math
from types import SimpleNamespace

from custom_components.hoben.v4_session import (
    V4Session,
    V4SessionMode,
    _InfoDeliveryDropExperiment,
)
from scripts.info_delivery_memory import MemoryFactory, MemoryTransport, OfflineClock
from scripts.info_delivery_worker import run_offline_worker
from tests.test_data_updated_silence import pump
from tests.test_v4_session import opened_prefix
from tests.tls_read_candidate_186 import RESPONSE


async def run_worker_case(
    monkeypatch,
    *,
    plan=((1000, b"\x0c"), (1100, b"\x0a")),
    replies=(RESPONSE,),
    enabled=True,
    suffix=b"",
    close_ms=0,
    close_fails=False,
    close_ack=True,
    cancel_at=None,
    repeat_cancel=False,
):
    loop = asyncio.get_running_loop()
    clock = OfflineClock(origin=0)
    monkeypatch.setattr(loop, "time", clock.loop_time)
    wire = MemoryTransport(
        opening=opened_prefix() + suffix,
        replies=replies,
        close_ms=close_ms,
        close_fails=close_fails,
    )
    if not close_ack:

        async def incomplete_close(self):
            self.close_count += 1
            # Deliberately no close completion. Returning/abort is NOT proof.

        monkeypatch.setattr(MemoryTransport, "close", incomplete_close)
    factory = MemoryFactory(wire)
    options = (
        {"_info_delivery_drop": _InfoDeliveryDropExperiment(limit=3)} if enabled else {}
    )
    session = V4Session(
        user_guid="b" * 32,
        mode=V4SessionMode.PERSISTENT,
        transport_factory=factory,
        classify_frame_boundary=True,
        **options,
    )
    task = asyncio.create_task(run_offline_worker(session=session, clock=clock))
    pending = list(plan)
    cancelled = False
    try:
        for _ in range(1024):
            await pump()
            if task.done():
                return SimpleNamespace(
                    report=task.result(),
                    session=session,
                    wire=wire,
                    clock=clock,
                    factory=factory,
                )
            times = [
                deadline for deadline, future in clock._waiters if not future.done()
            ]
            times.extend(
                math.ceil((h.when() - clock._origin) * 1000) + 1
                for h in loop._scheduled
                if not h.cancelled()
            )
            if pending:
                times.append(pending[0][0])
            if cancel_at is not None and not cancelled:
                times.append(cancel_at)
            assert times, "offline_worker_stalled"
            at = max(clock.now_ms, min(times))
            assert at <= 3_600_001, "offline_worker_global_budget"
            clock.advance_to(at)
            while pending and pending[0][0] <= at:
                _, data = pending.pop(0)
                wire.feed(data)
            if cancel_at is not None and at >= cancel_at and not cancelled:
                task.cancel()
                cancelled = True
                await pump()
                if repeat_cancel and not task.done():
                    task.cancel()
        raise AssertionError("offline_worker_event_budget")
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
