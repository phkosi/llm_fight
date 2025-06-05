import json
import importlib
from src.config import Config
from src.engine import constants as C
import src.transcripts as transcripts
import src.config as config_mod


def test_log_exchange_creates_file(tmp_path, monkeypatch):
    ini = (
        f"[{C.CONFIG_GENERAL}]\n" f"{C.CONFIG_SAVE_TRANSCRIPTS}=true\n" f"{C.CONFIG_TRANSCRIPT_DIR}={tmp_path/'logs'}\n"
    )
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    custom_cfg = Config(cfg_path)

    monkeypatch.setattr(config_mod, "CONFIG", custom_cfg)
    monkeypatch.setattr(transcripts, "CONFIG", custom_cfg)
    importlib.reload(transcripts)

    messages = [{"role": "user", "content": "hi"}]
    responses = ["hello"]
    transcripts.log_exchange(messages, responses)

    log_dir = tmp_path / "logs"
    files = list(log_dir.iterdir())
    assert len(files) == 1
    data = files[0].read_text().splitlines()
    assert len(data) == 1
    entry = json.loads(data[0])
    assert entry["prompt"] == messages
    assert entry["responses"] == responses
