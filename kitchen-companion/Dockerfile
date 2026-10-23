# syntax=docker/dockerfile:1

# 1. Build the tablet app.
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# 2. The bot server, which also serves the built app on the same port.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
RUN uv sync --frozen --no-dev

COPY --from=web /web/dist ./web/dist

ENV PATH="/app/.venv/bin:$PATH" \
    WEB_DIST=/app/web/dist \
    HOST=0.0.0.0 \
    PORT=7860
EXPOSE 7860
CMD ["kitchen-server"]
