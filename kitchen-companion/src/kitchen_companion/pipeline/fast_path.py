"""Fast path: short kitchen commands answered from code, with no LLM call.

`parse` is pure. Navigation, stop, yes/no and acknowledgements must match a whole short command, so
a sentence that merely contains "next" ("next time I'll use less salt") never matches. Timer
commands may be longer but must say "timer" (or ask how long is left) and, to start one, a duration.
"""

import re
from dataclasses import dataclass
from typing import Literal

IntentKind = Literal[
    "next", "prev", "repeat", "goto", "stop", "timer_start", "timer_cancel", "timer_query", "yes", "no", "ack"
]


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    n: int | None = None
    minutes: float | None = None
    label: str | None = None


# -- normalization -------------------------------------------------------------------------------

_POLITE = {"please", "okay", "ok", "alright", "now", "chef"}
_PUNCT = re.compile(r"[^\w\s.]|(?<!\d)\.|\.(?!\d)")


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("'", "")
    return " ".join(_PUNCT.sub(" ", text).split())


def _strip_polite(text: str) -> str:
    words = text.split()
    while words and words[0] in _POLITE:
        words.pop(0)
    while words and words[-1] in _POLITE:
        words.pop()
    return " ".join(words)


# -- numbers and durations -----------------------------------------------------------------------

_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]

_WORD_VALUES = {w: i + 1 for i, w in enumerate(_ONES)}
for _i, _tens in enumerate(_TENS):
    _WORD_VALUES[_tens] = 20 + 10 * _i
    for _j, _one in enumerate(_ONES[:9]):
        _WORD_VALUES[f"{_tens} {_one}"] = 20 + 10 * _i + _j + 1

_NUMBER_WORD = "|".join(sorted(_WORD_VALUES, key=len, reverse=True))
_NUM = rf"(?:\d+(?:\.\d+)?|{_NUMBER_WORD}|an|a)"
_UNIT = r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)"
_PART = re.compile(
    rf"\b(?:half (?:an|a) (?P<half_unit>hour|minute)"
    rf"|(?P<num>{_NUM})(?P<pre_half> and a half)? (?P<unit>{_UNIT})(?P<post_half> and a half)?)\b"
)
_JOINER = re.compile(r"\s+(?:and\s+)?")


def _number(token: str) -> float | None:
    if token in ("a", "an"):
        return 1.0
    if token in _WORD_VALUES:
        return float(_WORD_VALUES[token])
    try:
        return float(token)
    except ValueError:
        return None


def _part_minutes(m: re.Match[str]) -> float:
    if m.group("half_unit"):
        return 30.0 if m.group("half_unit") == "hour" else 0.5
    value = _number(m.group("num")) or 0.0
    if m.group("pre_half") or m.group("post_half"):
        value += 0.5
    unit = m.group("unit")
    if unit.startswith(("h",)):
        return value * 60
    if unit.startswith("s"):
        return value / 60
    return value


def _find_duration(text: str) -> tuple[float, int, int] | None:
    """Total minutes of the first run of duration parts ("1 hour 15 minutes"), with its span."""
    m = _PART.search(text)
    if not m:
        return None
    total, start, end = _part_minutes(m), m.start(), m.end()
    while True:
        joiner = _JOINER.match(text, end)
        if not joiner:
            break
        nxt = _PART.match(text, joiner.end())
        if not nxt:
            break
        total += _part_minutes(nxt)
        end = nxt.end()
    return total, start, end


def parse_duration_minutes(text: str) -> float | None:
    found = _find_duration(_normalize(text))
    return found[0] if found and found[0] > 0 else None


# -- whole-command phrase sets -------------------------------------------------------------------

_PHRASES: dict[IntentKind, set[str]] = {
    "next": {"next", "next step", "next one", "whats next", "what is next", "whats the next step", "done",
             "im done", "all done", "finished", "im finished", "go on", "continue", "keep going", "move on",
             "ready", "im ready", "go ahead and continue", "lets keep going"},
    "prev": {"back", "go back", "previous", "previous step", "go back a step", "go back one step",
             "step back", "back one", "back a step", "one step back", "go back one"},
    "repeat": {"repeat", "repeat that", "say that again", "say again", "what was that", "come again",
               "again", "pardon", "pardon me", "sorry what", "what did you say", "repeat the step",
               "repeat step", "read that again", "one more time", "huh"},
    "stop": {"stop", "quiet", "be quiet", "pause", "wait", "hold on", "hang on", "shush", "shh", "enough",
             "stop talking", "thats enough", "one moment", "hold it"},
    "yes": {"yes", "yeah", "yep", "yup", "sure", "sure thing", "do it", "please do", "go for it",
            "sounds good", "yes do it", "yes start it", "start it", "absolutely", "definitely"},
    "no": {"no", "nope", "nah", "no thanks", "no thank you", "not now", "not yet", "skip it", "no need",
           "dont", "maybe later"},
    "ack": {"got it", "thanks", "thank you", "okay", "ok", "alright", "ok got it", "okay got it",
            "understood", "roger", "cool", "great", "perfect", "will do", "on it", "heard"},
}

_STEP_NUMBER = rf"(\d+|{_NUMBER_WORD})"
_GOTO = re.compile(
    rf"^(?:(?:go|jump|skip|move|take me|back)(?: back)? to )?(?:the )?step (?:number )?{_STEP_NUMBER}$"
)
_GOTO_ORDINAL = re.compile(
    rf"^(?:(?:go|jump|skip|move|take me|back)(?: back)? to )?(?:the )?({'|'.join(_ORDINALS)}) step$"
)

# -- timer commands ------------------------------------------------------------------------------

_TIMER_WORD = re.compile(r"\btimers?\b")
_CANCEL_WORD = re.compile(r"\b(?:cancel|stop|delete|remove|clear|kill|turn off|end|reset|dismiss)\b")
_QUERY_START = re.compile(r"^(?:how long|how much time|how many minutes|whats left|time left|time check)\b")
_QUERY_TARGET = re.compile(
    r"\b(?:left|remaining|until|till|til|to go|timers?)\b|^(?:how long|how much time) (?:is )?on\b"
)

_START_FILLER = {
    "set", "start", "a", "an", "the", "me", "my", "timer", "for", "please", "can", "you", "put", "on", "of",
    "make", "up", "new", "another", "quick", "called", "named", "labeled", "and", "give", "get", "add",
    "us", "i", "need", "want", "to", "go", "could", "would",
}
_CANCEL_FILLER = {
    "cancel", "stop", "delete", "remove", "clear", "kill", "turn", "off", "end", "reset", "dismiss", "the",
    "my", "a", "timer", "timers", "please", "for", "that", "this", "on", "can", "you", "could",
}
_QUERY_FILLER = {
    "how", "long", "much", "time", "is", "left", "on", "the", "my", "timer", "timers", "until", "till", "til",
    "to", "go", "remaining", "whats", "what", "are", "there", "do", "i", "have", "many", "minutes", "done",
    "ready", "check", "does", "it", "of", "for", "a", "any", "be", "will", "s",
}
_MAX_LABEL_WORDS = 3


def _label(text: str, filler: set[str]) -> tuple[bool, str | None]:
    """Leftover words after the command words: (ok, label). Too many leftovers means it isn't a command."""
    words = [w for w in text.split() if w not in filler]
    if len(words) > _MAX_LABEL_WORDS:
        return False, None
    return True, " ".join(words) or None


def _timer_intent(text: str) -> Intent | None:
    if _QUERY_START.match(text) and _QUERY_TARGET.search(text):
        ok, label = _label(text, _QUERY_FILLER)
        return Intent("timer_query", label=label) if ok else None
    if not _TIMER_WORD.search(text):
        return None
    if _CANCEL_WORD.search(text):
        ok, label = _label(text, _CANCEL_FILLER)
        return Intent("timer_cancel", label=label) if ok else None
    found = _find_duration(text)
    if not found or found[0] <= 0:
        return None
    minutes, start, end = found
    ok, label = _label(text[:start] + " " + text[end:], _START_FILLER)
    return Intent("timer_start", minutes=minutes, label=label) if ok else None


def parse(text: str) -> Intent | None:
    raw = _normalize(text)
    if not raw:
        return None
    if raw in _PHRASES["ack"]:
        return Intent("ack")
    t = _strip_polite(raw)
    if not t:
        return None
    for kind, phrases in _PHRASES.items():
        if raw in phrases or t in phrases:  # "not now" is a phrase even though "now" is filler
            return Intent(kind)
    m = _GOTO.match(t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _WORD_VALUES[m.group(1)]
        return Intent("goto", n=n)
    m = _GOTO_ORDINAL.match(t)
    if m:
        return Intent("goto", n=_ORDINALS.index(m.group(1)) + 1)
    return _timer_intent(t)
