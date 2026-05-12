import importlib
import logging

import llm_fight.engine.logger as logger_module
from llm_fight.config import Config
from llm_fight.engine import constants as C


def _remove_direct_handlers() -> None:
    for handler in logger_module.logger.handlers[:]:
        logger_module.logger.removeHandler(handler)


def test_logger_level_respected(monkeypatch, tmp_path):
    ini = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_LOG_LEVEL}=WARNING\n"
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    custom_cfg = Config(cfg_path)

    import llm_fight.config as config_module

    monkeypatch.setattr(config_module, "CONFIG", custom_cfg)
    _remove_direct_handlers()
    module = importlib.reload(logger_module)

    assert module.logger.level == logging.WARNING
    assert len(module.logger.handlers) == 1
    assert isinstance(module.logger.handlers[0], logging.NullHandler)
    assert module.logger.handlers[0].level == logging.WARNING
    assert module.logger.propagate is True


def test_update_logger_level(monkeypatch, tmp_path):
    ini = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_LOG_LEVEL}=INFO\n"
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    cfg = Config(cfg_path)

    import llm_fight.config as config_module

    monkeypatch.setattr(config_module, "CONFIG", cfg)
    _remove_direct_handlers()
    module = importlib.reload(logger_module)

    ini2 = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_LOG_LEVEL}=ERROR\n"
    cfg_path2 = tmp_path / "cfg2.ini"
    cfg_path2.write_text(ini2)
    new_cfg = Config(cfg_path2)

    monkeypatch.setattr(config_module, "CONFIG", new_cfg)
    module.update_logger_level()

    assert module.logger.level == logging.ERROR
    assert module.logger.handlers[0].level == logging.ERROR


def test_logger_uses_direct_null_handler_even_when_root_has_handlers():
    stream_handler = logging.StreamHandler()
    root_logger = logging.getLogger()
    root_logger.addHandler(stream_handler)
    try:
        _remove_direct_handlers()
        module = importlib.reload(logger_module)

        assert len(module.logger.handlers) == 1
        assert isinstance(module.logger.handlers[0], logging.NullHandler)
        assert module.logger.propagate is True
    finally:
        root_logger.removeHandler(stream_handler)


def test_import_default_logger_does_not_write_to_stdout_or_stderr(capsys):
    _remove_direct_handlers()
    module = importlib.reload(logger_module)

    module.logger.warning("library import path is silent by default")
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""


def test_cli_logging_routes_to_stderr_and_restores(capsys):
    _remove_direct_handlers()
    module = importlib.reload(logger_module)
    previous_handlers = module.logger.handlers[:]
    previous_level = module.logger.level
    previous_propagate = module.logger.propagate

    with module.cli_logging():
        assert module.logger.propagate is False
        assert len(module.logger.handlers) == 1
        assert isinstance(module.logger.handlers[0], logging.StreamHandler)
        assert module.logger.handlers[0].stream is not None
        module.logger.warning("cli-visible warning")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cli-visible warning" in captured.err
    assert module.logger.handlers == previous_handlers
    assert module.logger.level == previous_level
    assert module.logger.propagate == previous_propagate
