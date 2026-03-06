import logging
import sys
from typing import Optional

_logger: Optional[logging.Logger] = None


def init_logger(level: str = "info") -> None:
    global _logger
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    log_level = level_map.get(level.lower(), logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(log_level)
    fmt = logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","module":"%(name)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(fmt)

    root = logging.getLogger("agentflow")
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False

    _logger = root


def get_logger(name: str = "agentflow") -> logging.Logger:
    global _logger
    if _logger is None:
        init_logger()
    return logging.getLogger(name)
