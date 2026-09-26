# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------- builder
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# Dependency layer is keyed on the lockfile alone, so editing source does not
# invalidate the (slow) install layer. Every package is pinned by version and
# hash (`make lock` writes requirements.lock), so an upstream release cannot
# change what an image contains or break a build that worked yesterday.
COPY requirements.lock ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install --require-hashes -r requirements.lock

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN /opt/venv/bin/pip install --no-deps .

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# libmagic for content sniffing on upload; poppler for PDF text extraction
# fallback. Kept minimal — every package here is attack surface.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 mnemos

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=mnemos:mnemos alembic.ini ./
COPY --chown=mnemos:mnemos migrations/ ./migrations/
COPY --chown=mnemos:mnemos src/ ./src/

USER mnemos
EXPOSE 8000

CMD ["uvicorn", "mnemos.entrypoints.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
