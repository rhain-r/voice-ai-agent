"""MCP server exposing the interview question bank (spec §5.6).

Usable by this app's agent and API, and by any MCP client (Claude Desktop, Claude Code).
"""

from typing import Literal

from mcp.server.mcpserver import MCPServer

from interview_coach.mcp_server import bank

mcp = MCPServer(
    "interview-coach-questions",
    instructions="Interview question bank: plans of questions per role, level and style, plus a grading rubric.",
)


@mcp.tool()
def list_role_families() -> dict:
    """List the role families the question bank covers."""
    return {"families": bank.role_families()}


@mcp.tool()
def get_question_plan(
    role: str,
    level: Literal["intern", "junior", "mid", "senior", "staff"],
    style: Literal["behavioral", "technical", "mixed"],
    count: int,
    seed: str = "",
) -> dict:
    """Pick an ordered, deterministic set of interview questions for a role and level."""
    items = bank.question_plan(role, level, style, count, seed)
    return {"family": bank.role_family(role), "items": [item.model_dump() for item in items]}


@mcp.tool()
def get_rubric(style: Literal["behavioral", "technical", "mixed"]) -> dict:
    """Grading rubric: five dimensions with 1/3/5 anchors."""
    return {"style": style, "dimensions": bank.rubric(style)}


def main() -> None:
    mcp.run("streamable-http", host="0.0.0.0", port=8765)


if __name__ == "__main__":
    main()
