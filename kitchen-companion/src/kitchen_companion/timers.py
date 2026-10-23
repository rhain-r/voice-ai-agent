"""Kitchen timers that speak up on their own, plus the gate that keeps them from talking over anyone.

Clock, wall clock and sleeper are injectable so tests run instantly.
"""

# TimerService.list() shadows the builtin inside the class body; keep annotations unevaluated.
from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

TimerState = Literal["running", "due", "acknowledged", "cancelled"]
OnDue = Callable[[list["Timer"], bool], Awaitable[None]]


@dataclass
class Timer:
    id: str
    label: str
    minutes: float
    ends_at: float
    state: TimerState = "running"
    reminders: int = 0
    last_announced: float | None = None


@dataclass
class CancelResult:
    cancelled: list[Timer]
    ambiguous: list[str]


class TimerService:
    def __init__(
        self,
        on_due: OnDue,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        reminder_interval: float = 60.0,
        max_reminders: int = 3,
    ):
        self.on_due = on_due
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self.reminder_interval = reminder_interval
        self.max_reminders = max_reminders
        self._timers: dict[str, Timer] = {}
        self._ids = itertools.count(1)

    def list(self) -> list[Timer]:
        """Timers that are still running or ringing, in start order."""
        return [t for t in self._timers.values() if t.state in ("running", "due")]

    def start(self, minutes: float, label: str | None = None) -> Timer:
        taken = {t.label for t in self.list()}
        if label is None:
            n = 1
            while f"timer {n}" in taken:
                n += 1
            label = f"timer {n}"
        else:
            base, n = label.strip(), 2
            label = base
            while label in taken:
                label = f"{base} {n}"
                n += 1
        timer = Timer(id=f"t{next(self._ids)}", label=label, minutes=minutes,
                      ends_at=self._clock() + minutes * 60)
        self._timers[timer.id] = timer
        return timer

    def _matching(self, label: str | None) -> list[Timer]:
        active = self.list()
        if label is None:
            return active
        needle = label.strip().lower()
        return [t for t in active if needle in t.label.lower() or t.id == label]

    def cancel(self, label: str | None = None) -> CancelResult:
        matches = self._matching(label)
        if len(matches) > 1:
            return CancelResult(cancelled=[], ambiguous=[t.label for t in matches])
        for t in matches:
            t.state = "cancelled"
            del self._timers[t.id]
        return CancelResult(cancelled=matches, ambiguous=[])

    def remaining(self, label: str | None = None) -> list[tuple[Timer, float]]:
        now = self._clock()
        return [(t, max(0.0, t.ends_at - now)) for t in self._matching(label) if t.state == "running"]

    def acknowledge(self) -> list[Timer]:
        due = [t for t in self._timers.values() if t.state == "due"]
        for t in due:
            t.state = "acknowledged"
            del self._timers[t.id]
        return due

    async def tick(self) -> None:
        now = self._clock()
        newly_due = [t for t in self.list() if t.state == "running" and t.ends_at <= now]
        for t in newly_due:
            t.state = "due"
            t.last_announced = now
        if newly_due:
            await self.on_due(newly_due, False)

        reminders = [
            t for t in self._timers.values()
            if t.state == "due" and t not in newly_due and t.reminders < self.max_reminders
            and now - (t.last_announced or now) >= self.reminder_interval
        ]
        for t in reminders:
            t.reminders += 1
            t.last_announced = now
        if reminders:
            await self.on_due(reminders, True)

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("timer announcement failed")
            await self._sleep(0.25)

    def snapshot(self) -> list[dict]:
        now, wall = self._clock(), self._wall()
        return [
            {"id": t.id, "label": t.label, "state": t.state, "minutes": t.minutes,
             "ends_at_epoch": wall + (t.ends_at - now)}
            for t in self.list()
        ]


class AnnouncementGate:
    """Lets a timer announcement through only once neither the user nor the bot is talking."""

    def __init__(self) -> None:
        self._user = False
        self._bot = False
        self._clear = asyncio.Event()
        self._clear.set()

    def _update(self) -> None:
        if self._user or self._bot:
            self._clear.clear()
        else:
            self._clear.set()

    def set_user_speaking(self, speaking: bool) -> None:
        self._user = speaking
        self._update()

    def set_bot_speaking(self, speaking: bool) -> None:
        self._bot = speaking
        self._update()

    async def wait_clear(self, timeout: float | None = None) -> bool:
        """True once both are quiet; False if the timeout ran out first (announce anyway)."""
        try:
            await asyncio.wait_for(self._clear.wait(), timeout)
            return True
        except TimeoutError:
            return False


def timer_phrase(label: str) -> str:
    """"rice" -> "rice timer", but a default label like "timer 2" is already a timer."""
    return label if label.lower().startswith("timer") else f"{label} timer"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def announcement_text(labels: list[str], next_step: str | None, reminder: bool) -> str:
    if any(label.lower().startswith("timer") for label in labels):
        names = _join([timer_phrase(label) for label in labels])
    else:
        names = _join(labels) + (" timer" if len(labels) == 1 else " timers")
    if reminder:
        return f"Reminder: your {names} went off."
    verb = "is" if len(labels) == 1 else "are"
    text = f"Your {names} {verb} done."
    if next_step:
        text += f" Next up: {next_step}"
    return text
