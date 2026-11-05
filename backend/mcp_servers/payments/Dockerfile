FROM python:3.12-slim

WORKDIR /app
RUN useradd -m -u 1000 appuser && mkdir -p /data && chown -R appuser:appuser /app /data


RUN pip install --no-cache-dir fastapi uvicorn pydantic

COPY --chown=appuser:appuser backend/mcp_servers /app/backend/mcp_servers

EXPOSE 8004
ENV PORT=8004
ENV PYTHONPATH=/app

USER appuser

CMD ["python", "-m", "backend.mcp_servers.payments.server"]
