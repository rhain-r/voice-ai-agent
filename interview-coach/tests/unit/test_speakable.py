import pytest

from interview_coach.agent.speakable import normalize, normalize_stream


@pytest.mark.parametrize(
    "text,expected",
    [
        ("**Great** answer", "Great answer"),
        ("# Next", "Next"),
        ("- first point", "first point"),
        ("`code`", "code"),
        ("40% faster", "40 percent faster"),
        ("R&D", "R and D"),
        ("e.g. a cache", "for example a cache"),
        ("see https://x.io/a", "see the link on screen"),
        ("plain", "plain"),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


async def test_normalize_stream_joins_split_tokens():
    async def chunks():
        for c in ["**Gre", "at** ans", "wer"]:
            yield c

    out = [piece async for piece in normalize_stream(chunks())]
    assert "".join(out) == "Great answer"
