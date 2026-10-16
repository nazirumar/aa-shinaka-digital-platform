"""Observability helpers (Phase 12).

A tiny, dependency-free JSON log formatter so production logs are
machine-readable for the log platform without adding a third-party package.

Only the standard :class:`logging.LogRecord` fields and any values explicitly
passed through ``extra={...}`` are emitted. The application never attaches
secrets, full request bodies or customer PII to log records; this formatter
does not add any of its own.
"""

from __future__ import annotations

import json
import logging

# LogRecord attributes that are already represented (or deliberately omitted).
_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "pid": record.process,
            "thread": record.threadName,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)
