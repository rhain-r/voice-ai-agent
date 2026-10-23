"""Deliver the finished session to the API; never lose it (spec §7: retry, then spill to disk)."""

import asyncio
import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


async def post_completion(
    api_url: str,
    secret: str,
    session_id: str,
    payload: dict,
    *,
    attempts: int = 3,
    backoff: float = 0.5,
    spill_dir: Path = Path("data/failed_completions"),
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    url = f"{api_url.rstrip('/')}/api/sessions/{session_id}/complete"
    async with httpx.AsyncClient(transport=transport, timeout=10.0) as client:
        for attempt in range(attempts):
            try:
                response = await client.post(url, json=payload, headers={"X-Agent-Secret": secret})
                if response.is_success:
                    return True
                log.warning("completion POST %s -> %s", url, response.status_code)
                if response.status_code < 500:
                    break  # a client error will not fix itself on retry
            except httpx.HTTPError as exc:
                log.warning("completion POST failed: %s", exc)
            if attempt + 1 < attempts:
                await asyncio.sleep(backoff * 2**attempt)

    spill_dir.mkdir(parents=True, exist_ok=True)
    (spill_dir / f"{session_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    log.error("completion for %s spilled to %s", session_id, spill_dir)
    return False
