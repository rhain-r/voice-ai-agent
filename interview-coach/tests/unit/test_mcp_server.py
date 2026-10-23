import json

from mcp import Client

from interview_coach.mcp_server import server
from interview_coach.mcp_server.bank import question_plan


async def test_mcp_tool_returns_plan():
    args = {"role": "Data Analyst", "level": "junior", "style": "mixed", "count": 3, "seed": "s1"}
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_question_plan", args)
    assert not result.is_error
    body = json.loads(result.content[0].text)
    assert body["family"] == "data"
    expected = question_plan("Data Analyst", "junior", "mixed", 3, seed="s1")
    assert [item["id"] for item in body["items"]] == [q.id for q in expected]


async def test_mcp_lists_tools():
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools.tools} == {"list_role_families", "get_question_plan", "get_rubric"}
