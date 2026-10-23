"""Fetch the interview's question plan from the MCP server, falling back to the bundled bank."""

import asyncio
import json
import logging
from typing import Any, Literal

from mcp import Client

from interview_coach.mcp_server import bank
from interview_coach.mcp_server.bank import QuestionItem

log = logging.getLogger(__name__)


async def _from_mcp(target: Any, args: dict) -> list[QuestionItem]:
    async with Client(target) as client:
        result = await client.call_tool("get_question_plan", args)
    if result.is_error:
        raise RuntimeError(f"get_question_plan failed: {result.content}")
    body = json.loads(result.content[0].text)
    return [QuestionItem(**item) for item in body["items"]]


async def fetch_plan(
    target: str | Any,
    *,
    role: str,
    level: str,
    style: str,
    count: int,
    seed: str,
    timeout: float = 3.0,
) -> tuple[list[QuestionItem], Literal["mcp", "bundled"]]:
    """`target` is the MCP URL in production, or an MCPServer instance in tests."""
    args = {"role": role, "level": level, "style": style, "count": count, "seed": seed}
    try:
        items = await asyncio.wait_for(_from_mcp(target, args), timeout)
        return items, "mcp"
    except Exception as exc:  # any MCP failure must not stop the interview
        log.warning("MCP question bank unavailable (%s: %s); using bundled bank", type(exc).__name__, exc)
        return bank.question_plan(role, level, style, count, seed), "bundled"
