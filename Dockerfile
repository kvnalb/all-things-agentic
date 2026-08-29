FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/backend"
CMD ["sh", "-c", "uvicorn studyagent.main:app --host 0.0.0.0 --port ${PORT}"]
