"""Logging estructurado en JSON, con trace_id y sin datos sensibles."""
import json
import logging
import re
from datetime import datetime, timezone

_SENSITIVE = re.compile(r"(password|passwd|contrase|token|secret|sessionid|csrftoken)[^\s,;]*\s*[=:]\s*\S+", re.I)


def redact(text: str) -> str:
    return _SENSITIVE.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=[REDACTADO]", text)


class TraceIdFilter(logging.Filter):
    def filter(self, record):
        from .middleware import current_trace_id

        record.trace_id = current_trace_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "message": redact(record.getMessage()),
        }
        for key in ("event", "actor", "outcome", "error_code", "path"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))[-2000:]
        return json.dumps(payload, ensure_ascii=False)
