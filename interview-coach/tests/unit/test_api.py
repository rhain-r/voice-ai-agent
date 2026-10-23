import base64
import json

import pytest
from fastapi.testclient import TestClient

from interview_coach.api.db import Store
from interview_coach.api.main import create_app
from interview_coach.config import Settings
from tests.fakes import FakeGrader

SECRET = "test-agent-secret"
SETUP = {"role": "Data Analyst", "level": "junior", "style": "behavioral", "count": 3}
PAYLOAD = {
    "status": "completed",
    "transcript": [
        {"role": "assistant", "text": "Tell me about a conflict.", "at": 1.0},
        {"role": "user", "text": "I disagreed with my lead about a metric.", "at": 5.0},
    ],
    "qa_items": [
        {
            "index": 0,
            "question": "Tell me about a conflict.",
            "competency": "conflict",
            "transcript": "I disagreed with my lead about a metric.",
            "metrics": {"wpm": 140},
        },
    ],
    "speech": {"avg_wpm": 140.0, "fillers_per_min": 2.0, "talk_ratio": 0.6, "answers": []},
    "latency": {"p50_ms": 900, "p95_ms": 1400, "turns": 4},
}


def make_client(tmp_path, grader: FakeGrader) -> TestClient:
    settings = Settings(
        _env_file=None,
        agent_shared_secret=SECRET,
        livekit_api_key="devkey",
        livekit_api_secret="a-long-enough-livekit-dev-secret-0123456789",
    )
    app = create_app(settings, store=Store(tmp_path / "coach.db"), grader_factory=lambda: grader)
    return TestClient(app)


@pytest.fixture
def grader():
    return FakeGrader()


@pytest.fixture
def client(tmp_path, grader):
    return make_client(tmp_path, grader)


def new_session(client) -> str:
    r = client.post("/api/sessions", json=SETUP)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def post_complete(client, sid, payload=PAYLOAD):
    return client.post(f"/api/sessions/{sid}/complete", json=payload, headers={"X-Agent-Secret": SECRET})


def jwt_claims(token: str) -> dict:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def test_create_session_returns_dispatch_token(client):
    body = client.post("/api/sessions", json=SETUP).json()
    assert body["session_id"].startswith("s_") and body["livekit_url"]
    claims = jwt_claims(body["token"])
    agent = claims["roomConfig"]["agents"][0]
    assert agent["agentName"] == "interview-coach"
    meta = json.loads(agent["metadata"])
    assert meta["role"] == SETUP["role"] and meta["session_id"] == body["session_id"]
    assert claims["video"]["room"] == f"coach-{body['session_id']}"


def test_create_session_rejects_long_role(client):
    assert client.post("/api/sessions", json={**SETUP, "role": "x" * 81}).status_code == 422


def test_create_session_rejects_bad_level(client):
    assert client.post("/api/sessions", json={**SETUP, "level": "wizard"}).status_code == 422


def test_report_in_progress_before_completion(client):
    sid = new_session(client)
    assert client.get(f"/api/sessions/{sid}/report").json()["status"] == "in_progress"


def test_complete_requires_secret(client):
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/complete", json=PAYLOAD, headers={"X-Agent-Secret": "wrong"})
    assert r.status_code == 401


def test_complete_unknown_session_404(client):
    assert post_complete(client, "s_doesnotexist").status_code == 404


def test_complete_then_report_ready(client, grader):
    sid = new_session(client)
    assert post_complete(client, sid).status_code == 202
    r = client.get(f"/api/sessions/{sid}/report").json()
    assert r["status"] == "ready" and r["scorecard"]["overall"] >= 0
    assert grader.graded_indexes == [0]
    assert r["latency"]["p50_ms"] == 900 and r["session"]["setup"]["role"] == "Data Analyst"


def test_failed_scorecard_keeps_speech(tmp_path):
    client = make_client(tmp_path, FakeGrader(fail=True))
    sid = new_session(client)
    post_complete(client, sid)
    r = client.get(f"/api/sessions/{sid}/report").json()
    assert r["status"] == "failed" and "grader exploded" in r["error"]
    assert r["speech"] == PAYLOAD["speech"] and r["transcript"]


def test_retry_only_from_failed(client):
    sid = new_session(client)
    post_complete(client, sid)
    assert client.post(f"/api/sessions/{sid}/report/retry").status_code == 409


def test_retry_after_failure_succeeds(client, grader):
    sid = new_session(client)
    grader.fail = True
    post_complete(client, sid)
    grader.fail = False
    assert client.post(f"/api/sessions/{sid}/report/retry").status_code == 202
    assert client.get(f"/api/sessions/{sid}/report").json()["status"] == "ready"


def test_unknown_session_404(client):
    assert client.get("/api/sessions/s_nope/report").status_code == 404


def test_list_sessions_newest_first(client):
    first, second = new_session(client), new_session(client)
    ids = [s["session_id"] for s in client.get("/api/sessions").json()]
    assert ids[:2] == [second, first]


def test_health_reports_key_presence_only(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True and set(body["keys"]) == {"anthropic", "livekit"}
    assert all(isinstance(v, bool) for v in body["keys"].values())
