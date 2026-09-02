# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Chromium browser binary for the tracking scraper (app/modules/tracking).
# This layer is cached alongside the pip install above, so the ~170 MB download
# only happens when requirements.txt changes (i.e. when the pinned playwright
# version is bumped) — never on a plain code change. The pinned playwright
# version is what keeps this browser build compatible, so don't let it float.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN playwright install chromium

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Runtime OS packages. xvfb + xauth let the scraper run a *headed* Chromium
# (parcelsapp blocks headless) inside a virtual display.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 1001 appgroup \
    && adduser --system --uid 1001 --gid 1001 appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Chromium: the binary is copied from the builder layer (no re-download); only
# its shared-library apt deps are resolved here (fast, layer-cached). `install`
# never touches user-data / profile directories, so this is safe to re-run.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
COPY --from=builder /opt/pw-browsers /opt/pw-browsers
RUN playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/pw-browsers

# Copy application code
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Run with production settings
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
