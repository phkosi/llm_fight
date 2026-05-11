import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import csv
import json
import os

import llm_fight.simulation as sim_module
from llm_fight.state import FighterState  # Keep for spec

# from llm_fight.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from llm_fight.engine import constants as C
from llm_fight.config import CONFIG


@pytest.mark.asyncio
@patch("llm_fight.simulation.get_fighter_attempt", new_callable=AsyncMock)
@patch("llm_fight.simulation.judge_phase1", new_callable=AsyncMock)
@patch("llm_fight.simulation.judge_phase2", new_callable=AsyncMock)
@patch("llm_fight.state.FighterState.from_preset")  # This is the crucial mock for instances inside _single_fight
async def test_single_fight_runs_to_completion(
    mock_from_preset,  # Renamed for clarity, this is the mock for FighterState.from_preset
    mock_judge_p2,
    mock_judge_p1,
    mock_get_fighter_attempt,
):
    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "5")

    # Create MagicMock instances for fighters
    fighter_a_mock = MagicMock(spec=FighterState)
    fighter_a_mock.id = "A"
    fighter_a_mock.status = C.FighterStatus.FIGHTING
    fighter_a_mock.parts = {"head": object(), "torso": object()}
    fighter_a_mock.to_json.return_value = {
        "id": "A",
        C.STATUS: C.FighterStatus.FIGHTING,
        C.PAIN: 0,
    }  # For judge_phase1 context
    fighter_a_mock.apply_delta = MagicMock()  # Ensure it can be called
    fighter_a_mock.apply_effects = MagicMock()  # Ensure it can be called

    fighter_b_mock = MagicMock(spec=FighterState)
    fighter_b_mock.id = "B"
    fighter_b_mock.status = C.FighterStatus.FIGHTING
    fighter_b_mock.parts = {"head": object(), "torso": object()}
    fighter_b_mock.to_json.return_value = {"id": "B", C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0}

    # Define side effect for B's apply_delta to change status
    def b_apply_delta_side_effect(delta):
        if delta.get(C.STATUS_CHANGE) == C.FighterStatus.UNCONSCIOUS:
            fighter_b_mock.status = C.FighterStatus.UNCONSCIOUS

    fighter_b_mock.apply_delta.side_effect = b_apply_delta_side_effect
    fighter_b_mock.apply_effects = MagicMock()

    # Set the side_effect for the mocked FighterState.from_preset
    mock_from_preset.side_effect = [fighter_a_mock, fighter_b_mock]

    mock_get_fighter_attempt.return_value = "Some attempt"
    mock_judge_p1.return_value = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
        "judgement_text": "Judgement P1",
        "explanation": "",
    }

    async def p2_side_effect(p2_input_state, rolls):
        # This delta will be passed to fighter_b_mock.apply_delta
        return {
            "narration": "A lands a decisive blow! B is knocked out!",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: C.FighterStatus.UNCONSCIOUS}},
            "fight_end": True,
            "winner": "A",  # Winner is determined by ID string
        }

    mock_judge_p2.side_effect = p2_side_effect

    with patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True) as mock_rand_obj:
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == "A"
    assert result[C.LOG_TURN] == "1"
    mock_get_fighter_attempt.assert_called()
    mock_judge_p1.assert_called_once()
    assert "recent_log" in mock_judge_p1.call_args.kwargs
    mock_judge_p2.assert_called_once()
    mock_rand_obj.assert_called()

    fighter_b_mock.apply_delta.assert_called_with({C.STATUS_CHANGE: C.FighterStatus.UNCONSCIOUS})
    assert fighter_b_mock.status == C.FighterStatus.UNCONSCIOUS
    assert fighter_a_mock.status == C.FighterStatus.FIGHTING  # A should be unchanged


@pytest.mark.asyncio
async def test_single_fight_uses_one_fixed_ollama_context_for_all_native_calls():
    old_values = {
        (C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, str),
        (C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, str),
        (C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER, str),
        (C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, str),
        (C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, str),
        (C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS): CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str),
    }
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, "32768")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE, "10m")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, "64")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, "128")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER, "1")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE, "1")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, "0")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, "false")
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    payloads = []

    async def fake_post_json(session, payload, retries=0):
        payloads.append(payload)
        schema = payload.get(C.AGENT_FORMAT)
        if not schema:
            return "I make a cautious attack."

        properties = schema.get(C.SCHEMA_PROPERTIES, {})
        if C.NARRATION in properties:
            return json.dumps(
                {
                    C.NARRATION: "Both fighters test range and reset.",
                    C.DELTA: {},
                    C.FIGHT_END: False,
                    C.WINNER: None,
                }
            )
        return json.dumps(
            {
                "judgement_text": "Both attacks are plausible.",
                f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
                f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
                f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
                f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            }
        )

    try:
        with (
            patch("llm_fight.agents._post_json", new=fake_post_json),
            patch.dict(os.environ, {"API_URL": "http://localhost:11434/api/chat"}),
        ):
            result = await sim_module._single_fight()
    finally:
        for (section, key), value in old_values.items():
            CONFIG.set(section, key, value)

    assert result == {C.WINNER: C.DRAW, C.LOG_TURN: "1"}
    assert len(payloads) == 4
    assert {payload[C.AGENT_OPTIONS][C.NUM_CTX] for payload in payloads} == {32768}
    assert {payload[C.AGENT_KEEP_ALIVE] for payload in payloads} == {"10m"}

    fighter_payloads = [payload for payload in payloads if C.AGENT_FORMAT not in payload]
    judge_payloads = [payload for payload in payloads if C.AGENT_FORMAT in payload]
    assert len(fighter_payloads) == 2
    assert len(judge_payloads) == 2
    assert all(1 <= payload[C.AGENT_OPTIONS][C.AGENT_NUM_PREDICT] <= 64 for payload in fighter_payloads)
    assert all(1 <= payload[C.AGENT_OPTIONS][C.AGENT_NUM_PREDICT] <= 128 for payload in judge_payloads)


@pytest.mark.asyncio
async def test_run_batch_concurrency(tmp_path):

    running = 0
    max_running = 0
    lock = asyncio.Lock()

    async def fake_fight(*args, **kwargs):
        nonlocal running, max_running
        async with lock:
            running += 1
            if running > max_running:
                max_running = running
        await asyncio.sleep(0.01)
        async with lock:
            running -= 1
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 4
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 2
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            out_file = tmp_path / "result.csv"
            ret = await sim_module.run_batch(out_file)

    assert max_running == 2
    assert ret == out_file
    assert out_file.exists()


@pytest.mark.asyncio
async def test_run_batch_exact_runs(tmp_path):
    calls = 0

    async def fake_fight(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 3
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            await sim_module.run_batch(tmp_path / "result.csv")

    assert calls == 3


@pytest.mark.asyncio
async def test_run_batch_progress_callback(tmp_path):
    async def fake_fight(*args, **kwargs):
        await asyncio.sleep(0)
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    progress_calls = []

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            out_file = tmp_path / "prog.csv"

            def cb(done, total):
                progress_calls.append((done, total))

            await sim_module.run_batch(out_file, progress=cb)

    assert progress_calls == [(1, 2), (2, 2)]


@pytest.mark.asyncio
async def test_run_batch_flushes_each_completed_result(tmp_path):
    calls = 0
    first_progress_rows = []

    async def fake_fight(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {C.WINNER: "A" if calls == 1 else "B", C.LOG_TURN: str(calls)}

    out_file = tmp_path / "incremental.csv"

    def progress(done, total):
        if done == 1:
            with open(out_file, newline="") as fp:
                first_progress_rows.extend(csv.DictReader(fp))

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            path = await sim_module.run_batch(out_file, progress=progress)

    assert path == out_file
    assert first_progress_rows == [{C.WINNER: "A", C.LOG_TURN: "1"}]

    with open(out_file, newline="") as fp:
        final_rows = list(csv.DictReader(fp))
    assert final_rows == [
        {C.WINNER: "A", C.LOG_TURN: "1"},
        {C.WINNER: "B", C.LOG_TURN: "2"},
    ]


@pytest.mark.asyncio
async def test_run_batch_handles_errors(tmp_path):
    async def failing_fight(*args, **kwargs):
        raise RuntimeError("boom")

    with patch.object(sim_module, "_single_fight", side_effect=failing_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with (
            patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
            patch.object(sim_module.logger, "exception") as mock_exc,
        ):
            out_file = tmp_path / "err.csv"
            path = await sim_module.run_batch(out_file)

    assert path == out_file
    with open(out_file, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 2
    assert all(row[C.WINNER] == "error" for row in rows)
    assert mock_exc.call_count == 2


@pytest.mark.asyncio
async def test_run_batch_zero_runs(tmp_path):
    out_file = tmp_path / "empty.csv"

    with patch.object(sim_module, "_single_fight", side_effect=RuntimeError("should not run")) as mock_fight:
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 0
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            path = await sim_module.run_batch(out_file)

    assert path == out_file
    assert out_file.exists()
    with open(out_file, newline="") as fp:
        reader = csv.DictReader(fp)
        rows = list(reader)

    assert reader.fieldnames == [C.WINNER, C.LOG_TURN]
    assert rows == []
    mock_fight.assert_not_called()


@pytest.mark.asyncio
async def test_turn_logging_respects_setting():
    async def fake_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A hits",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            "narration": "A wins",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}},
            "fight_end": True,
            "winner": "A",
        }

    original_setting = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False)
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, "true")

    with (
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        patch.object(sim_module.logger, "info") as mock_info,
    ):
        await sim_module._single_fight()

    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, str(original_setting).lower())

    assert any("Turn 1" in call.args[0] for call in mock_info.call_args_list)


@pytest.mark.asyncio
async def test_invalid_failed_attempts_cannot_apply_p2_damage_or_winner():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        fighters.append(fighter)
        return fighter

    async def fake_get_attempt(*args, **kwargs):
        return ""

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "Both attempts are empty.",
            "explanation": "No valid actions.",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "The judge wrongly invents a decisive wound.",
            C.DELTA: {C.FIGHTER_A: {}, C.FIGHTER_B: {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}},
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    with (
        patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module.logger, "warning") as mock_warning,
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert fighters[1].status == C.FighterStatus.FIGHTING
    assert any("both attempts were invalid and failed" in call.args[0] for call in mock_warning.call_args_list)
