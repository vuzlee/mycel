# The UI, built here so the runtime image carries no Node.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS app
# Dependencies before source, so a code change skips the reinstall.
RUN uv sync --locked --no-default-groups --no-install-project
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
COPY alembic.ini ./
RUN uv sync --locked --no-default-groups
COPY --from=web /web/dist/ web/dist/

# The app plus docling (torch) with its models baked in.
FROM base AS ingest
# OpenCV, pulled in by docling's table model, needs these.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libxcb1 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
RUN uv sync --locked --no-default-groups --group ingest --no-install-project
COPY src/ src/
COPY config/ config/
RUN uv sync --locked --no-default-groups --group ingest
RUN docling-tools models download layout tableformer
CMD ["python", "-m", "mycel.worker", "--queue", "ingest"]
