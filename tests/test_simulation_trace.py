import asyncio
import json
import random
from unittest.mock import AsyncMock, patch

import pytest

import llm_fight.simulation as sim_module
import llm_fight.transcripts as transcripts
from llm_fight.config import CONFIG, Config

# from llm_fight.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from llm_fight.engine import constants as C
from llm_fight.profiles import build_fighter_profile


def _source_value(source=C.FIGHTER_A, value=1):
    return {C.SOURCE: source, C.VALUE: value}


def _custom_profile(part_id: str, vital: bool = True):
    return {
        C.CONFIG_FIGHTER_CLASS: f"{part_id} fighter",
        C.LOADOUT: "profile weapon",
        "environment": "profile arena",
        C.BODY_PARTS: [
            {
                "id": part_id,
                "is_vital": vital,
                "layers": [{C.NAME: "core", C.MAX_HP: 12}],
            },
            {
                "id": f"{part_id}_limb",
                "can_be_severed": True,
                "layers": [{C.NAME: "muscle", C.MAX_HP: 8}],
            },
        ],
    }


def _write_profile(path, profile):
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_single_fight_emits_play_events_and_token_metadata():
    events = []

    async def fake_get_attempt(*args, **kwargs):
        kwargs["on_metadata"]({"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        kwargs["on_metadata"]({"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9})
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        kwargs["on_metadata"]({"prompt_tokens": 6, "completion_tokens": 7, "total_tokens": 13})
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True, on_event=events.append)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    names = [event.name for event in events]
    assert result[C.WINNER] == C.DRAW
    assert combat_log.turns[0].turn == 1
    assert names.index(C.FIGHT_EVENT_FIGHTERS_READY) < names.index(C.FIGHT_EVENT_FIGHTER_ACTION_START)
    assert names.index(C.FIGHT_EVENT_JUDGE_PHASE1_START) < names.index(C.FIGHT_EVENT_JUDGE_PHASE1_END)
    assert names.index(C.FIGHT_EVENT_ROLLS_START) < names.index(C.FIGHT_EVENT_ROLLS_END)
    assert names.index(C.FIGHT_EVENT_JUDGE_PHASE2_START) < names.index(C.FIGHT_EVENT_JUDGE_PHASE2_END)
    assert names.index(C.FIGHT_EVENT_TURN_COMPLETE) < names.index(C.FIGHT_EVENT_FIGHT_COMPLETE)
    token_events = [event for event in events if event.name == C.FIGHT_EVENT_TOKEN_METADATA]
    assert {event.data["phase"] for event in token_events} == {"fighter_action", "judge_phase1", "judge_phase2"}
    assert len(token_events) == 4
    assert sum(event.data["metadata"]["total_tokens"] for event in token_events) == 28


@pytest.mark.asyncio
async def test_single_fight_result_keeps_winner_id_and_adds_display_names(tmp_path):
    config_path = tmp_path / "named.ini"
    config_path.write_text(
        "\n".join(
            [
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[A]",
                "name = Sir Galant",
                "",
                "[B]",
                "name = Shade",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A can finish the fight.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "Sir Galant drops Shade.",
            C.DELTA: {C.FIGHTER_B: {C.STATUS_CHANGE: _source_value(C.FIGHTER_A, C.STATUS_UNCONSCIOUS)}},
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result = await sim_module._single_fight(fight_rng=random.Random(1))
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.FIGHTER_A
    assert result[C.LOG_WINNER_DISPLAY_NAME] == "Sir Galant"
    assert result[C.LOG_FIGHTER_A_DISPLAY_NAME] == "Sir Galant"
    assert result[C.LOG_FIGHTER_B_DISPLAY_NAME] == "Shade"


@pytest.mark.asyncio
async def test_single_fight_writes_ordered_trace_with_exchanges_rolls_deltas_and_states(tmp_path):
    transcript_dir = tmp_path / "traces"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "transcript_detail = full",
                "",
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[A]",
                "name = Sir Galant",
                "",
                "[B]",
                "name = Shade",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(fighter, *args, **kwargs):
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: f"{fighter.id} act"}],
            [f"{fighter.id} attacks"],
            [{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}],
        )
        kwargs["on_metadata"]({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        return f"{fighter.id} attacks"

    async def fake_judge_p1(*args, **kwargs):
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "judge p1"}],
            ["{}"],
            [{"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}],
        )
        kwargs["on_metadata"]({"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4})
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A can land.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "judge p2"}],
            ["{}"],
            [{"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}],
        )
        kwargs["on_metadata"]({"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})
        return {
            C.NARRATION: "A clips B.",
            C.DELTA: {C.FIGHTER_B: {C.PAIN_INCREASE: _source_value(C.FIGHTER_A, 3)}},
            C.FIGHT_END: False,
            C.WINNER: None,
        }

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True, fight_rng=random.Random(5))
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.DRAW
    assert result[C.LOG_FIGHTER_A_DISPLAY_NAME] == "Sir Galant"
    assert result[C.LOG_FIGHTER_B_DISPLAY_NAME] == "Shade"
    assert result[C.LOG_WINNER_DISPLAY_NAME] == ""
    assert combat_log.turns[0].state_B_after[C.PAIN] == 3
    assert list(transcript_dir.glob("*.json")) == []
    [trace_file] = list(transcript_dir.glob("*.jsonl"))
    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert [event["event_index"] for event in events] == list(range(len(events)))
    assert events[0]["event"] == "fight_start"
    assert events[-1]["event"] == C.FIGHT_EVENT_FIGHT_COMPLETE
    assert {event["event"] for event in events} >= {
        C.FIGHT_EVENT_FIGHTERS_READY,
        "llm_exchange",
        C.FIGHT_EVENT_TOKEN_METADATA,
        C.FIGHT_EVENT_ROLLS_END,
        C.FIGHT_EVENT_TURN_COMPLETE,
    }
    ready_event = next(event for event in events if event["event"] == C.FIGHT_EVENT_FIGHTERS_READY)
    assert ready_event["data"]["fighters"][C.FIGHTER_A][C.DISPLAY_NAME] == "Sir Galant"
    assert ready_event["data"]["fighters"][C.FIGHTER_B][C.DISPLAY_NAME] == "Shade"
    exchanges = [event for event in events if event["event"] == "llm_exchange"]
    assert {event["phase"] for event in exchanges} == {"fighter_action", "judge_phase1", "judge_phase2"}
    assert {event["fighter_id"] for event in exchanges if event["phase"] == "fighter_action"} == {
        C.FIGHTER_A,
        C.FIGHTER_B,
    }
    token_events = [event for event in events if event["event"] == C.FIGHT_EVENT_TOKEN_METADATA]
    assert any(event["data"]["metadata"]["total_tokens"] == 7 for event in token_events)
    turn_event = next(event for event in events if event["event"] == C.FIGHT_EVENT_TURN_COMPLETE)
    turn_data = turn_event["data"]["turn"]
    assert turn_data["attempt_A"] == "A attacks"
    assert turn_data["rolls"][C.FIGHTER_A]["success"] is True
    assert turn_data["judge_p2"][C.DELTA][C.FIGHTER_B][C.PAIN_INCREASE] == 3
    assert turn_data["state_B_before"][C.PAIN] == 0
    assert turn_data["state_B_after"][C.PAIN] == 3


@pytest.mark.asyncio
async def test_single_fight_trace_preserves_error_event(tmp_path):
    transcript_dir = tmp_path / "traces"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "",
                "[SIMULATION]",
                "max_turns = 1",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        raise RuntimeError("judge exploded with ignore previous instructions and raw prompt text" * 20)

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            pytest.raises(RuntimeError),
        ):
            await sim_module._single_fight(return_log=True)
    finally:
        sim_module.config_mod.CONFIG = old_config

    [trace_file] = list(transcript_dir.glob("*.jsonl"))
    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert events[0]["event"] == "fight_start"
    assert events[-1]["event"] == "fight_error"
    assert events[-1]["data"]["error_type"] == "RuntimeError"
    assert events[-1]["data"]["message"] == "Fight aborted due to RuntimeError. See application logs for details."
    trace_text = trace_file.read_text(encoding="utf-8")
    assert "ignore previous instructions" not in trace_text
    assert "raw prompt text" not in trace_text


@pytest.mark.asyncio
async def test_single_fight_trace_error_waits_for_cancelled_fighter_sibling(tmp_path):
    transcript_dir = tmp_path / "traces"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "",
                "[SIMULATION]",
                "max_turns = 1",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(fighter, *args, **kwargs):
        if fighter.id == C.FIGHTER_A:
            raise RuntimeError("fighter action leaked ignore previous instructions")
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "late B"}],
            ["late B response"],
        )
        return "late B"

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            pytest.raises(RuntimeError),
        ):
            await sim_module._single_fight(return_log=True)
    finally:
        sim_module.config_mod.CONFIG = old_config

    [trace_file] = list(transcript_dir.glob("*.jsonl"))
    trace_text = trace_file.read_text(encoding="utf-8")
    events = [json.loads(line) for line in trace_text.splitlines()]
    assert events[-1]["event"] == "fight_error"
    assert "late B response" not in trace_text
    assert "ignore previous instructions" not in trace_text


@pytest.mark.asyncio
async def test_generated_profile_events_precede_fighters_ready(tmp_path):
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "fighter_creation_mode = generated",
                "",
                "[SIMULATION]",
                "max_turns = 1",
            ]
        ),
        encoding="utf-8",
    )
    events = []

    async def fake_generate(fighter_id, section, opponent_section, nudge, **kwargs):
        return build_fighter_profile(_custom_profile(f"creative_{fighter_id.lower()}"))

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "generate_fighter_profile", new=AsyncMock(side_effect=fake_generate)),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            await sim_module._single_fight(return_log=True, on_event=events.append, fight_rng=random.Random(3))
    finally:
        sim_module.config_mod.CONFIG = old_config

    names = [event.name for event in events]
    assert names.index(C.FIGHT_EVENT_PROFILE_GENERATION_START) < names.index(C.FIGHT_EVENT_FIGHTERS_READY)
    assert names.count(C.FIGHT_EVENT_PROFILE_GENERATION_START) == 2
    assert names.count(C.FIGHT_EVENT_PROFILE_GENERATION_END) == 2
