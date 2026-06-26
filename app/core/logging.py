"""Logging setup — one place to configure how the app logs.

Call `configure_logging()` once at startup. Modules get their logger with
`logging.getLogger("hive.<area>")`; they never configure handlers themselves.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"hive.{name}" if not name.startswith("hive") else name)
