import pytest

from kitchen_companion.pipeline.speakable import KitchenTextFilter, normalize


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1 1/2 cups flour", "one and a half cups flour"),
        ("½ tsp salt", "half a teaspoon salt"),
        ("Bake at 350°F", "Bake at three hundred fifty degrees Fahrenheit"),
        ("180°C", "one hundred eighty degrees Celsius"),
        ("simmer 8-10 min", "simmer eight to ten minutes"),
        ("2 tbsp oil", "two tablespoons oil"),
        ("**Stir** well", "Stir well"),
        ("Step 3: whisk", "Step three: whisk"),
        ("1/4 cup", "a quarter cup"),
        ("tbsp", "tablespoons"),
        ("1 tbsp butter", "one tablespoon butter"),
        ("1½ cups milk", "one and a half cups milk"),
        ("Simmer for 8 minutes.", "Simmer for eight minutes."),
        ("Add 2-3 cloves garlic", "Add two to three cloves garlic"),
        ("Cook 1 min", "Cook one minute"),
        ("about 30 sec", "about thirty seconds"),
        ("Want an 8-minute timer?", "Want an eight-minute timer?"),
        ("250g pasta", "two hundred fifty grams pasta"),
        ("Use 1/2 of it", "Use half of it"),
        ("Heat to 375 °F.", "Heat to three hundred seventy-five degrees Fahrenheit."),
        ("Try *fresh* basil and `salt`", "Try fresh basil and salt"),
        ("See [the video](https://example.com/v) first", "See the video first"),
        ("# Tips\n- Stir often", "Tips\nStir often"),
        ("Vitamin B12 and 4 eggs", "Vitamin B12 and four eggs"),
        ("2 large eggs, medium-low heat", "two large eggs, medium-low heat"),
        ("about 1,000 ml of stock", "about one thousand milliliters of stock"),
        ("2,500 g flour", "two thousand five hundred grams flour"),
        ("eggs, 2, and milk", "eggs, two, and milk"),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


async def test_filter_async():
    f = KitchenTextFilter()
    assert await f.filter("Add 2 tbsp butter.") == "Add two tablespoons butter."
    await f.update_settings({})
    await f.handle_interruption()
    await f.reset_interruption()
