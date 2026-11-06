"""Application configuration and settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    PROJECT_NAME: str = "Multi-Agent AI Workflow Platform"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Security & Auth
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production-min-32-chars-long",
        description="Secret key for JWT generation and verification",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/dev.db"
    DATABASE_URL_SYNC: str = "sqlite:///./data/dev.db"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    # Redis / Queue
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_REQUIRED: bool = False
    WORKER_METRICS_PORT: int = 8005
    WORKER_LEASE_SECONDS: int = 120
    WORKER_HEARTBEAT_SECONDS: int = 30
    WORKER_MAX_CONCURRENCY: int = 5

    # LLM Settings
    DEFAULT_LLM_PROVIDER: Literal["fake", "anthropic", "openai"] = "fake"
    DEFAULT_MODEL_NAME: str = "claude-3-5-sonnet-20241022"
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    # MCP Servers
    CRM_MCP_URL: str = "http://localhost:8001/mcp"
    TICKETING_MCP_URL: str = "http://localhost:8002/mcp"
    EMAIL_MCP_URL: str = "http://localhost:8003/mcp"
    PAYMENTS_MCP_URL: str = "http://localhost:8004/mcp"

    # Engine Budgets & Limits
    DEFAULT_MAX_STEPS: int = 20
    DEFAULT_MAX_TOOL_CALLS: int = 15
    DEFAULT_MAX_TOKENS: int = 50_000
    DEFAULT_TIMEOUT_SECONDS: int = 300
    MAX_PLANNER_REVIEWER_LOOPS: int = 3

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_SERVICE_NAME: str = "agent-workflow-platform"
    PROMETHEUS_METRICS_ENABLED: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
