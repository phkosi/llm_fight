import importlib
import logging
from src.config import Config
from src.engine import constants as C
import src.engine.logger as logger_module


def test_logger_level_respected(monkeypatch, tmp_path):
    ini = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_LOG_LEVEL}=WARNING\n"
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    custom_cfg = Config(cfg_path)

    root_logger = logging.getLogger()
    saved_root_handlers = root_logger.handlers[:]
    root_logger.handlers = []
    for h in logger_module.logger.handlers[:]:
        logger_module.logger.removeHandler(h)

    import src.config as config_module

    monkeypatch.setattr(config_module, "CONFIG", custom_cfg)
    importlib.reload(logger_module)

    assert logger_module.logger.level == logging.WARNING
    assert logger_module.logger.handlers[0].level == logging.WARNING

    root_logger.handlers = saved_root_handlers
    importlib.reload(logger_module)


def test_update_logger_level(monkeypatch, tmp_path):
    ini = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_LOG_LEVEL}=INFO\n"
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    cfg = Config(cfg_path)

    root_logger = logging.getLogger()
    saved_root_handlers = root_logger.handlers[:]
    root_logger.handlers = []
    for h in logger_module.logger.handlers[:]:
        logger_module.logger.removeHandler(h)

    import src.config as config_module

    monkeypatch.setattr(config_module, "CONFIG", cfg)
    importlib.reload(logger_module)

    ini2 = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_LOG_LEVEL}=ERROR\n"
    cfg_path2 = tmp_path / "cfg2.ini"
    cfg_path2.write_text(ini2)
    new_cfg = Config(cfg_path2)

    monkeypatch.setattr(config_module, "CONFIG", new_cfg)
    logger_module.update_logger_level()

    assert logger_module.logger.level == logging.ERROR
    assert logger_module.logger.handlers[0].level == logging.ERROR

    root_logger.handlers = saved_root_handlers
    importlib.reload(logger_module)
