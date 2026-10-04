# The UI, built here so the runtime image carries no Node.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim AS app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first, copy source after - a code change skips the reinstall
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev

COPY src/ src/
COPY config/ config/
# Both halves of alembic, or neither works: migrations/ holds the versions, alembic.ini
# holds script_location that points at it. Without the ini, `alembic upgrade head` fails
# with "No 'script_location' key found" - which reads like a broken config file rather
# than a missing one.
COPY migrations/ migrations/
COPY alembic.ini ./
RUN uv sync --no-dev

# Last: only the built assets cross over, and only `app.py::WEB_DIST` looks for them.
COPY --from=web /web/dist/ web/dist/

ENV PATH="/app/.venv/bin:$PATH"

# The ingest worker: the same app plus docling (torch), and its models baked in so a
# restart never downloads gigabytes. Only this target carries the weight.
FROM python:3.11-slim AS ingest
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# OpenCV, pulled in by docling's table model, links against these; slim has none of them.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libxcb1 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --extra ingest --no-install-project
COPY src/ src/
COPY config/ config/
RUN uv sync --frozen --no-dev --extra ingest
ENV PATH="/app/.venv/bin:$PATH"
RUN docling-tools models download layout tableformer
CMD ["python", "-m", "mycel.queue.consumer", "--queue", "ingest"]

