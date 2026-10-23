from interview_coach.agent.question_source import fetch_plan
from interview_coach.mcp_server import server
from interview_coach.mcp_server.bank import question_plan

ARGS = {"role": "Data Analyst", "level": "junior", "style": "mixed", "count": 3, "seed": "s1"}


async def test_fetch_from_mcp():
    items, source = await fetch_plan(server.mcp, **ARGS)
    assert source == "mcp" and len(items) == 3
    assert [q.id for q in items] == [q.id for q in question_plan(**ARGS)]


async def test_falls_back_when_unreachable():
    items, source = await fetch_plan("http://127.0.0.1:9/mcp", timeout=0.5, **ARGS)
    assert source == "bundled" and len(items) == 3
