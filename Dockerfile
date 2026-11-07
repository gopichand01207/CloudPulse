# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install all Python dependencies into /install
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install OS-level build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies into an isolated prefix
COPY requirements.txt .
RUN pip install --prefix=/install --no-warn-script-location -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — lean production image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/install/bin:$PATH"

# Install only runtime OS libraries (libpq for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    # Create non-root user
    && groupadd --gid 1001 cloudpulse \
    && useradd --uid 1001 --gid cloudpulse --shell /bin/bash --create-home cloudpulse

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Set working directory and copy application source
WORKDIR /app
COPY --chown=cloudpulse:cloudpulse . .

# Switch to non-root user
USER cloudpulse

# Expose application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application with Uvicorn (4 workers for production)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-config", "app/log_config.json"]
