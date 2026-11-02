import pytest

from kitchen_companion.recipes.ingredients import parse_ingredient
from kitchen_companion.recipes.model import Recipe, Step
from kitchen_companion.recipes.state import NO_RECIPE, RecipeSession


def make_recipe(steps=None, lines=None) -> Recipe:
    lines = lines or [
        "1 cup flour",
        "2 tbsp butter, for the sauce",
        "1 tbsp butter, for the topping",
        "2 large eggs",
        "Salt to taste",
    ]
    if steps is None:
        steps = [
            Step(index=0, text="Whisk the flour and eggs."),
            Step(index=1, text="Simmer the sauce for 8 minutes.", timer_minutes=8),
            Step(index=2, text="Serve warm."),
        ]
    return Recipe(
        id="test", title="Test Pancakes", servings=4,
        ingredients=[parse_ingredient(line) for line in lines], steps=steps,
    )


@pytest.fixture
def session() -> RecipeSession:
    s = RecipeSession()
    s.load(make_recipe())
    return s


def test_load_and_navigate():
    s = RecipeSession()
    intro = s.load(make_recipe())
    assert intro == "Okay, Test Pancakes. Three steps. Step one: Whisk the flour and eggs."
    assert s.index == 0
    assert s.next().startswith("Step two: Simmer")
    assert s.index == 1
    assert s.prev() == "Step one: Whisk the flour and eggs."
    assert s.goto(3) == "Step three: Serve warm."
    assert s.repeat() == "Step three: Serve warm."
    assert s.current() == "Step three: Serve warm."


def test_next_at_end_message(session):
    session.goto(3)
    assert session.next() == "That was the last step. Enjoy!"
    assert session.index == 2


def test_prev_at_start_message(session):
    assert session.prev() == "We're at the first step. Step one: Whisk the flour and eggs."
    assert session.index == 0


def test_goto_out_of_range(session):
    assert session.goto(7) == "This recipe has three steps."
    assert session.goto(0) == "This recipe has three steps."
    assert session.index == 0


def test_no_recipe_message():
    s = RecipeSession()
    assert NO_RECIPE == "No recipe loaded yet. Pick one on the screen or ask me to find one."
    for say in (s.next(), s.prev(), s.repeat(), s.current(), s.goto(2), s.scale_to(2)):
        assert say == NO_RECIPE
    assert s.ingredient("flour").text == NO_RECIPE
    assert s.timer_label() is None
    assert s.next_step_text() is None


def test_timer_offer_set_and_cleared(session):
    assert session.pending_timer_offer is None
    assert session.next() == "Step two: Simmer the sauce for 8 minutes. Want an eight-minute timer?"
    assert session.pending_timer_offer == 8
    session.next()
    assert session.pending_timer_offer is None


def test_scale_changes_quantities(session):
    assert session.ingredient("flour").text == "one cup flour"
    assert session.scale_to(8) == "Scaled to eight servings."
    assert session.ingredient("flour").text == "two cups flour"
    assert session.recipe.ingredients[0].qty == 1  # quantities are scaled on read, never mutated
    assert session.snapshot()["servings"] == 8


def test_ingredient_ambiguous(session):
    ans = session.ingredient("butter")
    assert not ans.found
    assert len(ans.candidates) == 2
    assert ans.text == "Do you mean the butter, for the sauce or the butter, for the topping?"


def test_ingredient_plural_match(session):
    ans = session.ingredient("eggs")
    assert ans.found
    assert ans.text == "two large eggs"


def test_ingredient_not_found(session):
    ans = session.ingredient("saffron")
    assert not ans.found and ans.candidates == []
    assert "saffron" in ans.text


def test_ingredient_cloves_plural_both_ways():
    s = RecipeSession()
    s.load(make_recipe(lines=["3 cloves garlic, minced", "2 tomatoes"]))
    assert s.ingredient("garlic cloves").text == "three cloves garlic, minced"  # count unit counts as a name
    assert s.ingredient("tomato").text == "two tomatoes"


def test_zero_steps_navigation():
    s = RecipeSession()
    intro = s.load(make_recipe(steps=[]))
    assert intro.endswith("This recipe has no steps.")
    for say in (s.next(), s.prev(), s.repeat(), s.current(), s.goto(1)):
        assert say == "This recipe has no steps."
    assert s.timer_label() is None
    assert s.snapshot()["total"] == 0


def test_ingredient_without_qty_returns_raw(session):
    ans = session.ingredient("salt")
    assert ans.found
    assert ans.text == "Salt to taste"


def test_timer_label_uses_verb(session):
    session.goto(2)
    assert session.timer_label() == "simmer"
    session.goto(3)
    assert session.timer_label() == "step 3"


def test_snapshot_shape(session):
    snap = session.snapshot()
    assert snap["id"] == "test" and snap["title"] == "Test Pancakes"
    assert (snap["index"], snap["total"], snap["servings"]) == (0, 3, 4)
    assert snap["steps"][1] == "Simmer the sauce for 8 minutes."
    assert snap["ingredients"][0] == {"text": "one cup flour", "checked": False}
    assert snap["ingredients"][4] == {"text": "Salt to taste", "checked": False}


def test_next_step_text(session):
    assert session.next_step_text() == "Simmer the sauce for 8 minutes."
    session.goto(3)
    assert session.next_step_text() is None


def test_scale_rejects_zero(session):
    assert session.scale_to(0) == "I can only scale to one serving or more."
    assert session.snapshot()["servings"] == 4


def test_exact_name_beats_partial():
    s = RecipeSession()
    s.load(make_recipe(lines=["2 tbsp butter", "1 tbsp peanut butter"]))
    assert s.ingredient("butter").text == "two tablespoons butter"
