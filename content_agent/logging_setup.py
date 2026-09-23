from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import logs_dir
from .security import redact_secrets


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.msg)
        if record.args:
            record.args = tuple(redact_secrets(item) for item in record.args)
        if record.exc_info:
            # The formatter receives the original exception object. Avoid dumping it.
            record.exc_text = "Exception details redacted; see the safe message above."
            record.exc_info = None
        return True


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("content_agent")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        logs_dir() / "content_agent.log",
        maxBytes=512 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
