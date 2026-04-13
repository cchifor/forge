# ==========================================
# Global ARGs (must be before first FROM)
# ==========================================
ARG PYTHON_BUILD_BASE=python
ARG PYTHON_BUILD_VER=3.13-slim
ARG PYTHON_RUN_BASE=python
ARG PYTHON_RUN_VER=3.13-slim

# ==========================================
# Build Stage
# ==========================================
FROM ${PYTHON_BUILD_BASE}:${PYTHON_BUILD_VER} AS builder

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1
# Fix PDM version detection for non-git environments
ENV PDM_BUILD_SCM_VERSION=1.0.0
# Disable PDM update check for speed
ENV PDM_CHECK_UPDATE=false

# Install necessary system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
    gcc \
    libffi-dev \
    libssl-dev \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install PDM
RUN pip install -U pdm

WORKDIR /project

# OPTIMIZATION: Copy dependency definitions FIRST
COPY pyproject.toml pdm.lock README.md /project/

# OPTIMIZATION: Install dependencies ONLY (no source code yet)
RUN pdm install --check --prod --no-editable --no-self

# Copy the actual source code and config
COPY src/ /project/src
COPY config/ /project/config

# Install the project itself (src) into the venv
RUN pdm install --check --prod --no-editable

# ==========================================
# Run Stage
# ==========================================
FROM ${PYTHON_RUN_BASE}:${PYTHON_RUN_VER}

# Retrieve virtual environment and application code from builder
COPY --from=builder /project/.venv/ /project/.venv
COPY --from=builder /project/src/ /project/src
COPY --from=builder /project/config/ /project/config

# Secrets should be mounted at runtime, NOT baked into the image.
# Use: docker run -v /path/to/.secrets.yaml:/project/config/.secrets.yaml ...
# Or set via environment variables with APP__ prefix.

# Add venv to path so we use the installed PDM packages by default
ENV PATH="/project/.venv/bin:$PATH"
ENV PYTHONPATH="/project/src:$PYTHONPATH"
ENV ENV="production"

WORKDIR /project

EXPOSE 5000

CMD ["python", "src/__main__.py", "server", "run"]
