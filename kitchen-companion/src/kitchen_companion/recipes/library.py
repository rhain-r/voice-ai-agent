"""The recipe library: six bundled recipes plus any imported during the process lifetime."""

import json
from pathlib import Path

from kitchen_companion.recipes.ingredients import parse_ingredient
from kitchen_companion.recipes.model import Recipe, Step
from kitchen_companion.recipes.state import tokens

BUNDLED_DIR = Path(__file__).parent / "library"

# Words that say nothing about which recipe someone wants.
_QUERY_STOP_WORDS = {
    "a", "an", "and", "the", "with", "for", "of", "some", "recipe", "make", "cook", "want",
    "what", "can", "i", "me", "to", "something", "using", "have", "got",
}


def recipe_from_bundle(data: dict) -> Recipe:
    """Bundled JSON keeps ingredients as plain lines, parsed the same way imported ones are."""
    return Recipe(
        id=data["id"],
        title=data["title"],
        servings=data.get("servings", 4),
        total_time_min=data.get("total_time_min"),
        ingredients=[parse_ingredient(line) for line in data["ingredients"]],
        steps=[Step(index=i, text=s["text"], timer_minutes=s.get("timer_minutes"))
               for i, s in enumerate(data["steps"])],
    )


class Library:
    def __init__(self, recipes: dict[str, Recipe]):
        self._recipes = dict(recipes)

    @classmethod
    def load_bundled(cls) -> "Library":
        recipes = {}
        for path in sorted(BUNDLED_DIR.glob("*.json")):
            recipe = recipe_from_bundle(json.loads(path.read_text(encoding="utf-8")))
            recipes[recipe.id] = recipe
        return cls(recipes)

    def get(self, recipe_id: str) -> Recipe | None:
        return self._recipes.get(recipe_id)

    def all(self) -> list[Recipe]:
        return list(self._recipes.values())

    def add(self, recipe: Recipe) -> None:
        self._recipes[recipe.id] = recipe

    def search(self, query: str, limit: int = 3) -> list[Recipe]:
        wanted = tokens(query) - _QUERY_STOP_WORDS
        if not wanted:
            return []
        scored = []
        for recipe in self._recipes.values():
            words = tokens(recipe.title).union(*(tokens(i.name) for i in recipe.ingredients))
            overlap = len(wanted & words)
            if overlap:
                scored.append((-overlap, recipe.title, recipe))
        scored.sort(key=lambda row: (row[0], row[1]))
        return [recipe for _, _, recipe in scored[:limit]]
