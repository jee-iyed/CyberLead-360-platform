"""Structured logging with a redaction filter.

Logs are either human-readable ``key=value`` text (development) or one JSON
object per line (production, log aggregation). A filter masks e-mail addresses
and API-key-like tokens so personal data and secrets do not leak into logs.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,})\b")
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
_configured = False


def redact(text: str) -> str:
    text = _EMAIL_RE.sub("[email-redacted]", text)
    return _KEY_RE.sub("[secret-redacted]", text)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) for a in record.args)  # type: ignore[assignment]
        return True


def _extras(record: logging.LogRecord) -> dict[str, object]:
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: redact(str(v)) for k, v in _extras(record).items()})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = " ".join(f"{k}={redact(str(v))}" for k, v in _extras(record).items())
        return f"{base} {extras}".rstrip()


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the root ``cyberlead360`` logger once per process."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.addFilter(RedactionFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(KeyValueFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("cyberlead360")
    logger.setLevel(level.upper())
    logger.addHandler(handler)
    logger.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cyberlead360.{name}")
