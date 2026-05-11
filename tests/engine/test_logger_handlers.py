import importlib
import logging

import llm_fight.engine.logger as logger_module


def test_logger_single_handler(monkeypatch):
    """Importing logger multiple times should not add multiple handlers."""
    # Temporarily remove handlers from the root logger so hasHandlers() only
    # reflects handlers attached to our logger.
    root_logger = logging.getLogger()
    saved_root_handlers = root_logger.handlers[:]
    root_logger.handlers = []

    # Remove any handlers from our logger to start clean
    for handler in logger_module.logger.handlers[:]:
        logger_module.logger.removeHandler(handler)

    importlib.reload(logger_module)
    assert len(logger_module.logger.handlers) == 1
    first_id = id(logger_module.logger.handlers[0])

    importlib.reload(logger_module)
    assert len(logger_module.logger.handlers) == 1
    assert id(logger_module.logger.handlers[0]) == first_id

    # Restore root logger handlers
    root_logger.handlers = saved_root_handlers
