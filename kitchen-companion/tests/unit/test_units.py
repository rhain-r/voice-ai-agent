from fractions import Fraction as F

import pytest

from kitchen_companion.recipes.model import Ingredient, Recipe, Step
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


@pytest.mark.parametrize(
    "q,u,exp",
    [
        (F(3, 2), "cup", "one and a half cups"),
        (F(1, 2), "tsp", "half a teaspoon"),
        (F(1, 4), "cup", "a quarter cup"),
        (F(3, 4), "cup", "three quarters of a cup"),
        (F(1, 3), "cup", "a third of a cup"),
        (F(1, 8), "tsp", "an eighth of a teaspoon"),
        (F(1), "tbsp", "one tablespoon"),
        (F(3), "tbsp", "three tablespoons"),
        (F(2), None, "two"),
        (F(2), "clove", "two cloves"),
        (F(9, 4), "cup", "two and a quarter cups"),
        (F(250), "g", "two hundred fifty grams"),
    ],
)
def test_speak_quantity(q, u, exp):
    assert speak_quantity(q, u) == exp


def test_convert_volume():
    assert round_kitchen(convert(F(1), "cup", "ml"), "ml") == 237


def test_convert_butter_cup_to_grams():
    assert round_kitchen(convert(F(1), "cup", "g", "unsalted butter"), "g") == 216  # 236.588*0.911


def test_convert_needs_density():
    with pytest.raises(ConversionError):
        convert(F(1), "cup", "g", "spinach")


def test_convert_mass_to_volume_with_density():
    assert round_kitchen(convert(F(1000), "g", "l", "water"), "l") == 1


def test_convert_unknown_unit_raises():
    with pytest.raises(ConversionError):
        convert(F(1), "cup", "bushel")


def test_convert_temp():
    assert (convert_temp(350, "F", "C"), convert_temp(180, "C", "F")) == (175, 355)


def test_normalize_unit_case():
    got = (normalize_unit("T"), normalize_unit("t"), normalize_unit("Tablespoons"))
    assert got == ("tbsp", "tsp", "tbsp")


@pytest.mark.parametrize(
    "token,exp",
    [("cups", "cup"), ("Tbsp", "tbsp"), ("teaspoon", "tsp"), ("fl oz", "floz"), ("grams", "g"),
     ("kilograms", "kg"), ("pounds", "lb"), ("lbs", "lb"), ("ounces", "oz"), ("mL", "ml"),
     ("liters", "l"), ("cloves", "clove"), ("cans", "can"), ("pinch", "pinch"), ("banana", None)],
)
def test_normalize_unit_aliases(token, exp):
    assert normalize_unit(token) == exp


def test_round_kitchen_eighths():
    assert round_kitchen(F(1, 3), "cup") == F(3, 8)


def test_round_kitchen_whole_grams():
    assert round_kitchen(F(4331, 20), "g") == 217  # 216.55 rounds half-up
    assert round_kitchen(F(1, 4), "g") == 1  # a real amount never rounds down to nothing


def test_unit_name():
    assert (unit_name("tbsp"), unit_name("cup", plural=False), unit_name("floz")) == (
        "tablespoons", "cup", "fluid ounces")


def test_speak_quantity_snaps_odd_fractions():
    assert speak_quantity(F(2, 5), "cup") == "three eighths of a cup"
    assert speak_quantity(F(1, 2), "oz") == "half an ounce"


@pytest.mark.parametrize(
    "n,exp",
    [(0, "zero"), (7, "seven"), (15, "fifteen"), (42, "forty-two"), (100, "one hundred"),
     (350, "three hundred fifty"), (1000, "one thousand"), (2025, "two thousand twenty-five"),
     (9999, "nine thousand nine hundred ninety-nine")],
)
def test_number_words(n, exp):
    assert number_words(n) == exp


def test_model_round_trips_fraction():
    ing = Ingredient(qty=F(3, 2), unit="cup", name="flour", raw="1 1/2 cups flour")
    r = Recipe(id="x", title="X", ingredients=[ing], steps=[Step(index=0, text="Mix.")])
    dumped = r.model_dump(mode="json")
    assert dumped["ingredients"][0]["qty"] == "3/2"
    again = Recipe.model_validate(dumped)
    assert again.ingredients[0].qty == F(3, 2)
    assert again.servings == 4
