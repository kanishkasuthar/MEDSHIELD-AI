# ==============================================================================
# MEDSHIELD AI — Production Cloud Dockerfile
# ==============================================================================

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specifications
COPY requirements.txt pyproject.toml README.md ./

# Install wheels into local directory
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Final runtime image
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install runtime libpq for PostgreSQL support and curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create unprivileged user for security
RUN useradd -m -u 1000 medshield && \
    mkdir -p /app/data && \
    chown -R medshield:medshield /app

# Copy application code
COPY src/ /app/src/
COPY scripts/ /app/scripts/

ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV APP_ENV="production"
ENV API_HOST="0.0.0.0"
ENV API_PORT=8000

USER medshield

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["python", "scripts/run_server.py"]
