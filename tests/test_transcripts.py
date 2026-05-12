import json

import llm_fight.config as config_mod
import llm_fight.transcripts as transcripts
from llm_fight.config import Config
from llm_fight.engine import constants as C


def test_log_exchange_creates_file(tmp_path, monkeypatch):
    ini = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_SAVE_TRANSCRIPTS}=true\n{C.CONFIG_TRANSCRIPT_DIR}={tmp_path / 'logs'}\n"
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
    ini = f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_SAVE_TRANSCRIPTS}=true\n{C.CONFIG_TRANSCRIPT_DIR}={tmp_path / 'logs'}\n"
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(ini)
    custom_cfg = Config(cfg_path)

    monkeypatch.setattr(config_mod, "CONFIG", custom_cfg)

    from datetime import datetime as real_datetime

    class DummyDateTime:
        counter = 0

        @classmethod
        def now(cls, tz=None):
            cls.counter += 1
            return real_datetime(2025, 1, 1, 12, 0, 0, cls.counter)

    monkeypatch.setattr(transcripts, "datetime", DummyDateTime)

    transcripts.log_exchange([{"role": "user", "content": "a"}], ["1"])
    transcripts.log_exchange([{"role": "user", "content": "b"}], ["2"])

    log_dir = tmp_path / "logs"
    files = sorted(log_dir.iterdir())
    assert len(files) == 2
    assert files[0].name != files[1].name


def test_create_fight_trace_disabled_is_silent(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_TRANSCRIPT_DIR}={tmp_path / 'logs'}\n")
    monkeypatch.setattr(config_mod, "CONFIG", Config(cfg_path))

    writer = transcripts.create_fight_trace(run_index=1, fight_id="disabled")
    writer.write_event(event="fight_start", phase="fight", data={})

    assert not (tmp_path / "logs").exists()


def test_active_trace_routes_exchange_to_fight_jsonl(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(
        f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_SAVE_TRANSCRIPTS}=true\n{C.CONFIG_TRANSCRIPT_DIR}={tmp_path / 'logs'}\n"
    )
    monkeypatch.setattr(config_mod, "CONFIG", Config(cfg_path))

    writer = transcripts.create_fight_trace(run_index=2, fight_id="fightabc")
    with (
        transcripts.active_trace(writer),
        transcripts.llm_trace_context(phase="fighter_action", turn=3, fighter_id=C.FIGHTER_A),
    ):
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "act"}],
            ["strike"],
            [{"prompt_tokens": 4, "completion_tokens": 2, "eval_duration": 9}],
        )

    log_dir = tmp_path / "logs"
    assert list(log_dir.glob("*.json")) == []
    files = list(log_dir.glob("*.jsonl"))
    assert len(files) == 1
    event = json.loads(files[0].read_text(encoding="utf-8"))
    assert event["schema_version"] == transcripts.TRACE_SCHEMA_VERSION
    assert event["event_index"] == 0
    assert event["fight_id"] == "fightabc"
    assert event["run_index"] == 2
    assert event["turn"] == 3
    assert event["phase"] == "fighter_action"
    assert event["event"] == "llm_exchange"
    assert event["fighter_id"] == C.FIGHTER_A
    assert event["data"]["messages"][0][C.AGENT_CONTENT] == "act"
    assert event["data"]["responses"] == ["strike"]
    assert event["data"]["metadata"][0]["completion_tokens"] == 2


def test_trace_writer_orders_events(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.ini"
    cfg_path.write_text(
        f"[{C.CONFIG_GENERAL}]\n{C.CONFIG_SAVE_TRANSCRIPTS}=true\n{C.CONFIG_TRANSCRIPT_DIR}={tmp_path / 'logs'}\n"
    )
    monkeypatch.setattr(config_mod, "CONFIG", Config(cfg_path))

    writer = transcripts.create_fight_trace(fight_id="ordered")
    writer.write_event(event="fight_start", phase="fight", data={})
    writer.write_event(event="fight_complete", phase="fight", data={C.WINNER: C.DRAW})

    [path] = list((tmp_path / "logs").glob("*.jsonl"))
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [event["event_index"] for event in events] == [0, 1]
    assert [event["event"] for event in events] == ["fight_start", "fight_complete"]
