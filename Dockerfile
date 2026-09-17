FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first, copy source after - a code change skips the reinstall
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev

COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH"
