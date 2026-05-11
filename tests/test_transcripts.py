import json
from llm_fight.config import Config
from llm_fight.engine import constants as C
import llm_fight.transcripts as transcripts
import llm_fight.config as config_mod


def test_log_exchange_creates_file(tmp_path, monkeypatch):
    ini = (
        f"[{C.CONFIG_GENERAL}]\n" f"{C.CONFIG_SAVE_TRANSCRIPTS}=true\n" f"{C.CONFIG_TRANSCRIPT_DIR}={tmp_path/'logs'}\n"
    )
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    custom_cfg = Config(cfg_path)

    monkeypatch.setattr(config_mod, "CONFIG", custom_cfg)

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


def test_log_exchange_unique_timestamps(tmp_path, monkeypatch):
    ini = (
        f"[{C.CONFIG_GENERAL}]\n" f"{C.CONFIG_SAVE_TRANSCRIPTS}=true\n" f"{C.CONFIG_TRANSCRIPT_DIR}={tmp_path/'logs'}\n"
    )
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    custom_cfg = Config(cfg_path)

    monkeypatch.setattr(config_mod, "CONFIG", custom_cfg)

    from datetime import datetime as real_datetime

    class DummyDateTime:
        counter = 0

        @classmethod
        def now(cls):
            cls.counter += 1
            return real_datetime(2025, 1, 1, 12, 0, 0, cls.counter)

    monkeypatch.setattr(transcripts, "datetime", DummyDateTime)

    transcripts.log_exchange([{"role": "user", "content": "a"}], ["1"])
    transcripts.log_exchange([{"role": "user", "content": "b"}], ["2"])

    log_dir = tmp_path / "logs"
    files = sorted(log_dir.iterdir())
    assert len(files) == 2
    assert files[0].name != files[1].name
