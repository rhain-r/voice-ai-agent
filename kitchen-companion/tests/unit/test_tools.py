from types import SimpleNamespace

import pytest

from kitchen_companion.prompts import SYSTEM_PROMPT
from kitchen_companion.recipes.library import Library
from kitchen_companion.tools import ToolHandlers, to_anthropic_tools, tool_schemas
from tests.fakes import fixture_recipe, loaded_session, make_sink, make_timers

SPEC_TOOLS = {
    "search_recipes",
    "load_recipe",
    "get_ingredient",
    "scale_recipe",
    "convert_units",
    "go_to_step",
    "set_timer",
    "cancel_timer",
    "list_timers",
}


class Rig:
    def __init__(self):
        self.sink = make_sink()
        self.recipe = loaded_session()
        self.timers = make_timers()
        self.library = Library.load_bundled()
        self.library.add(fixture_recipe())
        self.loaded = []

        async def on_recipe_loaded(recipe):
            self.loaded.append(recipe.id)

        self.h = ToolHandlers(self.recipe, self.timers, self.library, self.sink, on_recipe_loaded)


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def test_get_ingredient_scaled(rig):
    assert (await rig.h.scale_recipe({"servings": 8}))["say"] == "Scaled to eight servings."
    out = await rig.h.get_ingredient({"name": "flour"})
    assert out == {"say": "two cups flour", "candidates": []}
    assert rig.sink.states[-1]["servings"] == 8


async def test_get_ingredient_ambiguous_lists_candidates(rig):
    rig.recipe.load(rig.library.get("fluffy-pancakes"))
    out = await rig.h.get_ingredient({"name": "sugar"})
    assert out["say"] == "two tablespoons sugar"
    out = await rig.h.get_ingredient({"name": "butter"})
    assert out["candidates"] == [] and out["say"] == "three tablespoons unsalted butter, melted"


async def test_convert_units_impossible_is_error_not_exception(rig):
    out = await rig.h.convert_units(
        {"quantity": 1, "from_unit": "cups", "to_unit": "grams", "ingredient": "spinach"}
    )
    assert out == {
        "error": "I can't convert cups of spinach to grams reliably, but it's roughly a handful per cup."
    }


async def test_convert_units_with_density(rig):
    out = await rig.h.convert_units(
        {"quantity": 2, "from_unit": "tbsp", "to_unit": "g", "ingredient": "butter"}
    )
    assert out == {"say": "two tablespoons of butter is about twenty-seven grams."}


async def test_convert_units_volume_and_fraction_string(rig):
    out = await rig.h.convert_units({"quantity": "1 1/2", "from_unit": "cups", "to_unit": "ml"})
    assert out == {"say": "one and a half cups is about three hundred fifty-five milliliters."}


async def test_convert_units_temperature(rig):
    out = await rig.h.convert_units({"quantity": 350, "from_unit": "F", "to_unit": "celsius"})
    assert out == {
        "say": "three hundred fifty degrees Fahrenheit is about one hundred seventy-five degrees Celsius."
    }


async def test_convert_units_unknown_unit(rig):
    out = await rig.h.convert_units({"quantity": 1, "from_unit": "bushel", "to_unit": "g"})
    assert "error" in out


async def test_load_recipe_calls_hook_and_emits_state(rig):
    out = await rig.h.load_recipe({"recipe_id": "garlic-butter-pasta"})
    assert out["say"].startswith("Okay, Garlic Butter Pasta. Seven steps. Step one:")
    assert rig.loaded == ["garlic-butter-pasta"]
    assert rig.sink.states[-1]["id"] == "garlic-butter-pasta"


async def test_unknown_recipe_id_error(rig):
    out = await rig.h.load_recipe({"recipe_id": "nope"})
    assert "error" in out and rig.loaded == []


async def test_search_recipes(rig):
    out = await rig.h.search_recipes({"query": "eggs spinach"})
    assert out["results"][0] == {"id": "spinach-feta-omelette", "title": "Spinach & Feta Omelette"}
    assert (await rig.h.search_recipes({"query": "quinoa"}))["results"] == []


async def test_go_to_step_variants(rig):
    assert (await rig.h.go_to_step({"step": 3}))["say"] == "Step three: Serve."
    assert (await rig.h.go_to_step({"step": "prev"}))["say"].startswith("Step two:")
    assert (await rig.h.go_to_step({"step": "repeat"}))["say"].startswith("Step two:")
    assert (await rig.h.go_to_step({"step": "next"}))["say"] == "Step three: Serve."
    assert (await rig.h.go_to_step({"step": "1"}))["say"] == "Step one: Whisk the flour."
    assert "error" in await rig.h.go_to_step({"step": "sideways"})
    assert rig.sink.states[-1]["index"] == 0


async def test_set_timer_emits_timers(rig):
    out = await rig.h.set_timer({"minutes": 11, "label": "pasta"})
    assert out == {"say": "Pasta timer set for eleven minutes."}
    assert rig.sink.timer_snapshots[-1][0]["label"] == "pasta"


async def test_set_timer_rejects_nonpositive(rig):
    assert "error" in await rig.h.set_timer({"minutes": 0})
    assert rig.timers.list() == []


async def test_cancel_and_list_timers(rig):
    await rig.h.set_timer({"minutes": 5, "label": "pasta"})
    await rig.h.set_timer({"minutes": 3, "label": "sauce"})
    assert (await rig.h.cancel_timer({}))["say"] == "Which timer, pasta or sauce?"
    listed = await rig.h.list_timers({})
    assert [t["label"] for t in listed["timers"]] == ["pasta", "sauce"]
    assert listed["say"].startswith("The pasta timer has")
    assert (await rig.h.cancel_timer({"label": "sauce"}))["say"] == "Cancelled the sauce timer."
    assert (await rig.h.cancel_timer({"label": "rice"}))["say"] == "I don't see the rice timer."


async def test_handler_exception_becomes_error(rig):
    out = await rig.h.scale_recipe({"servings": "lots"})
    assert out == {"error": "Sorry, I couldn't do that."}


def test_schema_names_match_spec(rig):
    schemas = tool_schemas(rig.h)
    assert {s.name for s in schemas} == SPEC_TOOLS
    for s in schemas:
        assert s.description and isinstance(s.properties, dict)
        assert set(s.required) <= set(s.properties)


async def test_schema_adapter_delivers_result(rig):
    schema = next(s for s in tool_schemas(rig.h) if s.name == "get_ingredient")
    got = []

    async def result_callback(result, **kwargs):
        got.append(result)

    await schema.handler(SimpleNamespace(arguments={"name": "garlic"}, result_callback=result_callback))
    assert got == [{"say": "three cloves garlic, minced", "candidates": []}]


def test_to_anthropic_tools(rig):
    tools = to_anthropic_tools(tool_schemas(rig.h))
    convert = next(t for t in tools if t["name"] == "convert_units")
    assert convert["input_schema"]["type"] == "object"
    assert set(convert["input_schema"]["required"]) == {"quantity", "from_unit", "to_unit"}
    assert "ingredient" in convert["input_schema"]["properties"]


@pytest.mark.parametrize(
    "phrase",
    [
        "friendly, calm sous-chef",
        "one or two short sentences",
        "never guess quantities, temperatures, or times — use the tools",
        "no lists or markdown",
        "substitutions: answer from your own knowledge",
        "the user's message may end with a [kitchen state: …] note; use it, never read it aloud",
    ],
)
def test_prompt_contains_rules(phrase):
    assert phrase.lower() in SYSTEM_PROMPT.lower()
