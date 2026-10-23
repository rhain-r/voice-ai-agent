from fractions import Fraction as F

import pytest

from kitchen_companion.recipes.ingredients import parse_ingredient

ROWS = [
    # input, qty, qty_max, unit, name, note
    ("2 cups flour", F(2), None, "cup", "flour", None),
    ("1 1/2 cups whole milk", F(3, 2), None, "cup", "whole milk", None),
    ("½ tsp salt", F(1, 2), None, "tsp", "salt", None),
    ("1½ tbsp olive oil", F(3, 2), None, "tbsp", "olive oil", None),
    ("2-3 cloves garlic, minced", F(2), F(3), "clove", "garlic", "minced"),
    ("3 Tbsp butter", F(3), None, "tbsp", "butter", None),
    ("1 T sugar", F(1), None, "tbsp", "sugar", None),
    ("1 t vanilla extract", F(1), None, "tsp", "vanilla extract", None),
    ("1 (14 oz) can diced tomatoes", F(1), None, "can", "diced tomatoes", "14 oz"),
    ("0.5 lb ground beef", F(1, 2), None, "lb", "ground beef", None),
    ("4 large eggs", F(4), None, None, "large eggs", None),
    ("200g spaghetti", F(200), None, "g", "spaghetti", None),
    ("Salt and pepper to taste", None, None, None, "Salt and pepper to taste", None),
    ("a pinch of nutmeg", F(1), None, "pinch", "nutmeg", None),
    ("1/4 cup sugar", F(1, 4), None, "cup", "sugar", None),
    ("3/4 cup brown sugar, packed", F(3, 4), None, "cup", "brown sugar", "packed"),
    ("2 tablespoons unsalted butter, melted", F(2), None, "tbsp", "unsalted butter", "melted"),
    ("1 teaspoon baking powder", F(1), None, "tsp", "baking powder", None),
    ("2 1/4 cups all-purpose flour", F(9, 4), None, "cup", "all-purpose flour", None),
    ("1 onion, finely chopped", F(1), None, None, "onion", "finely chopped"),
    ("8 oz cream cheese, softened", F(8), None, "oz", "cream cheese", "softened"),
    ("1 lb boneless chicken thighs (about 4)", F(1), None, "lb", "boneless chicken thighs", "about 4"),
    ("500 ml chicken stock", F(500), None, "ml", "chicken stock", None),
    ("1 can (400 g) chickpeas, drained", F(1), None, "can", "chickpeas", "400 g, drained"),
    ("2 garlic cloves, minced", F(2), None, None, "garlic cloves", "minced"),
    ("1 ½ cups milk", F(3, 2), None, "cup", "milk", None),
    ("1 1/2 - 2 cups broth", F(3, 2), F(2), "cup", "broth", None),
    ("2 to 3 tbsp water", F(2), F(3), "tbsp", "water", None),
    ("10 sprigs fresh thyme", F(10), None, "sprig", "fresh thyme", None),
    ("1 stick butter", F(1), None, "stick", "butter", None),
    ("1 kg potatoes, peeled and diced", F(1), None, "kg", "potatoes", "peeled and diced"),
    ("3 fl oz heavy cream", F(3), None, "floz", "heavy cream", None),
    ("¼ teaspoon ground cinnamon", F(1, 4), None, "tsp", "ground cinnamon", None),
    ("Fresh basil, for garnish", None, None, None, "Fresh basil, for garnish", None),
    ("1 cup (2 sticks) butter, softened", F(1), None, "cup", "butter", "2 sticks, softened"),
    ("1.5 cups rice", F(3, 2), None, "cup", "rice", None),
    ("1 tbsp. soy sauce", F(1), None, "tbsp", "soy sauce", None),
    ("2–3 tbsp lemon juice", F(2), F(3), "tbsp", "lemon juice", None),
]


@pytest.mark.parametrize("line,qty,qty_max,unit,name,note", ROWS)
def test_parse_ingredient(line, qty, qty_max, unit, name, note):
    ing = parse_ingredient(line)
    assert (ing.qty, ing.qty_max, ing.unit, ing.name, ing.note) == (qty, qty_max, unit, name, note)
    assert ing.raw == line


@pytest.mark.parametrize("line", ["", "   ", "(optional)", "1", "½", "a few leaves of basil"])
def test_parse_ingredient_never_raises(line):
    ing = parse_ingredient(line)
    assert ing.raw == line
    assert ing.name is not None
