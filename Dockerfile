# ---------------------------------------------------------------------------
# Stage 1: builder — install dependencies into a clean layer
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install only prod dependencies
COPY requirements-prod.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements-prod.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime — minimal image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy application source
COPY api/ ./api/
COPY core/ ./core/
COPY examples/ ./examples/

RUN chown -R appuser:appgroup /app
USER appuser

# Environment defaults (can be overridden via docker-compose or -e flags)
ENV APP_ENV=production \
    LOG_LEVEL=INFO \
    PORT=8000 \
    GRAPH_PATH="" \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/')" || exit 1

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
