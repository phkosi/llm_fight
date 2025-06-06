import csv
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

import src.simulation as sim_module
from src.engine import constants as C
from src.config import CONFIG


@pytest.mark.asyncio
async def test_short_single_fight_integration():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset)
        fighters.append(fighter)
        return fighter

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A hits B",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            "narration": "A knocks out B",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}},
            "fight_end": True,
            "winner": "A",
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "3")

    with (
        patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == "A"
    assert result[C.LOG_TURN] == "1"
    assert len(fighters) == 2
    assert fighters[1].status == C.STATUS_UNCONSCIOUS


@pytest.mark.asyncio
async def test_run_batch_short_simulation(tmp_path):
    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A hits B",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            "narration": "A knocks out B",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}},
            "fight_end": True,
            "winner": "A",
        }

    with (
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
    ):
        orig_get = sim_module.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.CONFIG, "get", side_effect=fake_get):
            out_file = tmp_path / "results.csv"
            path = await sim_module.run_batch(out_file)

    assert path == out_file
    with open(path, newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert len(rows) == 2
    assert all(row[C.WINNER] == "A" for row in rows)


@pytest.mark.asyncio
async def test_two_turn_single_fight_integration():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset)
        fighters.append(fighter)
        return fighter

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A hits B",
            "explanation": "",
        }

    p2_responses = [
        {
            "narration": "A wounds B",
            "delta": {"A": {}, "B": {C.PAIN_INCREASE: 5}},
            "fight_end": False,
            "winner": None,
        },
        {
            "narration": "A knocks out B",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}},
            "fight_end": True,
            "winner": "A",
        },
    ]
    p2_iter = iter(p2_responses)

    async def fake_judge_p2(*args, **kwargs):
        return next(p2_iter)

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "5")

    with (
        patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == "A"
    assert result[C.LOG_TURN] == "2"
    assert len(fighters) == 2
    assert fighters[1].pain == 5
    assert fighters[1].status == C.STATUS_UNCONSCIOUS


@pytest.mark.asyncio
async def test_draw_after_max_turns():
    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No progress",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            "narration": "Stalemate",
            "delta": {"A": {}, "B": {}},
            "fight_end": False,
            "winner": None,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "2")

    with (
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert result[C.LOG_TURN] == "2"
