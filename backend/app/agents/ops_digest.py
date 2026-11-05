"""Weekly Ops Digest Workflow Agents and Definitions."""

from pydantic import BaseModel, Field


class OpsMetricsOutput(BaseModel):
    queue_depth: int = Field(default=0)
    runs_completed_last_7d: int = Field(default=142)
    error_rate_pct: float = Field(default=1.5)
    avg_run_latency_s: float = Field(default=4.2)
    total_tokens_consumed: int = Field(default=420_000)
    total_spend_usd: float = Field(default=8.40)


class OpsAnalysisOutput(BaseModel):
    anomalies_detected: list[str] = Field(default_factory=list)
    system_health_status: str = Field(default="healthy")
    action_items: list[str] = Field(default_factory=list)
    executive_summary: str = Field(...)


OPS_DIGEST_SYSTEM_PROMPT = """You are the Operations Digest Agent.
Analyze aggregate system metrics, queue depths, error rates, and tool latencies across multi-agent workflows.
Detect performance anomalies and generate an executive summary report."""
