"""Unit conversion and kitchen-friendly spoken quantities. US customary units throughout."""

import math
from fractions import Fraction
from typing import Literal

CANONICAL = {"tsp", "tbsp", "cup", "ml", "l", "floz", "g", "kg", "oz", "lb"}
COUNT_UNITS = {"clove", "can", "pinch", "slice", "sprig", "bunch", "stick", "package"}

# Millilitres per volume unit and grams per mass unit.
VOLUME_ML = {
    "tsp": Fraction("4.929"),
    "tbsp": Fraction("14.787"),
    "cup": Fraction("236.588"),
    "ml": Fraction(1),
    "l": Fraction(1000),
    "floz": Fraction("29.574"),
}
MASS_G = {"g": Fraction(1), "kg": Fraction(1000), "oz": Fraction("28.3495"), "lb": Fraction("453.592")}

# g/ml, matched by substring of the ingredient name. Order matters: "buttermilk" is milk, not butter.
DENSITY = (
    ("milk", Fraction("1.03")),
    ("flour", Fraction("0.53")),
    ("sugar", Fraction("0.85")),
    ("butter", Fraction("0.911")),
    ("water", Fraction(1)),
    ("rice", Fraction("0.78")),
)

_ALIASES = {
    "tsp": ("tsp", "tsps", "tspn", "teaspoon", "teaspoons"),
    "tbsp": ("tbsp", "tbsps", "tbs", "tbl", "tbls", "tablespoon", "tablespoons"),
    "cup": ("cup", "cups"),
    "ml": ("ml", "mls", "milliliter", "milliliters", "millilitre", "millilitres"),
    "l": ("l", "liter", "liters", "litre", "litres"),
    "floz": ("floz", "fl oz", "fl. oz", "fluid ounce", "fluid ounces"),
    "g": ("g", "gr", "gram", "grams", "gramme", "grammes"),
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"),
    "oz": ("oz", "ounce", "ounces"),
    "lb": ("lb", "lbs", "pound", "pounds"),
    "clove": ("clove", "cloves"),
    "can": ("can", "cans", "tin", "tins"),
    "pinch": ("pinch", "pinches"),
    "slice": ("slice", "slices"),
    "sprig": ("sprig", "sprigs"),
    "bunch": ("bunch", "bunches"),
    "stick": ("stick", "sticks"),
    "package": ("package", "packages", "pkg", "packet", "packets"),
}
_ALIAS_TO_UNIT = {alias: unit for unit, aliases in _ALIASES.items() for alias in aliases}

_UNIT_NAMES = {
    "tsp": ("teaspoon", "teaspoons"),
    "tbsp": ("tablespoon", "tablespoons"),
    "cup": ("cup", "cups"),
    "ml": ("milliliter", "milliliters"),
    "l": ("liter", "liters"),
    "floz": ("fluid ounce", "fluid ounces"),
    "g": ("gram", "grams"),
    "kg": ("kilogram", "kilograms"),
    "oz": ("ounce", "ounces"),
    "lb": ("pound", "pounds"),
    "pinch": ("pinch", "pinches"),
    "bunch": ("bunch", "bunches"),
}


class ConversionError(ValueError):
    pass


def normalize_unit(token: str) -> str | None:
    """Map a unit token to its canonical name. "T" is tablespoon and "t" teaspoon; all else ignores case."""
    stripped = token.strip().rstrip(".")
    if stripped == "T":
        return "tbsp"
    if stripped == "t":
        return "tsp"
    key = " ".join(stripped.lower().split())
    return _ALIAS_TO_UNIT.get(key)


def unit_name(unit: str, plural: bool = True) -> str:
    """The spoken name of a canonical unit: "tbsp" -> "tablespoons"."""
    one, many = _unit_words(unit)
    return many if plural else one


def _density(ingredient: str | None) -> Fraction | None:
    if not ingredient:
        return None
    name = ingredient.lower()
    for key, density in DENSITY:
        if key in name:
            return density
    return None


def convert(qty: Fraction, from_unit: str, to_unit: str, ingredient: str | None = None) -> Fraction:
    src = normalize_unit(from_unit) or from_unit
    dst = normalize_unit(to_unit) or to_unit
    if src == dst:
        return Fraction(qty)
    if src in VOLUME_ML and dst in VOLUME_ML:
        return qty * VOLUME_ML[src] / VOLUME_ML[dst]
    if src in MASS_G and dst in MASS_G:
        return qty * MASS_G[src] / MASS_G[dst]
    if (src in VOLUME_ML and dst in MASS_G) or (src in MASS_G and dst in VOLUME_ML):
        density = _density(ingredient)
        if density is None:
            raise ConversionError(f"no density for {ingredient or 'that ingredient'}")
        if src in VOLUME_ML:
            return qty * VOLUME_ML[src] * density / MASS_G[dst]
        return qty * MASS_G[src] / density / VOLUME_ML[dst]
    raise ConversionError(f"can't convert {from_unit} to {to_unit}")


def _round_half_up(x: Fraction | float) -> int:
    return math.floor(x + Fraction(1, 2)) if isinstance(x, Fraction) else math.floor(x + 0.5)


def convert_temp(value: float, from_scale: Literal["F", "C"], to_scale: Literal["F", "C"]) -> int:
    if from_scale == to_scale:
        out = float(value)
    elif from_scale == "F":
        out = (value - 32) * 5 / 9
    else:
        out = value * 9 / 5 + 32
    return 5 * _round_half_up(out / 5)


def _step_for(unit: str | None) -> Fraction:
    if unit in ("g", "ml", "oz") or unit in COUNT_UNITS:
        return Fraction(1)
    if unit is None:
        return Fraction(1, 2)
    return Fraction(1, 8)


def round_kitchen(qty: Fraction, unit: str | None) -> Fraction:
    """Round to a step a cook can measure. A positive amount never rounds down to zero."""
    step = _step_for(unit)
    rounded = _round_half_up(Fraction(qty) / step) * step
    if rounded == 0 and qty > 0:
        return step
    return Fraction(rounded)


_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n: int) -> str:
    if n < 0 or n > 9999:
        return str(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {number_words(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return f"{_ONES[thousands]} thousand" + (f" {number_words(rest)}" if rest else "")


# Spoken forms of a fractional part: (on its own with a unit, after "and", on its own without a unit).
_FRACTIONS = {
    Fraction(1, 8): ("an eighth of {a} {one}", "an eighth", "an eighth"),
    Fraction(1, 4): ("a quarter {one}", "a quarter", "a quarter"),
    Fraction(1, 3): ("a third of {a} {one}", "a third", "a third"),
    Fraction(3, 8): ("three eighths of {a} {one}", "three eighths", "three eighths"),
    Fraction(1, 2): ("half {a} {one}", "a half", "half"),
    Fraction(5, 8): ("five eighths of {a} {one}", "five eighths", "five eighths"),
    Fraction(2, 3): ("two thirds of {a} {one}", "two thirds", "two thirds"),
    Fraction(3, 4): ("three quarters of {a} {one}", "three quarters", "three quarters"),
    Fraction(7, 8): ("seven eighths of {a} {one}", "seven eighths", "seven eighths"),
}


def _unit_words(unit: str | None) -> tuple[str, str]:
    if unit is None:
        return "", ""
    if unit in _UNIT_NAMES:
        return _UNIT_NAMES[unit]
    return unit, unit if unit.endswith("s") else unit + "s"


def _nearest_fraction(frac: Fraction) -> tuple[int, Fraction]:
    """Snap a fractional part (0 < frac < 1) to the nearest speakable fraction, carrying into wholes."""
    options = [Fraction(0), *_FRACTIONS, Fraction(1)]
    best = min(options, key=lambda f: abs(f - frac))
    return (1, Fraction(0)) if best == 1 else (0, best)


def speak_quantity(qty: Fraction, unit: str | None) -> str:
    whole, frac = divmod(Fraction(qty), 1)
    whole = int(whole)
    if frac:
        carry, frac = _nearest_fraction(frac)
        whole += carry
    one, many = _unit_words(unit)
    if not frac:
        noun = one if whole == 1 else many
        return f"{number_words(whole)} {noun}".strip()
    alone, after_and, bare = _FRACTIONS[frac]
    if whole == 0:
        if not one:
            return bare
        article = "an" if one[0] in "aeiou" else "a"
        return alone.format(a=article, one=one)
    return f"{number_words(whole)} and {after_and} {many}".strip()
