"""Shared test doubles: a recording event sink and a small loaded recipe."""

from pipecat.frames.frames import TranscriptionFrame

from kitchen_companion.recipes.ingredients import parse_ingredient
from kitchen_companion.recipes.model import Recipe, Step
from kitchen_companion.recipes.state import RecipeSession
from kitchen_companion.timers import TimerService


class _CallableLog(list):
    """A list that is also an async callable: `await sink.heard(x)` records, `sink.heard == [x]` checks."""

    async def __call__(self, text: str):
        self.append(text)


class FakeSink:
    def __init__(self):
        self.heard = _CallableLog()
        self.overheard = _CallableLog()
        self.latencies: list[tuple[str, int]] = []
        self.states: list[dict] = []
        self.timer_snapshots: list[list[dict]] = []
        self.errors: list[str] = []

    async def latency(self, path, ms):
        self.latencies.append((path, ms))

    async def recipe_state(self, snapshot):
        self.states.append(snapshot)

    async def timers(self, snapshot):
        self.timer_snapshots.append(snapshot)

    async def error(self, message):
        self.errors.append(message)


def make_sink() -> FakeSink:
    return FakeSink()


def fixture_recipe() -> Recipe:
    lines = ["1 cup flour", "2 tbsp butter", "3 cloves garlic, minced"]
    steps = [
        Step(index=0, text="Whisk the flour."),
        Step(index=1, text="Simmer the sauce for 8 minutes.", timer_minutes=8),
        Step(index=2, text="Serve."),
    ]
    return Recipe(
        id="fixture", title="Test", servings=4, ingredients=[parse_ingredient(x) for x in lines], steps=steps
    )


def loaded_session() -> RecipeSession:
    session = RecipeSession()
    session.load(fixture_recipe())
    return session


def make_timers(calls: list | None = None) -> TimerService:
    async def on_due(timers, is_reminder):
        if calls is not None:
            calls.append(([t.label for t in timers], is_reminder))

    return TimerService(on_due)


def tf(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="u", timestamp="now", finalized=True)
