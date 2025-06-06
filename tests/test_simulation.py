import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import csv

import src.simulation as sim_module
from src.state import FighterState  # Keep for spec

# from src.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from src.engine import constants as C
from src.config import CONFIG


@pytest.mark.asyncio
@patch("src.simulation.get_fighter_attempt", new_callable=AsyncMock)
@patch("src.simulation.judge_phase1", new_callable=AsyncMock)
@patch("src.simulation.judge_phase2", new_callable=AsyncMock)
@patch("src.state.FighterState.from_preset")  # This is the crucial mock for instances inside _single_fight
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
        with patch.object(sim_module, "RUNS", 4), patch.object(sim_module, "CONCURRENT_RUNS", 2):
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
        with patch.object(sim_module, "RUNS", 3), patch.object(sim_module, "CONCURRENT_RUNS", 1):
            await sim_module.run_batch(tmp_path / "result.csv")

    assert calls == 3


@pytest.mark.asyncio
async def test_run_batch_handles_errors(tmp_path):
    async def failing_fight():
        raise RuntimeError("boom")

    with (
        patch.object(sim_module, "_single_fight", side_effect=failing_fight),
        patch.object(sim_module, "RUNS", 2),
        patch.object(sim_module, "CONCURRENT_RUNS", 1),
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

    with (
        patch.object(sim_module, "_single_fight", side_effect=RuntimeError("should not run")) as mock_fight,
        patch.object(sim_module, "RUNS", 0),
        patch.object(sim_module, "CONCURRENT_RUNS", 1),
    ):
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
