"""Structured logging configuration with request-id correlation and timing."""

import contextvars
import logging
import sys

request_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Inject contextual request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx_var.get()
        return True


def setup_logging() -> None:
    """Initialize formatted logging with request_id tracking."""
    log_filter = RequestIdFilter()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(log_filter)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [req:%(request_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    app_logger = logging.getLogger("geospatial_api")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        app_logger.addHandler(handler)
    app_logger.propagate = False


logger = logging.getLogger("geospatial_api")
logger.addFilter(RequestIdFilter())
