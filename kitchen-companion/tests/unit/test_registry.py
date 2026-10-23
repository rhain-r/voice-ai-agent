import asyncio
import re

import pytest

from kitchen_companion.registry import KITCHEN_ID_RE, KitchenRegistry


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
async def registry():
    clock = FakeClock()
    reg = KitchenRegistry(ttl_s=6 * 3600, clock=clock)
    reg.clock = clock
    yield reg
    await reg.close()


async def test_registry_reuses_kitchen(registry):
    a = registry.get_or_create("kitchen-abc123")
    b = registry.get_or_create("kitchen-abc123")
    assert a is b
    assert registry.get_or_create("kitchen-xyz789") is not a
    assert a.task is not None and not a.task.done()  # the timer loop is running


async def test_registry_prunes_after_ttl(registry):
    kitchen = registry.get_or_create("kitchen-abc123")
    registry.clock.now += 6 * 3600 - 1
    assert registry.prune() == []
    registry.clock.now += 2
    assert registry.prune() == ["kitchen-abc123"]
    await asyncio.sleep(0)
    assert kitchen.task.cancelled() or kitchen.task.done()
    assert registry.get_or_create("kitchen-abc123") is not kitchen


async def test_registry_never_prunes_attached_kitchen(registry):
    kitchen = registry.get_or_create("kitchen-abc123")

    async def announce(timers, is_reminder):
        pass

    await kitchen.attach(announce)
    registry.clock.now += 7 * 3600
    assert registry.prune() == []
    kitchen.detach(announce)  # the TTL counts from the last disconnect
    assert registry.prune() == []
    registry.clock.now += 6 * 3600 + 1
    assert registry.prune() == ["kitchen-abc123"]


async def test_due_while_detached_is_queued_then_flushed(registry):
    kitchen = registry.get_or_create("kitchen-abc123")
    pasta = kitchen.timers.start(1, "pasta")
    rice = kitchen.timers.start(2, "rice")
    await kitchen.on_due([pasta], False)
    await kitchen.on_due([rice], False)
    heard = []

    async def announce(timers, is_reminder):
        heard.append(([t.label for t in timers], is_reminder))

    await kitchen.attach(announce)
    assert heard == [(["pasta"], False), (["rice"], False)]
    await kitchen.on_due([pasta], True)
    assert heard[-1] == (["pasta"], True)


async def test_detached_reminders_for_queued_timers_are_dropped(registry):
    kitchen = registry.get_or_create("kitchen-abc123")
    pasta = kitchen.timers.start(1, "pasta")
    await kitchen.on_due([pasta], False)
    await kitchen.on_due([pasta], True)
    await kitchen.on_due([pasta], True)
    heard = []

    async def announce(timers, is_reminder):
        heard.append(([t.label for t in timers], is_reminder))

    await kitchen.attach(announce)
    assert heard == [(["pasta"], False)]


async def test_stale_detach_keeps_new_connection(registry):
    kitchen = registry.get_or_create("kitchen-abc123")
    heard = []

    async def old(timers, is_reminder):
        heard.append("old")

    async def new(timers, is_reminder):
        heard.append("new")

    await kitchen.attach(old)
    await kitchen.attach(new)  # the tablet reconnected before the old peer noticed it was gone
    kitchen.detach(old)
    await kitchen.on_due([kitchen.timers.start(1, "pasta")], False)
    assert heard == ["new"]


@pytest.mark.parametrize(
    "kid,ok",
    [
        ("kitchen-abc123", True),
        ("A1b2C3d4_-xyz", True),
        ("short", False),
        ("has space here", False),
        ("x" * 65, False),
        ("../../etc", False),
    ],
)
def test_kitchen_id_re(kid, ok):
    assert bool(re.match(KITCHEN_ID_RE, kid)) is ok


async def test_reminders_not_spent_while_nobody_is_listening(registry):
    kitchen = registry.get_or_create("kitchen-abc123")
    pasta = kitchen.timers.start(1, "pasta")
    pasta.state, pasta.reminders = "due", 0
    await kitchen.on_due([pasta], False)
    for _ in range(3):  # TimerService counts each reminder before calling on_due
        pasta.reminders += 1
        await kitchen.on_due([pasta], True)
    assert pasta.reminders == 0  # all three are still owed to the next connection
