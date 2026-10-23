from kitchen_companion.recipes.library import Library
from kitchen_companion.recipes.model import Recipe


def test_bundled_library_has_six_valid():
    lib = Library.load_bundled()
    recipes = lib.all()
    assert len(recipes) == 6
    for r in recipes:
        assert isinstance(r, Recipe)
        assert 5 <= len(r.steps) <= 9, r.id
        assert any(s.timer_minutes for s in r.steps), r.id
        assert [s.index for s in r.steps] == list(range(len(r.steps)))
        with_qty = [i for i in r.ingredients if i.qty is not None]
        assert len(with_qty) >= len(r.ingredients) - 1, r.id  # real quantities, at most one "to taste"
        assert lib.get(r.id) is r


def test_search_eggs_spinach_finds_omelette():
    results = Library.load_bundled().search("eggs spinach")
    assert results[0].id == "spinach-feta-omelette"
    assert len(results) <= 3


def test_search_by_title_word():
    assert Library.load_bundled().search("pancakes")[0].id == "fluffy-pancakes"


def test_search_no_overlap_empty():
    assert Library.load_bundled().search("quinoa kale smoothie") == []
    assert Library.load_bundled().search("") == []


def test_add_makes_recipe_searchable():
    lib = Library({})
    r = Recipe(id="x-1", title="Saffron Risotto", ingredients=[], steps=[])
    lib.add(r)
    assert lib.get("x-1") is r and lib.search("risotto") == [r]
