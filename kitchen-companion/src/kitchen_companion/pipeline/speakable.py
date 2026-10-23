"""Kitchen-aware text normalization applied right before TTS: "1 1/2 cups" -> "one and a half cups"."""

import re
from fractions import Fraction

from pipecat.utils.text.base_text_filter import BaseTextFilter

from kitchen_companion.recipes.units import normalize_unit, number_words, speak_quantity

_UNICODE = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅛": "1/8", "⅜": "3/8",
            "⅝": "5/8", "⅞": "7/8"}
_UNICODE_RE = re.compile(r"(\d?)\s*([" + "".join(_UNICODE) + "])")

_TIME_UNITS = {
    "min": ("minute", "minutes"), "mins": ("minute", "minutes"), "minute": ("minute", "minutes"),
    "minutes": ("minute", "minutes"), "hr": ("hour", "hours"), "hrs": ("hour", "hours"),
    "hour": ("hour", "hours"), "hours": ("hour", "hours"), "sec": ("second", "seconds"),
    "secs": ("second", "seconds"), "second": ("second", "seconds"), "seconds": ("second", "seconds"),
}
# Abbreviations spoken in full even without a number in front.
_BARE_ABBREVIATIONS = {
    "tbsp": "tablespoons", "tbsps": "tablespoons", "tsp": "teaspoons", "tsps": "teaspoons",
    "oz": "ounces", "lb": "pounds", "lbs": "pounds", "ml": "milliliters", "min": "minutes",
    "mins": "minutes", "hr": "hours", "hrs": "hours", "sec": "seconds", "secs": "seconds",
}

_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_MARKDOWN = [
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"\1"),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"^\s*#{1,6}\s+", re.MULTILINE), ""),
    (re.compile(r"^\s*(?:[-*•]|\d+\.)\s+", re.MULTILINE), ""),
]
_TEMP = re.compile(rf"(?<![\w/])({_NUM})\s*°\s*([FC])?\b")
_RANGE = re.compile(rf"(?<![\w/])({_NUM})\s*[-–—]\s*({_NUM})(?:\s*([A-Za-z]+)\b\.?)?")
_QTY_UNIT = re.compile(rf"(?<![\w/])({_NUM})\s*([A-Za-z]+)\b(\.?)")
_BARE = re.compile(r"\b(" + "|".join(_BARE_ABBREVIATIONS) + r")\b", re.IGNORECASE)
_NUMBER = re.compile(rf"(?<![\w/.])({_NUM})(?![\w/]|\.\d)")


def _fraction(text: str) -> Fraction:
    return sum((Fraction(part) for part in text.split()), Fraction(0))


def _quantity_with_unit(qty: Fraction, word: str) -> str | None:
    if word.lower() in _TIME_UNITS:
        one, many = _TIME_UNITS[word.lower()]
        return speak_quantity(qty, None) + " " + (one if qty == 1 else many)
    unit = normalize_unit(word)
    if unit is None:
        return None
    return speak_quantity(qty, unit)


def _temp(m: re.Match[str]) -> str:
    words = speak_quantity(_fraction(m.group(1)), None)
    scale = {"F": " Fahrenheit", "C": " Celsius"}.get(m.group(2) or "", "")
    return f"{words} degrees{scale}"


def _range(m: re.Match[str]) -> str:
    low, high, word = _fraction(m.group(1)), _fraction(m.group(2)), m.group(3)
    if word:
        spoken_high = _quantity_with_unit(high, word)
        if spoken_high is not None:
            return f"{speak_quantity(low, None)} to {spoken_high}"
        return f"{speak_quantity(low, None)} to {speak_quantity(high, None)} {word}"
    return f"{speak_quantity(low, None)} to {speak_quantity(high, None)}"


def _qty_unit(m: re.Match[str]) -> str:
    spoken = _quantity_with_unit(_fraction(m.group(1)), m.group(2))
    if spoken is None:
        return m.group(0)
    return spoken + m.group(3)


def _number(m: re.Match[str]) -> str:
    value = _fraction(m.group(1))
    if value.denominator == 1:
        return number_words(int(value))
    return speak_quantity(value, None)


def normalize(text: str) -> str:
    for pattern, repl in _MARKDOWN:
        text = pattern.sub(repl, text)
    text = _UNICODE_RE.sub(lambda m: f"{m.group(1)} {_UNICODE[m.group(2)]}".strip(), text)
    text = _TEMP.sub(_temp, text)
    text = _RANGE.sub(_range, text)
    text = _QTY_UNIT.sub(_qty_unit, text)
    text = _BARE.sub(lambda m: _BARE_ABBREVIATIONS[m.group(1).lower()], text)
    text = _NUMBER.sub(_number, text)
    return text


class KitchenTextFilter(BaseTextFilter):
    """Pipecat TTS text filter: speaks quantities, temperatures and times the way a cook would."""

    async def filter(self, text: str) -> str:
        return normalize(text)

    async def update_settings(self, settings) -> None:
        pass

    async def handle_interruption(self) -> None:
        pass

    async def reset_interruption(self) -> None:
        pass

