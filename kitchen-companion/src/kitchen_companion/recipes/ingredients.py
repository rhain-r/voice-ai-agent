"""Parse free-text ingredient lines ("1 1/2 cups flour, sifted") into structured ingredients."""

import re
from fractions import Fraction

from kitchen_companion.recipes.model import Ingredient
from kitchen_companion.recipes.units import normalize_unit

_UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅖": "2/5", "⅗": "3/5",
    "⅘": "4/5", "⅙": "1/6", "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}
_UNICODE_RE = re.compile("(\\d?)\\s*([" + "".join(_UNICODE_FRACTIONS) + "])")

_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|\.\d+)"
_LEAD = re.compile(
    rf"^\s*(?P<qty>{_NUM})(?:\s*(?:-|to)\s*(?P<max>{_NUM}))?\s*", re.IGNORECASE
)
_ARTICLE = re.compile(r"^\s*an?\s+", re.IGNORECASE)
_PAREN = re.compile(r"\(\s*([^)]*?)\s*\)")
_TWO_WORD_UNIT = re.compile(r"^(fl\.?\s*oz\.?|fluid\s+ounces?)(?=\s|$)", re.IGNORECASE)
_WORD = re.compile(r"^([A-Za-z]+\.?)(?=\s|$|,)")
_OF = re.compile(r"^of\s+", re.IGNORECASE)


def _to_fraction(text: str) -> Fraction:
    parts = text.split()
    return sum((Fraction(p) for p in parts), Fraction(0))


def _expand_unicode(line: str) -> str:
    def repl(m: re.Match[str]) -> str:
        whole, frac = m.group(1), _UNICODE_FRACTIONS[m.group(2)]
        return f"{whole} {frac}" if whole else frac

    return _UNICODE_RE.sub(repl, line.replace("⁄", "/")).replace("–", "-").replace("—", "-")


def _take_unit(rest: str) -> tuple[str | None, str]:
    m = _TWO_WORD_UNIT.match(rest)
    if m:
        return "floz", rest[m.end():].lstrip()
    m = _WORD.match(rest)
    if m:
        unit = normalize_unit(m.group(1))
        if unit:
            return unit, rest[m.end():].lstrip()
    return None, rest


def parse_ingredient(line: str) -> Ingredient:
    """Never raises: a line without a leading quantity keeps the whole line as its name."""
    unparsed = Ingredient(qty=None, unit=None, name=line.strip(), raw=line)
    try:
        text = _expand_unicode(line)
        notes: list[str] = []

        m = _LEAD.match(text)
        if m:
            qty = _to_fraction(m.group("qty"))
            qty_max = _to_fraction(m.group("max")) if m.group("max") else None
            rest = text[m.end():]
        else:
            article = _ARTICLE.match(text)
            if not article:
                return unparsed
            unit, after = _take_unit(text[article.end():])
            if unit is None:
                return unparsed
            qty, qty_max, rest = Fraction(1), None, text[article.end():]

        paren = _PAREN.match(rest)
        if paren:
            notes.append(paren.group(1))
            rest = rest[paren.end():].lstrip()

        unit, rest = _take_unit(rest)
        rest = _OF.sub("", rest)

        for inner in _PAREN.findall(rest):
            notes.append(inner)
        rest = " ".join(_PAREN.sub(" ", rest).split())

        name, _, trailing = rest.partition(",")
        name = name.strip()
        if trailing.strip():
            notes.append(trailing.strip())
        if not name:
            return unparsed
        return Ingredient(
            qty=qty,
            qty_max=qty_max,
            unit=unit,
            name=name,
            note=", ".join(n for n in notes if n) or None,
            raw=line,
        )
    except (ValueError, ZeroDivisionError):
        return unparsed
