import importlib
import logging

import llm_fight.engine.logger as logger_module


def test_logger_single_null_handler():
    """Importing logger multiple times should not add multiple handlers."""
    for handler in logger_module.logger.handlers[:]:
        logger_module.logger.removeHandler(handler)

    importlib.reload(logger_module)
    assert len(logger_module.logger.handlers) == 1
    assert isinstance(logger_module.logger.handlers[0], logging.NullHandler)
    first_id = id(logger_module.logger.handlers[0])

    importlib.reload(logger_module)
    assert len(logger_module.logger.handlers) == 1
    assert isinstance(logger_module.logger.handlers[0], logging.NullHandler)
    assert id(logger_module.logger.handlers[0]) == first_id
