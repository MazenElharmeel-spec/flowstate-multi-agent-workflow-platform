"""Prometheus metrics for workflow, approval, tool, and budget activity."""

from prometheus_client import Counter, Gauge, Histogram

RUNS_TOTAL = Counter("workflow_runs_total", "Workflow runs by lifecycle state", ["status"])
RUN_DURATION_SECONDS = Histogram(
    "workflow_run_duration_seconds", "End-to-end workflow duration in seconds", ["workflow_key"]
)
APPROVALS_TOTAL = Counter(
    "workflow_approval_events_total", "Approval requests and decisions", ["event"]
)
TOOL_CALLS_TOTAL = Counter(
    "workflow_tool_calls_total", "Tool calls by tool and result", ["tool_name", "status"]
)
RETRIES_TOTAL = Counter("workflow_retries_total", "Workflow retry attempts")
TOKEN_USAGE_TOTAL = Counter(
    "workflow_tokens_total", "Total model tokens consumed", ["workflow_key"]
)
ESTIMATED_COST_TOTAL = Counter(
    "workflow_estimated_cost_usd_total", "Estimated model spend in USD", ["workflow_key"]
)
QUEUE_DEPTH = Gauge("workflow_queue_depth", "Number of queued workflow runs")
APPROVAL_WAIT_SECONDS = Histogram(
    "workflow_approval_wait_seconds", "Time spent waiting for human approval"
)
