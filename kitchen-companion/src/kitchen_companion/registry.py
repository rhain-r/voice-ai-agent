"""Per-kitchen state that outlives any one WebRTC connection.

The tablet keeps a `kitchen_id` in localStorage. Its recipe position and running timers live here,
so a dropped connection (tablet asleep, Wi-Fi blip) reattaches to the same kitchen. Timer
announcements that come due while nobody is connected wait for the next connection.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from kitchen_companion.recipes.state import RecipeSession
from kitchen_companion.timers import Timer, TimerService

logger = logging.getLogger(__name__)

KITCHEN_ID_RE = r"^[A-Za-z0-9_-]{8,64}$"
DEFAULT_TTL_S = 6 * 3600

Announce = Callable[[list[Timer], bool], Awaitable[None]]


class Kitchen:
    def __init__(self, kitchen_id: str, clock: Callable[[], float] = time.monotonic):
        self.id = kitchen_id
        self._clock = clock
        self.recipe = RecipeSession()
        self.timers = TimerService(self.on_due)
        self.last_seen = clock()
        self.task: asyncio.Task | None = None
        self._announce: Announce | None = None
        self._pending: list[tuple[list[Timer], bool]] = []

    @property
    def attached(self) -> bool:
        return self._announce is not None

    async def attach(self, announce: Announce) -> None:
        """Route announcements to this connection, first replaying any that came due while detached."""
        self._announce = announce
        self.last_seen = self._clock()
        pending, self._pending = self._pending, []
        for timers, is_reminder in pending:
            await announce(timers, is_reminder)

    def detach(self, announce: Announce | None = None) -> None:
        """Stop announcing. A stale connection's detach doesn't unhook the one that replaced it."""
        if announce is not None and announce is not self._announce:
            return
        self._announce = None
        self.last_seen = self._clock()

    async def on_due(self, timers: list[Timer], is_reminder: bool) -> None:
        if self._announce is not None:
            await self._announce(timers, is_reminder)
            return
        if is_reminder:
            queued = {t.id for batch, _ in self._pending for t in batch}
            if all(t.id in queued for t in timers):
                return  # the queued "is done" already covers it
        self._pending.append((timers, is_reminder))


class KitchenRegistry:
    def __init__(self, ttl_s: float = DEFAULT_TTL_S, clock: Callable[[], float] = time.monotonic):
        self._ttl_s = ttl_s
        self._clock = clock
        self._kitchens: dict[str, Kitchen] = {}

    def get_or_create(self, kitchen_id: str) -> Kitchen:
        self.prune()
        kitchen = self._kitchens.get(kitchen_id)
        if kitchen is None:
            kitchen = Kitchen(kitchen_id, clock=self._clock)
            kitchen.task = asyncio.get_running_loop().create_task(
                kitchen.timers.run(), name=f"timers-{kitchen_id}"
            )
            self._kitchens[kitchen_id] = kitchen
            logger.info("new kitchen %s", kitchen_id)
        kitchen.last_seen = self._clock()
        return kitchen

    def prune(self) -> list[str]:
        """Forget kitchens nobody has been connected to for longer than the TTL."""
        now = self._clock()
        stale = [
            kid for kid, k in self._kitchens.items() if not k.attached and now - k.last_seen > self._ttl_s
        ]
        for kid in stale:
            kitchen = self._kitchens.pop(kid)
            if kitchen.task:
                kitchen.task.cancel()
            logger.info("pruned kitchen %s", kid)
        return stale

    async def close(self) -> None:
        tasks = [k.task for k in self._kitchens.values() if k.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._kitchens.clear()
