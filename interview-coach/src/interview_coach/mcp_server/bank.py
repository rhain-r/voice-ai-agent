"""Question bank and plan selection (spec §5.6). Pure: no network, deterministic per seed."""

import json
import random
import re
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Family = Literal["software", "data", "ai_ml", "product", "design", "general"]
Style = Literal["behavioral", "technical"]

LEVELS = ("intern", "junior", "mid", "senior", "staff")
MAX_QUESTIONS = 10

# First match wins. Short keywords use word boundaries so "ui" never matches "build".
_FAMILY_KEYWORDS: list[tuple[Family, re.Pattern[str]]] = [
    ("ai_ml", re.compile(r"\b(machine learning|ml|ai)\b", re.IGNORECASE)),
    ("data", re.compile(r"\b(data|analyst|analytics)\b", re.IGNORECASE)),
    ("product", re.compile(r"\b(product manager|product owner|pm)\b", re.IGNORECASE)),
    ("design", re.compile(r"\b(designer|ux|ui)\b", re.IGNORECASE)),
    ("software", re.compile(r"\b(engineer|developer|swe|programmer)\b", re.IGNORECASE)),
]


class QuestionItem(BaseModel):
    id: str
    text: str
    competency: str
    style: Style
    levels: list[str]
    good_answer_covers: list[str]


@cache
def _bank() -> dict[str, dict[str, list[QuestionItem]]]:
    raw = json.loads((Path(__file__).parent / "question_bank.json").read_text(encoding="utf-8"))
    bank: dict[str, dict[str, list[QuestionItem]]] = {}
    for family, styles in raw.items():
        bank[family] = {}
        for style, items in styles.items():
            prefix = f"{family}-{style[0]}"
            bank[family][style] = [
                QuestionItem(id=f"{prefix}-{i + 1}", style=style, **item) for i, item in enumerate(items)
            ]
    return bank


def role_family(role: str) -> Family:
    for family, pattern in _FAMILY_KEYWORDS:
        if pattern.search(role):
            return family
    return "general"


def _ordered_pool(items: list[QuestionItem], level: str, rng: random.Random) -> list[QuestionItem]:
    """Items at the candidate's level first (shuffled), then the rest (shuffled) as top-up."""
    matching = [q for q in items if level in q.levels]
    others = [q for q in items if level not in q.levels]
    rng.shuffle(matching)
    rng.shuffle(others)
    return matching + others


def question_plan(
    role: str,
    level: str,
    style: Literal["behavioral", "technical", "mixed"],
    count: int,
    seed: str,
) -> list[QuestionItem]:
    count = max(1, min(MAX_QUESTIONS, count))
    family = role_family(role)
    bank = _bank()
    rng = random.Random(f"{seed}:{role}:{level}:{style}")

    behavioral = bank["general"]["behavioral"] + (bank[family]["behavioral"] if family != "general" else [])
    technical = bank[family]["technical"]
    pools = {
        "behavioral": _ordered_pool(behavioral, level, rng),
        "technical": _ordered_pool(technical, level, rng),
    }

    if style == "mixed":
        wanted = ["behavioral" if i % 2 == 0 else "technical" for i in range(count)]
    else:
        wanted = [style] * count

    plan: list[QuestionItem] = []
    for want in wanted:
        other = "technical" if want == "behavioral" else "behavioral"
        source = pools[want] or pools[other]
        if not source:
            break
        plan.append(source.pop(0))
    return plan


_ANCHORS = {
    "structure": {
        "1": "Rambling; no clear situation, action or result.",
        "3": "Some structure, but one part (usually the result) is thin or missing.",
        "5": "Clear arc: context, what they did, and how it turned out.",
    },
    "specificity": {
        "1": "Generic or hypothetical; no concrete details.",
        "3": "One concrete example, light on details.",
        "5": "Concrete names, numbers, timelines and trade-offs.",
    },
    "impact": {
        "1": "No outcome mentioned.",
        "3": "Outcome stated but not measured or tied to the candidate.",
        "5": "Measurable outcome clearly caused by the candidate's actions.",
    },
    "relevance": {
        "1": "Doesn't answer the question asked.",
        "3": "Answers it partly or drifts.",
        "5": "Directly answers the question and fits the role and level.",
    },
    "communication": {
        "1": "Hard to follow; heavy filler or jargon.",
        "3": "Understandable with some wandering.",
        "5": "Concise, confident and easy to follow.",
    },
}
_TECHNICAL_STRUCTURE = {
    "1": "No visible approach; jumps around.",
    "3": "An approach exists but skips clarifying the problem or trade-offs.",
    "5": "Clarifies, outlines an approach, then weighs trade-offs.",
}


def rubric(style: str) -> dict[str, dict[str, str]]:
    anchors = {dim: dict(levels) for dim, levels in _ANCHORS.items()}
    if style == "technical":
        anchors["structure"] = dict(_TECHNICAL_STRUCTURE)
    return anchors


def role_families() -> list[str]:
    return list(_bank())
