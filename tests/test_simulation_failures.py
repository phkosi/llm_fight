import csv
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import src.simulation as sim_module
from src.engine import constants as C
from src.state import FighterState


@pytest.mark.asyncio
async def test_single_fight_raises_on_guarded_call(monkeypatch):
    async def fail_guarded(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.validation.guarded_call", fail_guarded)
    monkeypatch.setattr("src.judge.guarded_call", fail_guarded)

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


@pytest.mark.asyncio
async def test_run_batch_partial_results_on_guarded_call_failure(monkeypatch, tmp_path):
    async def fail_guarded(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.validation.guarded_call", fail_guarded)
    monkeypatch.setattr("src.judge.guarded_call", fail_guarded)

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

    out_file = tmp_path / "results.csv"
    with (
        patch.object(sim_module, "RUNS", 2),
        patch.object(sim_module, "CONCURRENT_RUNS", 1),
        patch.object(sim_module.logger, "exception") as mock_exc,
    ):
        path = await sim_module.run_batch(out_file)

    assert path == out_file
    with open(out_file, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 2
    assert all(row[C.WINNER] == "error" for row in rows)
    assert mock_exc.call_count == 2
