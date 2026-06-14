"""
Logging configuration for the ambulance routing system.

Call configure_logging() once at application startup.
"""

import logging
import logging.config
from typing import Any, Dict

from core.config import APP_ENV, LOG_LEVEL


def _build_config(level: str, env: str) -> Dict[str, Any]:
    production = env == "production"
    formatter = "json" if production else "standard"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%SZ",
            },
            "json": {
                "()": "core.logging_config.JsonFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": formatter,
                "level": level,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": level,
        },
        "loggers": {
            "ambulance_routing": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter (no external dependencies)."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra_keys = {
            k: v
            for k, v in record.__dict__.items()
            if k not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__
            and not k.startswith("_")
        }
        if extra_keys:
            payload["extra"] = extra_keys
        return json.dumps(payload)


def configure_logging(level: str = LOG_LEVEL, env: str = APP_ENV) -> None:
    logging.config.dictConfig(_build_config(level, env))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ambulance_routing.{name}")
