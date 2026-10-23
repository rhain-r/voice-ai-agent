import asyncio

import pytest

from kitchen_companion.timers import (
    AnnouncementGate,
    TimerService,
    announcement_text,
    speak_duration,
    timer_phrase,
)


class FakeClock:
    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clk() -> FakeClock:
    return FakeClock()


@pytest.fixture
def calls() -> list:
    return []


@pytest.fixture
def t(clk, calls) -> TimerService:
    async def on_due(timers, is_reminder):
        calls.append(([x.label for x in timers], is_reminder))

    return TimerService(on_due, clock=clk, wall=lambda: 1000.0 + clk.now)


async def test_fires_once_when_due(t, clk, calls):
    t.start(1, "pasta")
    clk.now = 59
    await t.tick()
    assert calls == []
    clk.now = 60
    await t.tick()
    assert calls == [(["pasta"], False)]
    clk.now = 61
    await t.tick()
    assert calls == [(["pasta"], False)]
    assert t.list()[0].state == "due"


async def test_simultaneous_timers_one_announcement(t, clk, calls):  # Review Focus 3
    t.start(1, "pasta")
    t.start(1, "garlic")
    clk.now = 60
    await t.tick()
    assert calls == [(["pasta", "garlic"], False)]


async def test_reminders_capped(t, clk, calls):
    t.start(1, "pasta")
    for now in (60, 120, 180, 240, 300, 360, 420):
        clk.now = now
        await t.tick()
    assert calls == [(["pasta"], False)] + [(["pasta"], True)] * 3


async def test_reminder_waits_full_interval(t, clk, calls):
    t.start(1, "pasta")
    clk.now = 60
    await t.tick()
    clk.now = 119.9
    await t.tick()
    assert len(calls) == 1


async def test_acknowledge_stops_reminders(t, clk, calls):
    t.start(1, "pasta")
    clk.now = 60
    await t.tick()
    acked = t.acknowledge()
    assert [x.label for x in acked] == ["pasta"]
    for now in (120, 180, 240):
        clk.now = now
        await t.tick()
    assert calls == [(["pasta"], False)]
    assert t.list() == []
    assert t.acknowledge() == []


def test_cancel_ambiguous(t):  # Review Focus 4
    t.start(5, "pasta")
    t.start(3, "sauce")
    r = t.cancel()
    assert r.cancelled == [] and r.ambiguous == ["pasta", "sauce"]
    assert len(t.list()) == 2


def test_cancel_by_label_substring(t):
    t.start(5, "onions")
    t.start(3, "sauce")
    r = t.cancel("Onion")
    assert [x.label for x in r.cancelled] == ["onions"] and r.ambiguous == []
    assert [x.label for x in t.list()] == ["sauce"]


def test_cancel_single_and_none(t):
    assert t.cancel().cancelled == []
    t.start(5, "pasta")
    assert [x.label for x in t.cancel().cancelled] == ["pasta"]
    assert t.cancel("pasta").cancelled == []


def test_default_and_duplicate_labels(t):
    labels = [t.start(1).label, t.start(1).label, t.start(1, "rice").label, t.start(1, "rice").label]
    assert labels == ["timer 1", "timer 2", "rice", "rice 2"]


def test_remaining(t, clk):
    t.start(2, "pasta")
    t.start(5, "sauce")
    clk.now = 30
    assert [(x.label, secs) for x, secs in t.remaining()] == [("pasta", 90.0), ("sauce", 270.0)]
    assert [(x.label, secs) for x, secs in t.remaining("sau")] == [("sauce", 270.0)]


async def test_on_due_error_does_not_stop_run(clk):
    seen = []

    async def on_due(timers, is_reminder):
        seen.append(is_reminder)
        raise RuntimeError("speaker unplugged")

    sleeps = []

    async def sleeper(s):
        sleeps.append(s)
        clk.now += 60
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    svc = TimerService(on_due, clock=clk, sleep=sleeper)
    svc.start(1, "pasta")
    with pytest.raises(asyncio.CancelledError):
        await svc.run()
    assert seen == [False, True]
    assert sleeps == [0.25, 0.25, 0.25]


async def test_announcement_waits_for_user():
    g = AnnouncementGate()
    g.set_user_speaking(True)
    w = asyncio.create_task(g.wait_clear())
    await asyncio.sleep(0)
    assert not w.done()
    g.set_user_speaking(False)
    await asyncio.wait_for(w, 1)


async def test_announcement_waits_for_bot():  # Review Focus 2
    g = AnnouncementGate()
    g.set_bot_speaking(True)
    w = asyncio.create_task(g.wait_clear())
    await asyncio.sleep(0)
    assert not w.done()
    g.set_user_speaking(True)
    g.set_bot_speaking(False)
    await asyncio.sleep(0)
    assert not w.done()  # the user is still talking
    g.set_user_speaking(False)
    await asyncio.wait_for(w, 1)


async def test_announcement_gate_timeout_returns():
    g = AnnouncementGate()
    g.set_user_speaking(True)
    assert await g.wait_clear(timeout=0.01) is False
    g.set_user_speaking(False)
    assert await g.wait_clear(timeout=0.01) is True


def test_announcement_text_one_label():
    assert announcement_text(["pasta"], None, False) == "Your pasta timer is done."


def test_announcement_text_two_labels():
    assert announcement_text(["pasta", "garlic"], None, False) == "Your pasta and garlic timers are done."


def test_announcement_text_three_labels():
    assert announcement_text(["pasta", "garlic", "rice"], None, False) == (
        "Your pasta, garlic and rice timers are done."
    )


def test_announcement_text_next_step():
    assert announcement_text(["onions"], "add the garlic.", False) == (
        "Your onions timer is done. Next up: add the garlic."
    )


def test_announcement_text_reminder():
    assert announcement_text(["pasta"], "add the garlic.", True) == "Reminder: your pasta timer went off."
    assert (
        announcement_text(["pasta", "rice"], None, True) == "Reminder: your pasta and rice timers went off."
    )


def test_announcement_text_default_labels():
    assert announcement_text(["timer 1"], None, False) == "Your timer 1 is done."
    assert announcement_text(["pasta", "timer 2"], None, False) == "Your pasta timer and timer 2 are done."
    assert timer_phrase("timer 3") == "timer 3" and timer_phrase("rice") == "rice timer"


def test_snapshot_epoch(clk):
    async def on_due(timers, is_reminder):
        pass

    svc = TimerService(on_due, clock=clk, wall=lambda: 1000.0)
    timer = svc.start(2)
    assert svc.snapshot() == [
        {"id": timer.id, "label": "timer 1", "state": "running", "minutes": 2, "ends_at_epoch": 1120.0}
    ]


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (480, "eight minutes"),
        (90, "one minute and thirty seconds"),
        (60, "one minute"),
        (45, "forty-five seconds"),
        (1, "one second"),
        (0.4, "less than a second"),
        (3600, "one hour"),
        (5400, "one hour and thirty minutes"),
        (299.6, "five minutes"),
    ],
)
def test_speak_duration(seconds, expected):
    assert speak_duration(seconds) == expected
