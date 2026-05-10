# --- Builder Stage ---
FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /project

# Cache dependency layer — copy lock + manifest first, install without project,
# then copy source and install the project itself for layer reuse on code-only changes.
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --no-editable --no-install-project

COPY src/ src/
COPY config/ config/
RUN uv sync --no-dev --no-editable

# --- Runtime Stage ---
FROM python:3.13-slim

WORKDIR /project

COPY --from=builder /project/.venv /project/.venv
COPY --from=builder /project/src /project/src
COPY --from=builder /project/config /project/config
# scripts/keygen.py runs as the gatekeeper-keygen one-shot init service.
COPY scripts/ /project/scripts/

ENV PATH="/project/.venv/bin:$PATH"
ENV PYTHONPATH=/project/src
ENV ENV=production

RUN adduser --disabled-password --no-create-home --uid 10001 appuser \
    && chown -R appuser:appuser /project
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5000/api/v1/live',timeout=3).status==200 else 1)"

CMD ["gatekeeper", "server", "run"]
