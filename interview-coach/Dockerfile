# One image for the three Python services: coach-agent, coach-api, coach-mcp.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/

# onnxruntime (turn detector, Silero VAD) needs OpenMP at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# Bake the turn-detector and VAD weights into the image so the agent starts offline.
RUN python -m interview_coach.agent.worker download-files

CMD ["coach-api"]
