import asyncio

import pytest
from fastapi.testclient import TestClient

from kitchen_companion.config import Settings
from kitchen_companion.recipes.importer import ImportBlocked, RecipeNotFound
from kitchen_companion.recipes.library import Library
from kitchen_companion.registry import KitchenRegistry
from kitchen_companion.server import create_app
from tests.fakes import fixture_recipe

SETTINGS = Settings(_env_file=None, anthropic_api_key="a", deepgram_api_key="d")


class FakeWebRTC:
    def __init__(self):
        self.patches = []

    async def handle_web_request(self, request, callback):
        await callback(f"conn-for-{request.request_data['kitchen_id']}")
        return {"sdp": "answer-sdp", "type": "answer", "pc_id": "pc-1"}

    async def handle_patch_request(self, request):
        self.patches.append(request)

    async def close(self):
        pass


def make_client(importer=None, bot_runner=None):
    runs = []

    async def fake_bot(conn, kitchen, library, settings):
        runs.append((conn, kitchen.id))

    async def fake_importer(url):
        return fixture_recipe()

    library = Library.load_bundled()
    app = create_app(
        SETTINGS,
        registry=KitchenRegistry(),
        library=library,
        bot_runner=bot_runner or fake_bot,
        importer=importer or fake_importer,
        webrtc_handler=FakeWebRTC(),
    )
    return TestClient(app), library, runs


def test_health():
    client, _, _ = make_client()
    with client:
        assert client.get("/api/health").json() == {"ok": True}


@pytest.mark.parametrize(
    "request_data", [{"kitchen_id": "bad"}, {"kitchen_id": "has spaces in it"}, {}, None]
)
def test_offer_rejects_bad_kitchen_id(request_data):
    client, _, runs = make_client()
    with client:
        r = client.post("/api/offer", json={"sdp": "v=0", "type": "offer", "request_data": request_data})
    assert r.status_code == 422
    assert runs == []


def test_offer_starts_bot_for_kitchen():
    client, _, runs = make_client()
    with client:
        r = client.post(
            "/api/offer",
            json={"sdp": "v=0", "type": "offer", "requestData": {"kitchen_id": "kitchen-abc123"}},
        )
        assert r.status_code == 200
        assert r.json() == {"sdp": "answer-sdp", "type": "answer", "pc_id": "pc-1"}
        for _ in range(20):
            if runs:
                break
            client.portal.call(asyncio.sleep, 0.01)
    assert runs == [("conn-for-kitchen-abc123", "kitchen-abc123")]


def test_offer_patch_forwards_candidates():
    client, _, _ = make_client()
    with client:
        r = client.patch(
            "/api/offer",
            json={
                "pc_id": "pc-1",
                "candidates": [
                    {
                        "candidate": "candidate:1 1 UDP 1 1.2.3.4 5 typ host",
                        "sdp_mid": "0",
                        "sdp_mline_index": 0,
                    },
                    {"candidate": "", "sdpMid": "0", "sdpMLineIndex": 0},
                ],
            },
        )
        assert r.status_code == 200
        handler = client.app.state.webrtc
    patch = handler.patches[0]
    assert patch.pc_id == "pc-1" and [c.sdp_mid for c in patch.candidates] == ["0", "0"]


def test_recipes_list_and_get():
    client, _, _ = make_client()
    with client:
        listed = client.get("/api/recipes").json()
        assert len(listed) == 6
        assert set(listed[0]) == {"id", "title", "servings", "total_time_min"}
        one = client.get("/api/recipes/tomato-soup").json()
        assert one["title"] == "Tomato Soup" and len(one["steps"]) == 7
        assert client.get("/api/recipes/nope").status_code == 404


def test_import_maps_errors_to_422():
    async def blocked(url):
        raise ImportBlocked("That address isn't allowed.")

    async def missing(url):
        raise RecipeNotFound("Couldn't find a recipe on that page.")

    for importer, detail in (
        (blocked, "That address isn't allowed."),
        (missing, "Couldn't find a recipe on that page."),
    ):
        client, _, _ = make_client(importer=importer)
        with client:
            r = client.post("/api/recipes/import", json={"url": "http://10.0.0.1/"})
        assert r.status_code == 422 and r.json() == {"detail": detail}


def test_import_success_adds_to_library():
    client, library, _ = make_client()
    with client:
        r = client.post("/api/recipes/import", json={"url": "https://example.com/x"})
        assert r.status_code == 200 and r.json()["id"] == "fixture"
        assert library.get("fixture") is not None
        assert any(x["id"] == "fixture" for x in client.get("/api/recipes").json())


def test_serves_web_dist_when_present(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Kitchen</title>")
    settings = SETTINGS.model_copy(update={"web_dist": str(tmp_path)})
    app = create_app(
        settings, registry=KitchenRegistry(), library=Library.load_bundled(), webrtc_handler=FakeWebRTC()
    )
    with TestClient(app) as client:
        assert "Kitchen" in client.get("/").text
        assert client.get("/api/health").json() == {"ok": True}
