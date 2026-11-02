"""Claude's tools, bound to this kitchen's live recipe and timers.

Every handler takes the tool arguments as a dict and returns a dict for the tool result: "say" is
speakable text for Claude to base its reply on, "error" a speakable problem. A handler never raises.
"""

import functools
import logging
from collections.abc import Awaitable, Callable
from fractions import Fraction
from typing import Any

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

from kitchen_companion.events import EventSink
from kitchen_companion.recipes.library import Library
from kitchen_companion.recipes.model import Recipe, to_fraction
from kitchen_companion.recipes.state import RecipeSession
from kitchen_companion.recipes.units import (
    ConversionError,
    convert,
    convert_temp,
    normalize_unit,
    number_words,
    round_kitchen,
    speak_quantity,
    unit_name,
)
from kitchen_companion.timers import TimerService, cancel_reply, remaining_reply, started_reply

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Sorry, I couldn't do that."
_TEMP_SCALES = {
    "f": "F",
    "fahrenheit": "F",
    "°f": "F",
    "c": "C",
    "celsius": "C",
    "centigrade": "C",
    "°c": "C",
}
_SCALE_NAMES = {"F": "Fahrenheit", "C": "Celsius"}
_LEAFY = (
    "spinach",
    "kale",
    "lettuce",
    "arugula",
    "rocket",
    "greens",
    "chard",
    "basil",
    "parsley",
    "cilantro",
)

Result = dict[str, Any]


def _safe(method: Callable[..., Awaitable[Result]]) -> Callable[..., Awaitable[Result]]:
    @functools.wraps(method)
    async def wrapper(self, args: dict) -> Result:
        try:
            return await method(self, args or {})
        except Exception:
            logger.exception("tool %s failed with %r", method.__name__, args)
            return {"error": GENERIC_ERROR}

    return wrapper


def _quantity(value: Any) -> Fraction:
    if isinstance(value, str) and " " in value.strip():
        return sum((to_fraction(part) for part in value.split()), Fraction(0))
    return to_fraction(value)


def _temp_scale(unit: str) -> str | None:
    key = unit.strip().lower().replace("degrees", "").strip()
    return _TEMP_SCALES.get(key)


class ToolHandlers:
    def __init__(
        self,
        recipe: RecipeSession,
        timers: TimerService,
        library: Library,
        sink: EventSink,
        on_recipe_loaded: Callable[[Recipe], Awaitable[None]],
    ):
        self.recipe = recipe
        self.timers = timers
        self.library = library
        self.sink = sink
        self.on_recipe_loaded = on_recipe_loaded

    @_safe
    async def search_recipes(self, args: dict) -> Result:
        found = self.library.search(str(args.get("query", "")))
        return {"results": [{"id": r.id, "title": r.title} for r in found]}

    @_safe
    async def load_recipe(self, args: dict) -> Result:
        recipe = self.library.get(str(args.get("recipe_id", "")))
        if recipe is None:
            return {"error": "I don't have that recipe. Try searching for it first."}
        say = self.recipe.load(recipe)
        await self.on_recipe_loaded(recipe)
        await self.sink.recipe_state(self.recipe.snapshot())
        return {"say": say}

    @_safe
    async def get_ingredient(self, args: dict) -> Result:
        answer = self.recipe.ingredient(str(args.get("name", "")))
        return {"say": answer.text, "candidates": answer.candidates}

    @_safe
    async def scale_recipe(self, args: dict) -> Result:
        say = self.recipe.scale_to(int(args["servings"]))
        await self.sink.recipe_state(self.recipe.snapshot())
        return {"say": say}

    @_safe
    async def convert_units(self, args: dict) -> Result:
        qty = _quantity(args["quantity"])
        src_raw, dst_raw = str(args["from_unit"]), str(args["to_unit"])
        ingredient = args.get("ingredient") or None

        src_temp, dst_temp = _temp_scale(src_raw), _temp_scale(dst_raw)
        if src_temp and dst_temp:
            out = convert_temp(float(qty), src_temp, dst_temp)
            return {
                "say": f"{speak_quantity(qty, None)} degrees {_SCALE_NAMES[src_temp]} is about "
                f"{number_words(out)} degrees {_SCALE_NAMES[dst_temp]}."
            }

        src, dst = normalize_unit(src_raw), normalize_unit(dst_raw)
        if src is None or dst is None:
            return {"error": f"I don't know the unit {src_raw if src is None else dst_raw}."}
        try:
            out = convert(qty, src, dst, ingredient)
        except ConversionError:
            if not ingredient:
                return {
                    "error": f"I can't convert {unit_name(src)} to {unit_name(dst)} without knowing "
                    "the ingredient."
                }
            leafy = any(leaf in ingredient.lower() for leaf in _LEAFY)
            hint = ", but it's roughly a handful per cup" if leafy else ""
            return {
                "error": f"I can't convert {unit_name(src)} of {ingredient} to {unit_name(dst)} "
                f"reliably{hint}."
            }
        of = f" of {ingredient}" if ingredient else ""
        return {
            "say": f"{speak_quantity(qty, src)}{of} is about {speak_quantity(round_kitchen(out, dst), dst)}."
        }

    @_safe
    async def go_to_step(self, args: dict) -> Result:
        step = args.get("step")
        word = str(step).strip().lower()
        if isinstance(step, int) or word.isdigit():
            say = self.recipe.goto(int(word))
        elif word == "next":
            say = self.recipe.next()
        elif word in ("prev", "previous", "back"):
            say = self.recipe.prev()
        elif word in ("repeat", "current", "again"):
            say = self.recipe.repeat()
        else:
            return {"error": "Tell me a step number, or next, prev or repeat."}
        await self.sink.recipe_state(self.recipe.snapshot())
        return {"say": say}

    @_safe
    async def set_timer(self, args: dict) -> Result:
        minutes = float(args["minutes"])
        if minutes <= 0:
            return {"error": "Timers need a positive number of minutes."}
        timer = self.timers.start(minutes, args.get("label") or self.recipe.timer_label())
        await self.sink.timers(self.timers.snapshot())
        return {"say": started_reply(timer)}

    @_safe
    async def cancel_timer(self, args: dict) -> Result:
        say, changed = cancel_reply(self.timers, args.get("label") or None)
        if changed:
            await self.sink.timers(self.timers.snapshot())
        return {"say": say}

    @_safe
    async def list_timers(self, args: dict) -> Result:
        timers = [{"label": t.label, "seconds_left": round(secs)} for t, secs in self.timers.remaining()]
        return {"timers": timers, "say": remaining_reply(self.timers)}


_STR = {"type": "string"}

# name -> (description, properties, required)
_TOOLS: dict[str, tuple[str, dict, list[str]]] = {
    "search_recipes": (
        "Search the recipe library by title or ingredients. Returns up to three matches.",
        {"query": {**_STR, "description": "Words from the dish or its ingredients, e.g. 'eggs spinach'."}},
        ["query"],
    ),
    "load_recipe": (
        "Start cooking a recipe from the library. Returns the intro and first step to say.",
        {"recipe_id": {**_STR, "description": "The id from search_recipes."}},
        ["recipe_id"],
    ),
    "get_ingredient": (
        "How much of an ingredient the current recipe needs, scaled to the current servings.",
        {"name": {**_STR, "description": "The ingredient, e.g. 'butter'."}},
        ["name"],
    ),
    "scale_recipe": (
        "Scale the current recipe to a number of servings.",
        {"servings": {"type": "integer", "minimum": 1}},
        ["servings"],
    ),
    "convert_units": (
        "Convert a quantity between units (cups, tbsp, tsp, ml, l, fl oz, g, kg, oz, lb) or temperatures "
        "(F, C). Volume to weight needs the ingredient.",
        {
            "quantity": {
                "type": ["number", "string"],
                "description": "A number or fraction, e.g. 1.5 or '1 1/2'.",
            },
            "from_unit": _STR,
            "to_unit": _STR,
            "ingredient": {**_STR, "description": "The ingredient, needed for volume to weight."},
        },
        ["quantity", "from_unit", "to_unit"],
    ),
    "go_to_step": (
        "Move through the current recipe.",
        {
            "step": {
                "type": ["integer", "string"],
                "description": "A step number, or 'next', 'prev' or 'repeat'.",
            }
        },
        ["step"],
    ),
    "set_timer": (
        "Start a kitchen timer. It announces itself when it's done.",
        {
            "minutes": {"type": "number", "description": "Length in minutes; 1.5 is a minute and a half."},
            "label": {**_STR, "description": "What it's for, e.g. 'pasta'. Optional."},
        },
        ["minutes"],
    ),
    "cancel_timer": (
        "Cancel a running timer. Without a label it cancels the only timer, or asks which one.",
        {"label": {**_STR, "description": "The timer's label, e.g. 'pasta'. Optional."}},
        [],
    ),
    "list_timers": ("List running timers and how long each has left.", {}, []),
}


def tool_schemas(handlers: ToolHandlers) -> list[FunctionSchema]:
    def adapter(method: Callable[[dict], Awaitable[Result]]):
        async def handler(params: FunctionCallParams) -> None:
            await params.result_callback(await method(dict(params.arguments or {})))

        return handler

    return [
        FunctionSchema(name, description, properties, required, handler=adapter(getattr(handlers, name)))
        for name, (description, properties, required) in _TOOLS.items()
    ]


def to_anthropic_tools(schemas: list[FunctionSchema]) -> list[dict]:
    return [
        {
            "name": s.name,
            "description": s.description,
            "input_schema": {"type": "object", "properties": s.properties, "required": s.required},
        }
        for s in schemas
    ]
