"""Make LLM text safe to speak: no markdown symbols, no raw URLs, spoken symbols (spec §5.4)."""

import re
from collections.abc import AsyncIterable, AsyncIterator

_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^(\s*)#+\s*")
_BULLET = re.compile(r"^(\s*)[-•]\s+")
_EMPHASIS = re.compile(r"\*+|__|`+")
_PERCENT = re.compile(r"(\d)\s*%")
_AMP = re.compile(r"\s*&\s*")
_EG = re.compile(r"\be\.g\.", re.IGNORECASE)
_IE = re.compile(r"\bi\.e\.", re.IGNORECASE)
_SPACES = re.compile(r"[ \t]{2,}")


def normalize(text: str, *, at_line_start: bool = True) -> str:
    """Normalize one piece of text. Leading/trailing whitespace is preserved so streamed
    pieces can be concatenated; `at_line_start=False` means the text continues a line."""
    text = _URL.sub("the link on screen", text)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if i > 0 or at_line_start:
            line = _HEADING.sub(r"\1", line)
            line = _BULLET.sub(r"\1", line)
        lines[i] = line
    text = "\n".join(lines)
    text = _EMPHASIS.sub("", text)
    text = _PERCENT.sub(r"\1 percent", text)
    text = _AMP.sub(" and ", text)
    text = _EG.sub("for example", text)
    text = _IE.sub("that is", text)
    return _SPACES.sub(" ", text)


async def normalize_stream(chunks: AsyncIterable[str]) -> AsyncIterator[str]:
    """Normalize streamed LLM tokens, cutting only at whitespace so no token is split."""
    buffer = ""
    at_line_start = True
    async for chunk in chunks:
        buffer += chunk
        cut = max(buffer.rfind(" "), buffer.rfind("\n"))
        if cut < 0:
            continue
        ready, buffer = buffer[: cut + 1], buffer[cut + 1 :]
        out = normalize(ready, at_line_start=at_line_start)
        at_line_start = ready.endswith("\n")
        if out:
            yield out
    if buffer:
        yield normalize(buffer, at_line_start=at_line_start)
