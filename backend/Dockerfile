FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir hatchling
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels .

FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

COPY --from=builder /build/wheels /wheels
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .

COPY backend /app/backend
COPY alembic.ini /app/alembic.ini

USER appuser

EXPOSE 8000
ENV PYTHONPATH=/app
ENV PORT=8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
