"""Structured logging with redaction for PII and sensitive data."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

# Sensitive patterns
SECRET_PATTERNS = [
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"api[_-]?key['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"password['\"]?\s*[:=]\s*['\"]?([^'\"\s,]+)", re.IGNORECASE),
    re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),  # Credit card
]

SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "access_token",
    "refresh_token",
    "authorization",
    "card_number",
    "cvv",
}


def redact_data(data: Any) -> Any:
    """Recursively redact sensitive keys and values from dicts, lists, and strings."""
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            if any(s_key in k.lower() for s_key in SENSITIVE_KEYS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_data(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_data(item) for item in data]
    elif isinstance(data, str):
        masked = data
        for pattern in SECRET_PATTERNS:
            masked = pattern.sub("[REDACTED]", masked)
        return masked
    return data


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON with automatic redaction."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include extra attributes
        if hasattr(record, "trace_id"):
            log_obj["trace_id"] = record.trace_id
        if hasattr(record, "run_id"):
            log_obj["run_id"] = record.run_id
        if hasattr(record, "details"):
            log_obj["details"] = redact_data(record.details)

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(redact_data(log_obj))


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger with the structured JSON formatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())
    # Replace existing handlers
    root_logger.handlers = [handler]
