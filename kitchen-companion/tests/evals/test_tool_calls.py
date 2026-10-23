import re

import pytest

pytestmark = pytest.mark.eval


def tool_uses(response) -> list:
    return [block for block in response.content if block.type == "tool_use"]


def text_of(response) -> str:
    return " ".join(block.text for block in response.content if block.type == "text").strip()


def first_call(response, name: str) -> dict:
    calls = [c for c in tool_uses(response) if c.name == name]
    assert calls, (
        f"expected a {name} call, got {[c.name for c in tool_uses(response)]}: {text_of(response)!r}"
    )
    return calls[0].input


async def test_how_much_butter_uses_get_ingredient(ask):
    args = first_call(await ask("how much butter do I need"), "get_ingredient")
    assert "butter" in args["name"].lower()


async def test_scale_for_eight(ask):
    args = first_call(await ask("make it for eight people"), "scale_recipe")
    assert int(args["servings"]) == 8


async def test_convert_that_to_grams_after_butter(ask):
    response = await ask(
        "how much butter do I need",
        "Two tablespoons of butter.",
        "convert that to grams",
    )
    args = first_call(response, "convert_units")
    assert str(args["to_unit"]).lower() in {"g", "grams", "gram"}
    assert "butter" in str(args.get("ingredient", "")).lower()


async def test_substitution_answered_without_tools(ask):
    response = await ask("what can I use instead of buttermilk")
    assert tool_uses(response) == []
    text = text_of(response)
    assert text
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    assert len(sentences) <= 2, text
    assert not re.search(r"[*#]|^\s*- ", text, re.MULTILINE), text


async def test_pasta_timer_eleven_minutes(ask):
    args = first_call(await ask("set a timer for the pasta, eleven minutes"), "set_timer")
    assert float(args["minutes"]) == 11
    assert "pasta" in str(args.get("label", "")).lower()
