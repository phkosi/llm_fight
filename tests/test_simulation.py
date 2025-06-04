import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import json

import src.simulation as sim_module
from src.state import FighterState # Keep for spec
# from src.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from src.engine import constants as C
from src.config import CONFIG

@pytest.mark.asyncio
@patch('src.simulation.get_fighter_attempt', new_callable=AsyncMock)
@patch('src.simulation.judge_phase1', new_callable=AsyncMock)
@patch('src.simulation.judge_phase2', new_callable=AsyncMock)
@patch('src.state.FighterState.from_preset') # This is the crucial mock for instances inside _single_fight
async def test_single_fight_runs_to_completion(
    mock_from_preset, # Renamed for clarity, this is the mock for FighterState.from_preset
    mock_judge_p2, 
    mock_judge_p1, 
    mock_get_fighter_attempt
):
    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "5")

    # Create MagicMock instances for fighters
    fighter_a_mock = MagicMock(spec=FighterState)
    fighter_a_mock.id = 'A'
    fighter_a_mock.status = C.STATUS_FIGHTING
    fighter_a_mock.to_json.return_value = {'id': 'A', C.STATUS: C.STATUS_FIGHTING, C.PAIN: 0} # For judge_phase1 context
    fighter_a_mock.apply_delta = MagicMock() # Ensure it can be called
    fighter_a_mock.apply_effects = MagicMock() # Ensure it can be called

    fighter_b_mock = MagicMock(spec=FighterState)
    fighter_b_mock.id = 'B'
    fighter_b_mock.status = C.STATUS_FIGHTING
    fighter_b_mock.to_json.return_value = {'id': 'B', C.STATUS: C.STATUS_FIGHTING, C.PAIN: 0}
    
    # Define side effect for B's apply_delta to change status
    def b_apply_delta_side_effect(delta):
        if delta.get(C.STATUS_CHANGE) == C.STATUS_UNCONSCIOUS:
            fighter_b_mock.status = C.STATUS_UNCONSCIOUS
    fighter_b_mock.apply_delta.side_effect = b_apply_delta_side_effect
    fighter_b_mock.apply_effects = MagicMock()

    # Set the side_effect for the mocked FighterState.from_preset
    mock_from_preset.side_effect = [fighter_a_mock, fighter_b_mock]

    mock_get_fighter_attempt.return_value = "Some attempt"
    mock_judge_p1.return_value = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
        "judgement_text": "Judgement P1", "explanation": ""
    }
    async def p2_side_effect(p2_input_state, rolls):
        # This delta will be passed to fighter_b_mock.apply_delta
        return {
            "narration": "A lands a decisive blow! B is knocked out!",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}},
            "fight_end": True, "winner": "A" # Winner is determined by ID string
        }
    mock_judge_p2.side_effect = p2_side_effect

    with patch.object(sim_module, 'rand', MagicMock(return_value=0.0), create=True) as mock_rand_obj:
        result = await sim_module._single_fight()
    
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == 'A'
    assert result[C.LOG_TURN] == "1"
    mock_get_fighter_attempt.assert_called()
    mock_judge_p1.assert_called_once()
    mock_judge_p2.assert_called_once()
    mock_rand_obj.assert_called()
    
    fighter_b_mock.apply_delta.assert_called_with({C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS})
    assert fighter_b_mock.status == C.STATUS_UNCONSCIOUS
    assert fighter_a_mock.status == C.STATUS_FIGHTING # A should be unchanged 
