"""The recipe position, scale and timer offer for one kitchen. Every reply is speakable text."""

import re
from dataclasses import dataclass, field
from fractions import Fraction

from kitchen_companion.recipes.model import Ingredient, Recipe
from kitchen_companion.recipes.units import COUNT_UNITS, number_words, round_kitchen, speak_quantity

NO_RECIPE = "No recipe loaded yet. Pick one on the screen or ask me to find one."
NO_STEPS = "This recipe has no steps."
LAST_STEP = "That was the last step. Enjoy!"
FIRST_STEP = "We're at the first step. "

COOKING_VERBS = {
    "boil", "simmer", "bake", "roast", "fry", "saute", "cook", "rest", "chill", "marinate",
    "steam", "toast", "sear", "proof", "rise", "knead", "whisk",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _singular(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith("es") and token[:-2].endswith(("s", "x", "z", "ch", "sh", "o")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> set[str]:
    """Lowercased, punctuation-free, singularized word set used for fuzzy ingredient matching."""
    return {_singular(t) for t in _WORD_RE.findall(text.lower().replace("é", "e"))}


def _article(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


@dataclass
class IngredientAnswer:
    found: bool
    text: str
    candidates: list[str] = field(default_factory=list)


class RecipeSession:
    def __init__(self) -> None:
        self.recipe: Recipe | None = None
        self.index = 0
        self.scale = Fraction(1)
        self.pending_timer_offer: int | None = None

    # -- loading and navigation ------------------------------------------------------------------

    def load(self, recipe: Recipe) -> str:
        self.recipe = recipe
        self.index = 0
        self.scale = Fraction(1)
        self.pending_timer_offer = None
        n = len(recipe.steps)
        if n == 0:
            return f"Okay, {recipe.title}. {NO_STEPS}"
        count = "One step" if n == 1 else f"{number_words(n).capitalize()} steps"
        return f"Okay, {recipe.title}. {count}. " + self.current()

    def _guard(self) -> str | None:
        if self.recipe is None:
            return NO_RECIPE
        if not self.recipe.steps:
            self.pending_timer_offer = None
            return NO_STEPS
        return None

    def current(self) -> str:
        if (msg := self._guard()) is not None:
            return msg
        step = self.recipe.steps[self.index]
        say = f"Step {number_words(self.index + 1)}: {step.text}"
        if step.timer_minutes:
            words = number_words(step.timer_minutes)
            say += f" Want {_article(words)} {words}-minute timer?"
            self.pending_timer_offer = step.timer_minutes
        else:
            self.pending_timer_offer = None
        return say

    def next(self) -> str:
        if (msg := self._guard()) is not None:
            return msg
        if self.index >= len(self.recipe.steps) - 1:
            return LAST_STEP
        self.index += 1
        return self.current()

    def prev(self) -> str:
        if (msg := self._guard()) is not None:
            return msg
        if self.index == 0:
            return FIRST_STEP + self.current()
        self.index -= 1
        return self.current()

    def goto(self, n: int) -> str:
        if (msg := self._guard()) is not None:
            return msg
        total = len(self.recipe.steps)
        if not 1 <= n <= total:
            return f"This recipe has {number_words(total)} steps."
        self.index = n - 1
        return self.current()

    def repeat(self) -> str:
        return self.current()

    # -- scaling and ingredients -----------------------------------------------------------------

    @property
    def servings(self) -> int | None:
        if self.recipe is None:
            return None
        return round(self.recipe.servings * self.scale)

    def scale_to(self, servings: int) -> str:
        if self.recipe is None:
            return NO_RECIPE
        if servings < 1:
            return "I can only scale to one serving or more."
        self.scale = Fraction(servings, self.recipe.servings or 1)
        return f"Scaled to {number_words(servings)} servings."

    def ingredient_text(self, ing: Ingredient) -> str:
        """The ingredient line as spoken, with its quantity scaled and rounded for the kitchen."""
        if ing.qty is None:
            return ing.raw.strip()
        low = round_kitchen(ing.qty * self.scale, ing.unit)
        if ing.qty_max is not None:
            high = round_kitchen(ing.qty_max * self.scale, ing.unit)
            amount = f"{speak_quantity(low, None)} to {speak_quantity(high, ing.unit)}"
        else:
            amount = speak_quantity(low, ing.unit)
        text = f"{amount} {ing.name}"
        return f"{text}, {ing.note}" if ing.note else text

    def ingredient(self, name: str) -> IngredientAnswer:
        if self.recipe is None:
            return IngredientAnswer(False, NO_RECIPE)
        query = tokens(name)
        if not query:
            return IngredientAnswer(False, "Which ingredient?")

        def name_tokens(ing: Ingredient) -> set[str]:
            extra = {ing.unit} if ing.unit in COUNT_UNITS else set()
            return tokens(ing.name) | extra

        matches = [ing for ing in self.recipe.ingredients if query <= name_tokens(ing)]
        exact = [ing for ing in matches if tokens(ing.name) == query]
        if len(matches) > 1 and len(exact) == 1:
            matches = exact
        if not matches:
            return IngredientAnswer(False, f"I don't see {name} in this recipe.")
        if len(matches) == 1:
            return IngredientAnswer(True, self.ingredient_text(matches[0]))
        candidates = [f"the {ing.name}, {ing.note}" if ing.note else f"the {ing.name}" for ing in matches]
        return IngredientAnswer(False, "Do you mean " + " or ".join(candidates) + "?", candidates)

    # -- timers and display ----------------------------------------------------------------------

    def timer_label(self) -> str | None:
        if self.recipe is None or not self.recipe.steps:
            return None
        for word in _WORD_RE.findall(self.recipe.steps[self.index].text.lower().replace("é", "e")):
            if word in COOKING_VERBS:
                return word
        return f"step {self.index + 1}"

    def next_step_text(self) -> str | None:
        if self.recipe is None or self.index + 1 >= len(self.recipe.steps):
            return None
        return self.recipe.steps[self.index + 1].text

    def snapshot(self) -> dict:
        if self.recipe is None:
            return {"id": None, "title": None, "index": 0, "total": 0, "servings": None,
                    "steps": [], "ingredients": []}
        return {
            "id": self.recipe.id,
            "title": self.recipe.title,
            "index": self.index,
            "total": len(self.recipe.steps),
            "servings": self.servings,
            "steps": [s.text for s in self.recipe.steps],
            "ingredients": [{"text": self.ingredient_text(i), "checked": False}
                            for i in self.recipe.ingredients],
        }
