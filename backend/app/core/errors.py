"""Error taxonomy and exception hierarchy."""

from typing import Any


class WorkflowEngineError(Exception):
    """Base error for all workflow platform exceptions."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TransientError(WorkflowEngineError):
    """Transient errors that can be safely retried with exponential backoff (e.g. network blips, 5xx)."""

    def __init__(
        self,
        message: str,
        retry_after_s: float | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, details)
        self.retry_after_s = retry_after_s


class PermanentError(WorkflowEngineError):
    """Permanent errors that should not be automatically retried (e.g. 4xx, validation, permission)."""

    pass


class ModelError(WorkflowEngineError):
    """Errors arising from LLM interactions (e.g. schema violation, context overflow, refusal)."""

    def __init__(
        self,
        message: str,
        raw_output: str | None = None,
        can_repair: bool = True,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, details)
        self.raw_output = raw_output
        self.can_repair = can_repair


class BudgetExceededError(PermanentError):
    """Raised when a run exceeds allocated steps, tokens, tool calls, or time budget."""

    def __init__(self, budget_type: str, limit: int | float, actual: int | float):
        super().__init__(
            f"Budget exceeded for {budget_type}: limit={limit}, actual={actual}",
            details={"budget_type": budget_type, "limit": limit, "actual": actual},
        )


class PolicyDenialError(PermanentError):
    """Raised when an action violates safety or business policy."""

    def __init__(self, rule_name: str, reason: str, details: dict[str, Any] | None = None):
        merged = {"rule_name": rule_name, "reason": reason}
        if details:
            merged.update(details)
        super().__init__(f"Policy denial [{rule_name}]: {reason}", details=merged)


class ApprovalExpiredError(PermanentError):
    """Raised when an approval request has expired without decision."""

    def __init__(self, approval_id: str):
        super().__init__(
            f"Approval request {approval_id} has expired", details={"approval_id": approval_id}
        )
