import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import llm_fight.simulation as sim_module
from llm_fight.state import FighterState
from llm_fight.engine import constants as C
from llm_fight.config import CONFIG


@pytest.mark.asyncio
async def test_single_fight_logs_invalid_probabilities(tmp_path):
    # Setup fighter mocks
    fighter_a = MagicMock(spec=FighterState)
    fighter_a.id = "A"
    fighter_a.status = C.FighterStatus.FIGHTING
    fighter_a.parts = {"head": object(), "torso": object()}
    fighter_a.to_json.return_value = {"id": "A", C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0}
    fighter_a.apply_delta = MagicMock()
    fighter_a.apply_effects = MagicMock()

    fighter_b = MagicMock(spec=FighterState)
    fighter_b.id = "B"
    fighter_b.status = C.FighterStatus.FIGHTING
    fighter_b.parts = {"head": object(), "torso": object()}
    fighter_b.to_json.return_value = {"id": "B", C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0}
    fighter_b.apply_delta = MagicMock()
    fighter_b.apply_effects = MagicMock()

    # Prepare config for short fight
    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "2")

    p1_response = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "bad",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "oops",
        "judgement_text": "",  # minimal
        "explanation": "",
    }
    p2_response = {"narration": "", "delta": {}, "fight_end": True, "winner": None}

    with (
        patch.object(sim_module.FighterState, "from_preset", side_effect=[fighter_a, fighter_b]),
        patch.object(sim_module, "get_fighter_attempt", AsyncMock(return_value="atk")),
        patch.object(sim_module, "judge_phase1", AsyncMock(return_value=p1_response)),
        patch.object(sim_module, "judge_phase2", AsyncMock(return_value=p2_response)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        patch.object(sim_module.logger, "warning") as mock_warn,
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == "draw"
    # Two warnings, one for each bad probability
    assert mock_warn.call_count == 2
    assert "Fighter A" in mock_warn.call_args_list[0].args[0]
    assert "Fighter B" in mock_warn.call_args_list[1].args[0]
