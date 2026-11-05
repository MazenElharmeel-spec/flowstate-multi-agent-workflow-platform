FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn pydantic

COPY backend/mcp_servers /app/backend/mcp_servers

EXPOSE 8002
ENV PORT=8002
ENV PYTHONPATH=/app

CMD ["python", "-m", "backend.mcp_servers.ticketing.server"]
