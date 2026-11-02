from pathlib import Path

import httpx
import pytest

from kitchen_companion.recipes.importer import (
    ImportBlocked,
    RecipeNotFound,
    extract_recipe,
    import_recipe,
    parse_iso_minutes,
    timer_hint,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "jsonld"
PUBLIC = {"example.com": ["93.184.216.34"], "recipes.test": ["93.184.216.35"]}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def resolver(table: dict[str, list[str]]):
    def resolve(host: str) -> list[str]:
        return table.get(host, [])

    return resolve


def test_parse_iso_minutes():
    assert parse_iso_minutes("PT1H15M") == 75
    assert parse_iso_minutes("PT45M") == 45
    assert parse_iso_minutes("P0DT2H") == 120
    assert parse_iso_minutes(None) is None
    assert parse_iso_minutes("soon") is None


def test_timer_hint():
    assert timer_hint("simmer for 8-10 minutes") == 8
    assert timer_hint("bake 1 hour") == 60
    assert timer_hint("stir for 30 seconds") is None
    assert timer_hint("simmer for 8–10 minutes") == 8
    assert timer_hint("cook 5 to 7 mins") == 5
    assert timer_hint("Preheat the oven.") is None


def test_extract_top_level():
    r = extract_recipe(fixture("top_level.html"), "https://example.com/lemon-rice")
    assert r.title == "Lemon Rice"
    assert r.servings == 6 and r.total_time_min == 35
    assert r.source_url == "https://example.com/lemon-rice"
    assert [i.name for i in r.ingredients] == ["long-grain rice", "butter", "lemon", "Salt to taste"]
    assert [s.text for s in r.steps][2] == "Stir in the butter & lemon zest."
    assert r.steps[1].timer_minutes == 15
    assert r.id.startswith("lemon-rice-") and len(r.id) == len("lemon-rice-") + 6


def test_extract_graph():
    r = extract_recipe(fixture("graph.html"), "https://example.com/g")
    assert r.title == "Graph Granola" and r.servings == 8
    assert r.steps[0].timer_minutes == 25


def test_extract_type_list():
    r = extract_recipe(fixture("type_list.html"), "https://example.com/l")
    assert r.title == "Listed Lentils" and r.servings == 2
    assert [s.text for s in r.steps] == ["Boil the lentils for 20 minutes."]


def test_extract_howtosection_flattens():
    r = extract_recipe(fixture("howtosection.html"), "https://example.com/c")
    assert [s.index for s in r.steps] == [0, 1, 2, 3]
    assert r.steps[3].text == "Spread over the cooled cake."
    assert r.servings == 4  # default when recipeYield is missing


def test_extract_string_instructions():
    r = extract_recipe(fixture("string_instructions.html"), "https://example.com/s")
    assert [s.text for s in r.steps] == [
        "Chop the onion.",
        "Simmer the onion in the stock for 10 minutes.",
        "Serve.",
    ]
    assert r.steps[1].timer_minutes == 10


def test_extract_missing_raises():
    with pytest.raises(RecipeNotFound):
        extract_recipe(fixture("missing.html"), "https://example.com/m")


async def test_import_blocks_private_ip():
    with pytest.raises(ImportBlocked):
        await import_recipe("https://recipes.test/x", resolve=resolver({"recipes.test": ["10.0.0.5"]}))


async def test_import_blocks_if_any_address_private():
    table = {"recipes.test": ["93.184.216.35", "127.0.0.1"]}
    with pytest.raises(ImportBlocked):
        await import_recipe("https://recipes.test/x", resolve=resolver(table))


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
    ],
)
async def test_import_blocks_ip_literals(url):
    with pytest.raises(ImportBlocked):
        await import_recipe(url, resolve=resolver({}))


async def test_import_blocks_non_http():
    with pytest.raises(ImportBlocked):
        await import_recipe("file:///etc/passwd", resolve=resolver(PUBLIC))


async def test_import_redirect_to_private_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"Location": "http://internal/"})
        return httpx.Response(200, text=fixture("top_level.html"))

    table = {**PUBLIC, "internal": ["127.0.0.1"]}
    with pytest.raises(ImportBlocked):
        await import_recipe(
            "http://example.com/r", transport=httpx.MockTransport(handler), resolve=resolver(table)
        )


async def test_import_too_many_redirects():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/again"})

    with pytest.raises(RecipeNotFound):
        await import_recipe(
            "http://example.com/r", transport=httpx.MockTransport(handler), resolve=resolver(PUBLIC)
        )


async def test_import_size_cap():
    big = b"<html>" + b"x" * (4 * 1024 * 1024) + b"</html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big)

    with pytest.raises(RecipeNotFound, match="page is too large"):
        await import_recipe(
            "https://example.com/big", transport=httpx.MockTransport(handler), resolve=resolver(PUBLIC)
        )


async def test_import_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    with pytest.raises(RecipeNotFound):
        await import_recipe(
            "https://example.com/404", transport=httpx.MockTransport(handler), resolve=resolver(PUBLIC)
        )


async def test_import_success():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"Location": "https://example.com/lemon-rice"})
        return httpx.Response(200, text=fixture("top_level.html"), headers={"content-type": "text/html"})

    r = await import_recipe(
        "https://example.com/start", transport=httpx.MockTransport(handler), resolve=resolver(PUBLIC)
    )
    assert r.title == "Lemon Rice" and len(r.steps) == 3
    assert r.source_url == "https://example.com/lemon-rice"
