import pytest

from interview_coach.mcp_server.bank import LEVELS, question_plan, role_family, rubric


@pytest.mark.parametrize(
    "role,fam",
    [
        ("Senior Software Engineer", "software"),
        ("ML Engineer", "ai_ml"),
        ("Data Analyst", "data"),
        ("Product Manager", "product"),
        ("UX Designer", "design"),
        ("Chef", "general"),
        ("Build Engineer", "software"),  # "ui" inside "build" must not mean design
    ],
)
def test_role_family(role, fam):
    assert role_family(role) == fam


def test_role_family_case_insensitive():
    assert role_family("mACHINE lEARNING researcher") == "ai_ml"


def test_plan_count_unique_deterministic():
    p1 = question_plan("Data Analyst", "junior", "mixed", 5, seed="s1")
    assert len(p1) == 5 and len({q.id for q in p1}) == 5
    p2 = question_plan("Data Analyst", "junior", "mixed", 5, seed="s1")
    assert [q.id for q in p1] == [q.id for q in p2]
    assert [q.style for q in p1] == ["behavioral", "technical", "behavioral", "technical", "behavioral"]


def test_plan_prefers_level():
    plan = question_plan("Software Engineer", "senior", "behavioral", 3, "x")
    assert all("senior" in q.levels for q in plan)


def test_count_clamped():
    assert len(question_plan("x", "mid", "behavioral", 50, "s")) == 10
    assert len(question_plan("x", "mid", "behavioral", 0, "s")) == 1


def test_technical_plan_uses_family_items():
    plan = question_plan("ML Engineer", "mid", "technical", 3, "s")
    assert all(q.style == "technical" for q in plan)
    assert all(q.id.startswith("ai_ml-") for q in plan)


def test_every_item_tags_two_valid_levels():
    for style in ("behavioral", "technical"):
        for q in question_plan("Software Engineer", "mid", style, 10, "s"):
            assert len(q.levels) >= 2 and set(q.levels) <= set(LEVELS)


def test_rubric_shape():
    r = rubric("behavioral")
    assert set(r) == {"structure", "specificity", "impact", "relevance", "communication"}
    assert all(set(anchors) == {"1", "3", "5"} for anchors in r.values())
