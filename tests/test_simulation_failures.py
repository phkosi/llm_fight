from unittest.mock import AsyncMock, MagicMock

import pytest

import llm_fight.simulation as sim_module
from llm_fight.engine import constants as C
from llm_fight.state import FighterState


@pytest.mark.asyncio
async def test_single_fight_raises_on_guarded_call(monkeypatch):
    async def fail_guarded(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("llm_fight.validation.guarded_call", fail_guarded)
    monkeypatch.setattr("llm_fight.judge.guarded_call", fail_guarded)

    fighter_a = MagicMock(spec=FighterState)
    fighter_a.id = "A"
    fighter_a.status = C.FighterStatus.FIGHTING
    fighter_a.to_json.return_value = {}
    fighter_a.apply_delta = MagicMock()
    fighter_a.apply_effects = MagicMock()

    fighter_b = MagicMock(spec=FighterState)
    fighter_b.id = "B"
    fighter_b.status = C.FighterStatus.FIGHTING
    fighter_b.to_json.return_value = {}
    fighter_b.apply_delta = MagicMock()
    fighter_b.apply_effects = MagicMock()

    monkeypatch.setattr(
        sim_module.FighterState,
        "from_preset",
        MagicMock(side_effect=[fighter_a, fighter_b]),
    )
    monkeypatch.setattr(sim_module, "get_fighter_attempt", AsyncMock(return_value="attack"))

    with pytest.raises(RuntimeError):
        await sim_module._single_fight()
