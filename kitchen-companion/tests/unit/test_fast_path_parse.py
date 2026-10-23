import pytest

from kitchen_companion.pipeline.fast_path import Intent, parse, parse_duration_minutes

I = Intent  # noqa: E741 - keeps the table readable

MUST_MATCH = [
    # navigation
    ("next", I("next")),
    ("Next.", I("next")),
    ("what's next", I("next")),
    ("What’s next?", I("next")),
    ("okay next please", I("next")),
    ("next step", I("next")),
    ("I'm done", I("next")),
    ("done", I("next")),
    ("all done", I("next")),
    ("keep going", I("next")),
    ("move on", I("next")),
    ("go back", I("prev")),
    ("back", I("prev")),
    ("previous step", I("prev")),
    ("go back a step", I("prev")),
    ("say that again", I("repeat")),
    ("repeat", I("repeat")),
    ("repeat that please", I("repeat")),
    ("what was that", I("repeat")),
    ("come again", I("repeat")),
    ("go to step 3", I("goto", n=3)),
    ("step five", I("goto", n=5)),
    ("Go to step twelve.", I("goto", n=12)),
    ("jump to step 2", I("goto", n=2)),
    ("go to the third step", I("goto", n=3)),
    ("first step", I("goto", n=1)),
    # stop
    ("stop", I("stop")),
    ("hold on", I("stop")),
    ("quiet", I("stop")),
    ("be quiet please", I("stop")),
    ("pause", I("stop")),
    ("wait", I("stop")),
    # timers
    ("set a timer for 8 minutes", I("timer_start", minutes=8)),
    ("set a timer for eight minutes for the onions", I("timer_start", minutes=8, label="onions")),
    ("start a timer for a minute and a half", I("timer_start", minutes=1.5)),
    ("half an hour timer", I("timer_start", minutes=30)),
    ("set a timer for 1 hour 15 minutes", I("timer_start", minutes=75)),
    ("set a timer for 90 seconds", I("timer_start", minutes=1.5)),
    ("set a pasta timer for 10 minutes", I("timer_start", minutes=10, label="pasta")),
    ("timer for the pasta, eleven minutes", I("timer_start", minutes=11, label="pasta")),
    ("set a 5-minute timer for the garlic bread", I("timer_start", minutes=5, label="garlic bread")),
    ("timer twenty five minutes", I("timer_start", minutes=25)),
    ("set a timer for an hour and a half", I("timer_start", minutes=90)),
    ("set a timer for one and a half minutes", I("timer_start", minutes=1.5)),
    ("cancel the onion timer", I("timer_cancel", label="onion")),
    ("cancel the timer", I("timer_cancel")),
    ("stop the pasta timer", I("timer_cancel", label="pasta")),
    ("how long left on the pasta", I("timer_query", label="pasta")),
    ("how much time is left", I("timer_query")),
    ("how long until the rice is done", I("timer_query", label="rice")),
    ("how much time on the onions", I("timer_query", label="onions")),
    # answers
    ("yes please", I("yes")),
    ("yeah", I("yes")),
    ("sure", I("yes")),
    ("no thanks", I("no")),
    ("nope", I("no")),
    ("not now", I("no")),
    ("got it", I("ack")),
    ("thanks", I("ack")),
    ("thank you chef", I("ack")),
    ("okay", I("ack")),
]

MUST_NOT_MATCH = [
    "next time I'll use less salt",
    "I'll go back to the store later",
    "can you repeat the part about the oven",
    "how much butter do I need",
    "set the table",
    "what can I make with eggs",
    "stop adding salt when",
    "the timer on the oven is broken",
    "how long do I bake the cookies",
    "is it done yet",
    "put it next to the sink",
    "yes I think we should add more garlic",
    "no I meant the other pan",
    "thanks for the help with the sauce",
    "wait until it boils",
    "set a timer",
    "what's the next ingredient",
    "go back to the oven",
    "when does the timer end",
    "when will the timer go off",
    "how do I reset the timer",
    "the timer says 5 minutes left",
    "",
    "   ",
]


@pytest.mark.parametrize("text,expected", MUST_MATCH)
def test_parse_matches(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize("text", MUST_NOT_MATCH)
def test_parse_rejects(text):
    assert parse(text) is None


def test_table_size():
    assert len(MUST_MATCH) + len(MUST_NOT_MATCH) >= 60


@pytest.mark.parametrize(
    "text,minutes",
    [("8 minutes", 8), ("eight minutes", 8), ("a minute and a half", 1.5), ("half an hour", 30),
     ("1 hour 15 minutes", 75), ("90 seconds", 1.5), ("an hour", 60), ("2 and a half hours", 150),
     ("forty five minutes", 45), ("1.5 hours", 90), ("half a minute", 0.5), ("no duration here", None)],
)
def test_parse_duration_minutes(text, minutes):
    assert parse_duration_minutes(text) == minutes
