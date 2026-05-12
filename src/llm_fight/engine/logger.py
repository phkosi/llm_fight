"""Logger configuration used across the engine modules."""

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from .. import config
from . import constants as C

logger = logging.getLogger("llm_fight_engine")
logger.propagate = True

_FORMATTER = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _configured_level() -> int:
    level_name = config.CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_LEVEL, str, fallback="INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _ensure_null_handler() -> None:
    if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        logger.addHandler(logging.NullHandler())


def update_logger_level() -> None:
    """Update :data:`logger` and its handlers from :data:`config.CONFIG`."""

    level = _configured_level()
    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)


@contextmanager
def cli_logging(*, update_level: bool = True) -> Iterator[None]:
    """Temporarily route package logs to stderr for a CLI invocation."""

    previous_handlers = logger.handlers[:]
    previous_level = logger.level
    previous_propagate = logger.propagate

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    cli_handler = logging.StreamHandler(sys.stderr)
    cli_handler.setFormatter(_FORMATTER)
    logger.addHandler(cli_handler)
    logger.propagate = False
    if update_level:
        update_logger_level()

    try:
        yield
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            if handler is cli_handler:
                handler.close()
        for handler in previous_handlers:
            logger.addHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


_ensure_null_handler()
update_logger_level()
