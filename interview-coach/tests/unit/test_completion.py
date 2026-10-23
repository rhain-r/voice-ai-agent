import json

import httpx

from interview_coach.agent.completion import post_completion


async def test_post_completion_retries_then_spills(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    ok = await post_completion(
        "http://api",
        "sec",
        "s_1",
        {"a": 1},
        transport=httpx.MockTransport(handler),
        backoff=0,
        spill_dir=tmp_path,
    )
    assert not ok and len(calls) == 3
    assert json.loads((tmp_path / "s_1.json").read_text()) == {"a": 1}
    assert calls[0].headers["X-Agent-Secret"] == "sec"
    assert calls[0].url.path == "/api/sessions/s_1/complete"


async def test_post_completion_success_first_try(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(202, json={"status": "accepted"})

    ok = await post_completion(
        "http://api/",
        "sec",
        "s_2",
        {"a": 1},
        transport=httpx.MockTransport(handler),
        backoff=0,
        spill_dir=tmp_path,
    )
    assert ok and len(calls) == 1 and not (tmp_path / "s_2.json").exists()


async def test_client_error_is_not_retried(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    ok = await post_completion(
        "http://api",
        "bad",
        "s_3",
        {"a": 1},
        transport=httpx.MockTransport(handler),
        backoff=0,
        spill_dir=tmp_path,
    )
    assert not ok and len(calls) == 1 and (tmp_path / "s_3.json").exists()
